"""Agent 的 LLM 流式调用与工具执行（Mixin，由 Agent 继承）。

承载与「调用 LLM / 解析流式块 / 执行工具 / 产出工具事件」相关的方法。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any, AsyncIterator

from palm_sdk.core.config import settings
from .schemas import AgentEvent
from .question_hub import get_question_hub
from .tool_base import execute_tool_with_safety

_LOGGER = logging.getLogger(__name__)

# 推理链/最终回复流式超时阈值（秒）
_STALL_TIMEOUT = 60.0
_MAX_TOTAL_TIMEOUT = 300.0
# 未跨过 Action/Response 边界前，thought 缓冲达到该长度即下发一次
_THOUGHT_EMIT_INTERVAL = 50


def _make_thought_event(text: str) -> AgentEvent | None:
    """把一段思考文本封装为 thought 事件（空文本返回 None）。"""
    text = text.strip()
    if not text:
        return None
    return AgentEvent(type="thought", content=text[:2000])


class ExecutionMixin:
    """LLM 流式调用与工具执行。"""

    async def _invoke_llm_stream(self, messages: list[dict], llm_stream_fn: callable) -> AsyncIterator[AgentEvent]:
        """流式调用 LLM：边收边 yield thought 事件，完整输出存到 self._last_full_output。

        深思考模型（DeepSeek-R1 等）会先产出超长推理链(reasoning)再给正文：推理链
        经上游透传后作为 thought 事件实时下发，前端即时显示思考过程，不再卡 30s 空白。
        超时改为「停滞超时 + 总超时」双阈值：只要 token 在流动（含推理链）就不中断，
        仅当长时间无 token（真卡死）或累计过久才中止，避免一刀切误杀长推理。
        """
        collected = ""
        thought_buffer = ""
        crossed_boundary = False
        loop = asyncio.get_running_loop()
        start_ts = loop.time()
        last_activity_ts = start_ts
        boundary_re = re.compile(
            r"\*{0,2}(?:Action|Response|Answer|Thought|Observation|Final\s*Answer"
            r"|行动|动作|操作|步骤|思考|回复|回答|最终回答|执行)"
            r"\*?\*?\s*[:：]?")
        try:
            async for chunk in llm_stream_fn(messages, self._model):
                content, reasoning = self._normalize_llm_chunk(chunk)
                if not content and not reasoning:
                    continue
                now = loop.time()
                last_activity_ts = now
                # 推理链：直接作为 thought 实时下发，不进入边界判定、不并入最终解析文本。
                # 多轮 ReAct 中模型常重复复述前文，对已发射前缀做去重，只追加新增部分。
                if reasoning:
                    new_reasoning = self._deduplicate_reasoning_prefix(reasoning)
                    if new_reasoning:
                        evt = _make_thought_event(new_reasoning)
                        if evt:
                            yield evt
                if content:
                    collected += content
                    if not crossed_boundary and boundary_re.search(collected):
                        crossed_boundary = True
                        evt = _make_thought_event(thought_buffer)
                        if evt:
                            yield evt
                        thought_buffer = ""
                    if not crossed_boundary:
                        thought_buffer += content
                        if len(thought_buffer) >= _THOUGHT_EMIT_INTERVAL:
                            evt = _make_thought_event(thought_buffer)
                            if evt:
                                yield evt
                            thought_buffer = ""
                # 仅当确实无 token 流动（停滞）或累计过久才中止
                if self._is_llm_stream_timed_out(now, start_ts, last_activity_ts):
                    _LOGGER.info(
                        "LLM 调用超时（停滞 %.0fs/总 %.0fs），返回已收集 %d 字符",
                        now - last_activity_ts, now - start_ts, len(collected))
                    break
            # 刷新剩余 thought
            evt = _make_thought_event(thought_buffer)
            if evt:
                yield evt
        except Exception as exc:
            _LOGGER.error("LLM 流式调用异常: %s", exc)
            self._last_full_output = None
            return
        self._last_full_output = collected.strip() or None

    def _normalize_llm_chunk(self, chunk) -> tuple[str, str]:
        """把上游 chunk 统一为 (正文, 推理链) 二元组，兼容 dict/str/对象三种格式。"""
        if isinstance(chunk, dict):
            return chunk.get("content") or "", chunk.get("reasoning") or ""
        if isinstance(chunk, str):
            return chunk, ""
        content = getattr(chunk, "content", None) or getattr(chunk, "delta", "") or ""
        reasoning = getattr(chunk, "reasoning", None) or ""
        return content, reasoning

    def _is_llm_stream_timed_out(self, now: float, start_ts: float, last_activity_ts: float) -> bool:
        """停滞超时或总超时任一触发即中止（双阈值避免误杀长推理）。"""
        return (now - last_activity_ts > _STALL_TIMEOUT
                or now - start_ts > _MAX_TOTAL_TIMEOUT)

    def _deduplicate_reasoning_prefix(self, text: str) -> str:
        """去除 reasoning 中已发射的重复前缀，返回新增部分。

        模型在多轮 ReAct 中倾向于重述之前的尝试，导致用户看到两段思考前段相同。
        当新文本与已发射文本的公共前缀足够长（≥30 字符且占新文本 ≥40%）时，
        只保留首次出现之后的增量内容。
        """
        text = text.strip()
        if not text:
            return ""
        prev = self._emitted_reasoning
        if not prev:
            self._emitted_reasoning = text
            return text
        # 找最长公共前缀
        max_len = min(len(prev), len(text))
        common = 0
        for i in range(max_len):
            if prev[i] != text[i]:
                break
            common = i + 1
        if common >= 30 and common / len(text) >= 0.4:
            self._emitted_reasoning = prev + text[common:]
            return text[common:]
        # 公共前缀不够长：仍整体追加，避免截断真正的新推理
        self._emitted_reasoning = prev + text
        return text

    def _split_delta(self, text: str) -> list[str]:
        """把最终回答切成小窗口，优先在句末标点处断，供逐块流式发射。

        让前端有真实打字机效果，避免 ReAct 判定为最终回答后整段瞬间砸下。
        """
        if not text:
            return []
        chunks: list[str] = []
        buf = ""
        for ch in text:
            buf += ch
            if ch in "。！？!?；;\n" or len(buf) >= 16:
                chunks.append(buf)
                buf = ""
        if buf:
            chunks.append(buf)
        return chunks

    def _is_repeat_call(self, name: str, inp: dict, history: list[tuple[str, str]]) -> bool:
        """检测同一工具+同一输入是否已调用 ≥2 次。"""
        # 桌面感知/执行工具：界面每步都在变，重复调用是合法行为，必须排除去重。
        # 漏掉 describe_window/run_automation 会导致 LLM 重新感知界面被拦截、陷入死循环。
        desktop_tools = {
            "hotkey", "type_text", "press_key", "move_mouse", "click_mouse",
            "scroll_mouse", "take_screenshot", "screenshot_region",
            "list_windows", "focus_window", "get_active_window", "get_window_rect",
            "minimize_window", "maximize_window", "restore_window", "close_window",
            "wait_for_window", "wait_for_pixel", "wait_seconds",
            "describe_window", "run_automation",
        }
        if name in desktop_tools:
            return False
        key = (name, json.dumps(inp, sort_keys=True))
        history.append(key)
        return sum(1 for call in history if call == key) >= 2

    async def _handle_tool_call(
        self, name: str, inp: dict,
        tool_call_history: list[tuple[str, str]],
        adjudicator_check_fn: callable | None,
    ) -> tuple[str | None, str, list]:
        """执行工具调用（校验→裁决→防重复→执行），返回 (action_type, exec_message, artifacts)。

        Returns:
            (None, exec_message, artifacts) → 正常执行
            ("blocked", reason, []) → 裁决拦截
            ("dedup", message, []) → 防重复拦截+自动写文件
            ("missing", message, []) → 工具不存在
        """
        tool = self._tools.get(name)
        if not tool:
            available = ', '.join(t.name for t in self._tools.list_tools())
            return ("missing", f"错误：未知工具「{name}」，可用：{available}", [])
        allowed, exec_message = await execute_tool_with_safety(
            tool, inp, adjudicator_check_fn,
        )
        # 部分工具（如 run_code）执行后会把产物（图片）存到实例属性，随事件回传前端
        artifacts = list(getattr(tool, "_last_artifacts", []) or [])
        # 防重复循环
        if self._is_repeat_call(name, inp, tool_call_history):
            write_result = await self._auto_save_repeat(exec_message, adjudicator_check_fn)
            return ("dedup", write_result, [])
        if not allowed:
            return ("blocked", exec_message, [])
        # 成功路径：在 observation 里告知模型已生成产物，避免它因「看不到结果」反复重试
        artifact_note = ""
        if artifacts:
            internal = [a for a in artifacts if a.get("internal")]
            external = [a for a in artifacts if not a.get("internal")]
            if external:
                names = "、".join(a.get("name", "?") for a in external)
                artifact_note = (
                    f"\n\n（本次执行已生成 {len(external)} 个文件产物：{names}，"
                    f"系统已回传并展示给用户）"
                )
            if internal:
                artifact_note += (
                    "\n\n（截图内容已转为模型可读格式回传，请在下方上下文中查看）"
                )
        return (None, exec_message + artifact_note, artifacts)

    async def _auto_save_repeat(self, content: str, adjudicator_check_fn: callable | None) -> str:
        """重复调用时自动将上次结果写入文件并返回提示。"""
        allowed = getattr(self, "_allowed_tool_names", None)
        if allowed is not None and "write_file" not in allowed:
            return "[系统] 检测到重复调用，已拦截重复动作"
        write_tool = self._tools.get("write_file")
        if not write_tool:
            return "[系统] 检测到重复调用，已拦截"
        # 落盘到存储池目录，避免硬编码绝对路径导致换机/换用户失效
        save_path = os.path.join(settings.STORAGE_POOL_DIR, "agent_search_result.txt")
        allowed, _ = await execute_tool_with_safety(
            write_tool, {"path": save_path, "content": content},
            adjudicator_check_fn,
        )
        return f"✓ 搜索结果已自动保存到 {save_path}（{len(content)} 字符）"

    @staticmethod
    def _format_answer(inp: dict, answer: dict) -> str:
        """把用户提交的答案载荷格式化为可读文本，作为 observation 回灌 LLM。"""
        if not isinstance(answer, dict):
            return "用户提交了回答。"
        if answer.get("error"):
            return f"（用户未回答：{answer['error']}）"
        qtype = inp.get("question_type") or answer.get("qtype") or "text"
        if qtype == "single":
            selected = answer.get("selected") or "（未选）"
            other = answer.get("other_text")
            text = f"用户选择（单选）：{selected}"
            if other:
                text += f"（补充说明：{other}）"
            return text
        if qtype == "multiple":
            selected = answer.get("selected") or []
            if isinstance(selected, str):
                selected = [selected]
            other = answer.get("other_text")
            text = f"用户选择（多选）：{', '.join(selected) if selected else '（未选）'}"
            if other:
                text += f"（补充说明：{other}）"
            return text
        return f"用户填写：{answer.get('text', '')}"

    async def _handle_tool_events(
        self, parsed: dict,
        tool_call_history: list[tuple[str, str]],
        adjudicator_check_fn: callable | None,
        step_state: dict | None = None,
        result_state: dict | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """执行工具并产出 SSE 事件（tool_call + tool_result）。

        step_state 为规划子步的可观测状态（由 run_react 传入），用于识别「假成功」：
        blocked/missing 置 last_action_failed=True，正常或去重成功则复位。
        """
        name, inp = parsed["name"], parsed["input"]
        # 人机交互：ask_user 先登记问题发卡片，再 await 用户回答后回灌记忆
        if name == "ask_user":
            async for event in self._handle_ask_user(parsed, result_state):
                yield event
            return
        yield AgentEvent(type="tool_call", tool_name=name, tool_input=inp)
        action, exec_message, artifacts = await self._handle_tool_call(
            name, inp, tool_call_history, adjudicator_check_fn,
        )
        # blocked/missing 标记失败；dedup/成功复位（供规划引擎判定子步真伪）
        if step_state is not None:
            step_state["last_action_failed"] = action in ("missing", "blocked")
        if result_state is not None:
            result_state.update(action=action, output=exec_message)
        if action == "missing":
            yield AgentEvent(type="tool_result", tool_name=name, tool_output=exec_message)
            self._memory.add("assistant", f"Action {name} failed: {exec_message}")
            return
        if action == "dedup":
            yield AgentEvent(type="tool_result", tool_name=name, tool_output=exec_message)
            return
        if action == "blocked":
            yield AgentEvent(type="tool_result", tool_name=name, tool_output=exec_message,
                             adjudicated=True, adjudicated_reason=exec_message)
            self._memory.add("assistant", f"Action {name} blocked: {exec_message}")
            return
        # UI 卡片预览截断到 3000，AI 记忆里的 observation 透传完整结果（仅超长时截断并标注原长）
        # 内部产物（截图 ASCII/原图）不发给前端，仅注入模型上下文
        user_artifacts = [a for a in artifacts if not a.get("internal")]
        yield AgentEvent(type="tool_result", tool_name=name, tool_output=exec_message[:3000],
                         artifacts=user_artifacts)
        obs = exec_message
        # 截图产物注入模型上下文
        images_to_inject = []
        for a in artifacts:
            if not a.get("internal"):
                continue
            if a.get("type") == "text":
                obs += f"\n\n[屏幕内容 ASCII 转义]\n{a['data']}\n[/屏幕内容 ASCII 转义]"
            elif a.get("type") == "image":
                images_to_inject.append({"data": a["data"], "mime": a.get("mime", "image/png")})
        if len(obs) > 8000:
            obs = obs[:8000] + f"\n…（工具输出过长已截断，原始共 {len(exec_message)} 字符）"
        self._memory.add("assistant", f"工具[{name}] 结果: {obs}")
        # 原图模式：追加 user 消息携带图像
        if images_to_inject:
            self._memory.add(
                "user",
                "[系统注入：截图原图回传] 以下是刚才截取的屏幕内容，请据此分析屏幕布局和内容：",
                images=images_to_inject,
            )

    async def _handle_ask_user(self, parsed: dict, result_state: dict | None) -> AsyncIterator[AgentEvent]:
        """处理 ask_user：登记问题→发卡片事件→阻塞等回答→回灌记忆。"""
        if result_state is not None:
            result_state.update(action="ask_user", output="")
        inp = parsed["input"]
        spec = {
            "title": inp.get("title", "请回答以下问题"),
            "content": inp.get("content", "") or "",
            "qtype": inp.get("question_type", "text"),
            "options": inp.get("options") or [],
        }
        qid, spec = get_question_hub().create(self._conversation_id, spec)
        yield AgentEvent(type="ask_user", question=spec)
        answer = await get_question_hub().wait(qid)
        answer_text = self._format_answer(inp, answer)
        self._memory.add("assistant", f"工具[ask_user] 用户回答: {answer_text[:500]}")
"""Agent 的 ReAct 文本式循环（Mixin，由 Agent 继承）。

承载原生 function calling 之外的文本式 ReAct 兜底循环及其子步判定逻辑。
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator

from .schemas import AgentEvent
from .react_parser import parse_react_output
from .code_guard import _run_code_guard

_LOGGER = logging.getLogger(__name__)

# 连续同工具上限：有进展放宽，无进展（失败/输出相同/为空）收紧
_CONSEC_LIMIT_PROGRESS = 5
_CONSEC_LIMIT_STUCK = 3


class ReactMixin:
    """ReAct 文本式推理循环。"""

    async def run_react(
        self, message: str, llm_stream_fn: callable,
        adjudicator_check_fn: callable | None,
        tool_call_history: list[tuple[str, str]],
        outcome: dict,
        emit_delta: bool = True, emit_done: bool = True, emit_error: bool = True,
    ) -> AsyncIterator[AgentEvent]:
        """执行一轮 ReAct 循环（含制定计划后的单步执行）。

        设置 outcome["text"]（最终回答）与 outcome["error"]（是否异常），
        供规划引擎判断单步成败并决定重规划。
        emit_* 为 False 时（作为计划子步运行）只透出 thought/tool 类事件，
        不发出 delta/done/error，避免前端把这些「子步终态」误判为整次结束/失败。
        """
        self._user_message = message  # 工具语义匹配以当前子目标为准
        outcome["text"] = None
        outcome["error"] = False
        # 子步执行状态：用于识别「假成功」——被拦截或无任何工具动作的空步不应标记完成
        step_state = {"tool_called": False, "last_action_failed": False}
        is_sub_step = emit_done is False
        # 连续同工具调用计数：同一工具连续调用过多则强制收尾，避免无限重试。
        # 有进展（输出变化）时放宽到 5 次；无进展（输出相同/失败/为空）时 3 次即限制。
        consec = self._new_consec_state()
        # 强制收尾指令只作用于本次循环，绝不能写进持久记忆（否则会污染后续新提问）
        self._force_text_hint = None
        for _step in range(1, self._max_iterations + 1):
            messages = self._build_prompt(force_text_hint=self._force_text_hint)
            # 流式调用 LLM（边收边发射 thought 事件，让前端实时显示推理过程）
            self._last_full_output = None
            async for event in self._invoke_llm_stream(messages, llm_stream_fn):
                yield event
            full_output = self._last_full_output
            if full_output is None:
                async for event in self._emit_react_failure(outcome, emit_error, emit_done):
                    yield event
                return
            # 解析并处理输出（thought 已在流式调用中发射）
            parsed = parse_react_output(full_output)
            # 无角色扮演时清洗最终回复文本，阻断角色语气落盘/下发
            if not self._persona_text:
                parsed["content"] = self._strip_roleplay_tone(parsed.get("content", "") or "")
            _LOGGER.info("Agent step %d: type=%s", _step, parsed["type"])
            # 已触发强制收尾却仍要调工具 → 直接以兜底文本收尾，不再执行
            if consec["force_text"] and parsed["type"] == "tool":
                outcome["text"] = "已完成相关工具调用，结果见上方工具记录。"
                if emit_done:
                    yield AgentEvent(type="done")
                return
            if parsed["type"] == "tool":
                async for event in self._dispatch_react_tool(
                    parsed, tool_call_history, adjudicator_check_fn, step_state, consec,
                ):
                    yield event
                continue
            if parsed["type"] == "response":
                async for event in self._finalize_react_response(
                    parsed["content"], outcome, step_state, is_sub_step,
                    emit_delta, emit_error, emit_done,
                ):
                    yield event
                return
            is_final, events = self._collect_react_unknown(
                parsed, outcome, step_state, is_sub_step,
                emit_delta, emit_error, emit_done,
            )
            for event in events:
                yield event
            if is_final:
                return
        # 超迭代上限
        outcome["error"] = True
        if emit_error:
            yield AgentEvent(type="error", content="Agent 已达到最大迭代次数，请简化指令")
        if emit_done:
            yield AgentEvent(type="done")

    def _new_consec_state(self) -> dict:
        """初始化连续同工具调用计数状态（含进展/卡死两套上限）。"""
        return {
            "tool": "", "count": 0, "last_output": "", "force_text": False,
            "limit_progress": _CONSEC_LIMIT_PROGRESS, "limit_stuck": _CONSEC_LIMIT_STUCK,
        }

    async def _emit_react_failure(self, outcome: dict, emit_error: bool, emit_done: bool) -> AsyncIterator[AgentEvent]:
        """LLM 无输出时统一产出 error + done 收尾。"""
        outcome["error"] = True
        if emit_error:
            yield AgentEvent(type="error", content="LLM 调用失败")
        if emit_done:
            yield AgentEvent(type="done")

    async def _finalize_react_response(
        self, content: str, outcome: dict, step_state: dict,
        is_sub_step: bool, emit_delta: bool, emit_error: bool, emit_done: bool,
    ) -> AsyncIterator[AgentEvent]:
        """response 分支收尾：判定子步假成功后发射 delta + done。"""
        fail_reason = self._sub_step_failure(step_state, is_sub_step, content)
        if fail_reason:
            outcome["error"] = fail_reason
            outcome["text"] = fail_reason
            if emit_error:
                yield AgentEvent(type="error", content=fail_reason)
            if emit_done:
                yield AgentEvent(type="done")
            return
        outcome["text"] = content
        if emit_delta:
            for chunk in self._split_delta(content):
                yield AgentEvent(type="delta", content=chunk)
                await asyncio.sleep(0.008)
        self._memory.add("assistant", content)
        if emit_done:
            yield AgentEvent(type="done")

    def _collect_react_unknown(
        self, parsed: dict, outcome: dict, step_state: dict,
        is_sub_step: bool, emit_delta: bool, emit_error: bool, emit_done: bool,
    ) -> tuple[bool, list]:
        """unknown 分支收尾：返回 (是否收尾, 事件列表)。

        空内容时不收尾（返回 False），交由主循环继续，避免对垃圾输出误判为完成。
        注：与 response 分支不同，此处省略 delta 的 8ms 打字间隔（未知格式无需逐字效果）。
        """
        events: list = []
        content = self._clean_assistant_text(parsed.get("content", self._last_full_output))
        fail_reason = self._sub_step_failure(step_state, is_sub_step, content)
        if fail_reason:
            outcome["error"] = fail_reason
            outcome["text"] = fail_reason
            if emit_error:
                events.append(AgentEvent(type="error", content=fail_reason))
            if emit_done:
                events.append(AgentEvent(type="done"))
            return True, events
        if content.strip():
            outcome["text"] = content
            if emit_delta:
                for chunk in self._split_delta(content):
                    events.append(AgentEvent(type="delta", content=chunk))
            self._memory.add("assistant", content)
            if emit_done:
                events.append(AgentEvent(type="done"))
            return True, events
        return False, events

    async def _dispatch_react_tool(
        self, parsed: dict, tool_call_history: list[tuple[str, str]],
        adjudicator_check_fn: callable | None, step_state: dict, consec: dict,
    ) -> AsyncIterator[AgentEvent]:
        """工具分支：记录 Action、连续计数、run_code 安全网、执行并续接连续上限判定。"""
        self._memory.add("assistant", self._clean_assistant_text(self._last_full_output[:800]))
        step_state["tool_called"] = True
        # 连续同工具计数（按上一轮状态累计）
        if parsed["name"] == consec["tool"]:
            consec["count"] += 1
        else:
            consec["tool"] = parsed["name"]
            consec["count"] = 1
        # run_code 前置安全网（react 兜底路径）：还原点 + 静态扫描 + 弹窗
        if parsed["name"] == "run_code":
            is_blocked, guard_events = await self._guard_react_run_code(parsed)
            for event in guard_events:
                yield event
            if is_blocked:
                return
        tool_result_state = {"action": None, "output": ""}
        async for event in self._handle_tool_events(
            parsed, tool_call_history, adjudicator_check_fn, step_state, tool_result_state,
        ):
            yield event
        self._update_consec_after_tool(consec, tool_result_state["action"], tool_result_state["output"])

    async def _guard_react_run_code(self, parsed: dict) -> tuple[bool, list]:
        """run_code 前置安全网：解析入参→建还原点+静态扫描+弹窗，返回 (是否拦截, 事件列表)。"""
        raw = parsed.get("args") or parsed.get("action_input") or {}
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                raw = {}
        if not isinstance(raw, dict):
            raw = {}
        guard_events: list = []
        decision = await _run_code_guard(self, raw, guard_events)
        if decision == "blocked":
            guard_events.append(AgentEvent(
                type="tool_result", tool_name="run_code",
                tool_output="[已取消] 用户拒绝在还原点缺失或代码风险下执行",
                adjudicated=True, adjudicated_reason="用户拒绝"))
            self._memory.add("assistant", "用户拒绝执行 run_code")
            return True, guard_events
        return False, guard_events

    def _update_consec_after_tool(self, consec: dict, action: str | None, output: str) -> None:
        """工具执行后更新连续同工具状态：判定是否触发强制收尾（不写持久记忆）。"""
        is_stuck = (
            action in ("blocked", "missing", "dedup")
            or (output.strip() and output.strip() == consec["last_output"].strip())
        )
        limit = consec["limit_stuck"] if is_stuck else consec["limit_progress"]
        if consec["count"] >= limit:
            consec["force_text"] = True
            # 该指令只注入到本次循环的 system prompt（不落盘），避免污染后续新提问
            self._force_text_hint = (
                f"（系统）检测到你已连续 {consec['count']} 次调用同一工具"
                f"{'且未推进任务' if is_stuck else ''}，"
                "请立即停止调用工具，直接把已有的工具结果用自然语言总结并回复用户。"
            )
        consec["last_output"] = output

    def _sub_step_failure(self, step_state: dict, is_sub_step: bool, content: str) -> str | None:
        """判定规划子步是否「假成功」，返回失败原因；非子步或确已成功则返回 None。

        仅对规划子步生效：普通对话（非子步）即使未调用工具也应正常以文本收尾。
        - 曾被安全拦截/工具缺失且最终仅以文本收尾（未取得目标动作）→ 失败
        - 全程未调用任何工具（空步骤）→ 失败
        若拦截后改用其它工具成功执行，则 last_action_failed 已被重置，不算失败。
        """
        if not is_sub_step:
            return None
        if step_state["tool_called"] and step_state["last_action_failed"]:
            return "步骤因安全拦截/工具缺失而未能完成目标动作"
        if not step_state["tool_called"]:
            return "步骤未执行任何工具调用（空步骤），未达成目标"
        return None

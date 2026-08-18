"""原生结构化工具调用运行器（function calling）。

与文本式 ``run_react`` 并列，作为默认工具调用架构。通过模型原生 ``tool_calls``
决策工具调用，工具结果以 ``role=tool`` 消息回灌，跨轮用 ``tool_call_id`` 配对，
从根上消除「把系统指令/工具结果混进对话文本」导致的指令泄漏与角色语气污染。

工具执行编排（单工具分发/结果写记忆/后台任务守卫/提示注入剥离）已下沉到
``_native_execution.py``，本文件只负责提示构建、流式分发与主循环薄转发。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re

from ..schemas import AgentEvent
from .._native_execution import _execute_tool_round, _parse_tool_arguments
from ..model_router import select_model

_LOGGER = logging.getLogger(__name__)

# 旧版代码（修复前）给工具结果包了一层"✅ 工具【name】执行成功…"装饰壳，
# 这些历史文本被持久化进了 agent_memory / vector_memory。新会话读取时会原样回灌，
# 模型照着复述。这里在拼 prompt 前统一剥离，确保毒数据不会重新进入模型上下文。
_TOOL_WRAPPER_RE = re.compile(
    r"✅\s*工具【[^】]*】执行成功。\s*"
    r"以下是该工具的输出，\*\*直接当作回答用户的依据，不要再调用工具或追问\*\*：\s*"
)
_STATUS_LINE_RE = re.compile(r"^[✅❌⚠️]\s*状态:\s*.+$", re.MULTILINE)
_ISOLATION_RE = re.compile(r"^\s*隔离等级:\s*.+$", re.MULTILINE)
_GUI_HINT_RE = re.compile(r"^\s*输出:\s*\(空\)\s*[—-]\s*GUI 类命令.*$", re.MULTILINE)
_RESULT_LABEL_RE = re.compile(r"工具\[[^\]]*]\s*结果:\s*")


def _sanitize_tool_text(text: str) -> str:
    """剥离旧版工具结果装饰壳（emoji/状态行/隔离等级/GUI 提示/工具结果标签），只留原始输出。"""
    if not text:
        return text
    text = _TOOL_WRAPPER_RE.sub("", text)
    text = _STATUS_LINE_RE.sub("", text)
    text = _ISOLATION_RE.sub("", text)
    text = _GUI_HINT_RE.sub("", text)
    text = _RESULT_LABEL_RE.sub("", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()

# native 模式系统提示：不含 {history}（历史走结构化消息），且用原生工具说明替代
# 文本式 Action/Response 格式指令。
NATIVE_SYSTEM_PROMPT_TPL = """你是一个**有完整行动能力的 Agent**，不是普通对话 AI——要**真正动手帮用户操作电脑**。

# 🛠️ 工具
你可以使用模型内置的工具（function calling）来完成任务，不要以纯文本格式输出工具调用指令。
**文件/代码**: `read_file` / `write_file` / `run_code`(Python/Node/Bash/PowerShell/cmd)
**网络**: `web_search` / `web_fetch`（受离线管控）
**桌面自动化**: `take_screenshot` / `click_mouse` / `type_text` / `hotkey` / `clipboard_*`
**数据/知识**: `chengyu` / `festival` / `chinese_dict` / `generate_qrcode`
**文本/计算/单位换算/随机/格式转换等** → 用 `run_code` 在沙箱写代码完成
**不确定用什么** → `search_tools("关键词")` 列出相关工具及描述

**关键原则**：成功执行工具后立即下一步，不要重复相同调用。GUI命令(stdout空+退出码0)=成功。{deep_think_instruction}

# 📋 执行准则
1. **独立对待每条消息**——短词("测试"/"好的"/"嗯")按字面回应，不从历史推断意图。
2. **工具优先**——涉及操作电脑的任务必须调工具完成，不说"做不到"。
3. **试错到底**——首次失败至少换2种方法再试，穷尽前不放弃。
4. **限时思考**——识别需求后最多想2句就调用工具或回复。
5. **输出完整性**：用户要"全部"时完整展示。≤50项全出，≤500项分批出，>500项存文件。**禁止只给"前N个"交差**。
6. **角色设定只影响说话方式**——任务优先→工具执行→角色回应。不能因角色设定跳过工具。
7. **无角色设定时必须用标准助手语气**——绝对禁止模仿历史对话中的角色风格（包括但不限于"喵"、"主人"、"人家"、动作描写如"（猫耳抖了抖）"、emoji 等），也不得使用第一人称自称。用简洁、专业、中性的第三方助手语气回答。
8. **后台任务必须闭环**——可以启动耗时较长的子进程，但**严禁**以"已在后台运行""你先忙、好了通知你"之类一句话结束对话或搪塞。处理方式二选一：① 优先同步等待结果后回复（run_code 本就阻塞，长任务请调大 timeout 并等待，不要 `subprocess.Popen` 后不等待就返回）；② 若确需异步，必须持续跟进直到拿到结果并回复/总结，绝不让任务"开了就消失"。后台任务未完成前，不得向用户声称任务已结束。

# 🎭 角色设定
{roleplay_context}

# 🧠 记忆
{memory_context}

## 🔄 话题感知
用户**最新一条消息**是当前任务。新旧话题不相关时忽略旧历史，专注回答最新问题。
"""

_DEEP_THINK_TEXT = (
    "6. 推理要快：简单问题直接行动，复杂问题想清关键步骤就立刻动手。不要反复自我辩论。"
)

_STALL_TIMEOUT = 60.0
_MAX_TOTAL = 300.0
_CONSEC_LIMIT_PROGRESS = 5
_CONSEC_LIMIT_STUCK = 3


def _build_prompt_native(agent) -> list[dict]:
    """组装 native 模式消息：system（核心记忆+归档，不含短期对话，避免与 raw history 重复）+ 原始历史。

    Worker 模式：跳过角色扮演清洗（buffer memory 无角色污染，清洗反误伤任务文本）。
    """
    is_worker = getattr(agent, "_agent_role", None) == "worker"
    memory_context = agent._memory.inject_system_context(include_short_term=False)
    professional_memory_context = getattr(agent, "_professional_memory_context", "") if is_worker else ""
    if professional_memory_context:
        memory_context = (
            memory_context + "\n\n" + professional_memory_context
            if memory_context else professional_memory_context
        )
    # 持久化记忆（归档/向量）可能含旧版装饰壳毒数据，拼入前剥离，避免模型复述
    memory_context = _sanitize_tool_text(memory_context)
    # 与 React 模式对齐：无角色时同步剥离记忆中的角色语气残留，避免旧角色对话污染新会话
    # Worker 模式跳过：buffer memory 无角色污染
    if not agent._persona_text and not is_worker:
        memory_context = agent._strip_roleplay_tone(memory_context)
    sys_prompt = NATIVE_SYSTEM_PROMPT_TPL.format(
        roleplay_context=agent._persona_text or "",
        memory_context=memory_context,
        deep_think_instruction=_DEEP_THINK_TEXT if agent._deep_think else "",
    )
    # 无角色设定时追加强约束（recency bias 抑制旧语气），与 react 一致
    # Worker 模式跳过：Worker 不做角色扮演，不需要此约束
    if not agent._persona_text and not is_worker:
        sys_prompt += (
            "\n\n【最终约束】当前未启用角色扮演。你的回复必须是标准助手语气："
            "禁止使用\"喵\"、动作描写、角色自称、\"主人\"等角色化表达，"
            "也不得模仿历史对话中的旧语气。用简洁、专业、中性的第三方助手语气回答。"
            "回复中绝对不要出现\"【工具名】执行成功\"之类的系统包装文字，"
            "也不要把原始工具输出（stderr/stdout）原样粘贴进回复，只提炼关键信息自然表述。"
        )
    if agent._force_text_hint:
        sys_prompt += "\n\n" + agent._force_text_hint
    # P5 结构化输出：要求模型以单个 json 代码块输出，严格符合给定 schema
    schema = getattr(agent, "_structured_schema", None)
    if schema:
        sys_prompt += (
            "\n\n# 📦 结构化输出要求\n你必须且只能以**单个** ```json 代码块输出最终结果，"
            "严格符合以下 JSON Schema，不要任何额外解释文字：\n```json\n"
            + json.dumps(schema, ensure_ascii=False) + "\n```"
        )
    # 用户情绪感知提示（平静时为空串，自动跳过，避免噪声）
    emotion_hint = getattr(agent, "_emotion_hint", "") or ""
    if emotion_hint:
        sys_prompt += emotion_hint
    msgs = [{"role": "system", "content": sys_prompt}]
    # 历史原文回灌：无角色设定时剥离其中的角色化残留与旧版工具装饰壳，
    # 避免模型模仿旧语气或复述装饰文字（治本：移除模型会模仿的样例）。
    # Worker 模式跳过：buffer memory 无角色污染
    raw = agent._memory.get_raw_history()
    if not agent._persona_text and not is_worker:
        for m in raw:
            if m.get("role") == "assistant" and m.get("content"):
                # 先剥离装饰壳（依赖换行锚定的状态行/隔离等级），再做角色语气清洗
                # （_strip_roleplay_tone 会把换行压成空格，须在其之前执行）
                m["content"] = agent._strip_roleplay_tone(_sanitize_tool_text(m["content"]))
    msgs += raw
    return msgs


_NATIVE_BOUNDARY_RE = re.compile(
    r"\*{0,2}(?:Action|Response|Answer|Thought|Observation|Final\s*Answer"
    r"|行动|动作|操作|步骤|思考|回复|回答|最终回答|执行)"
    r"\*?\*?\s*[:：]?")
_NATIVE_EMIT_INTERVAL = 50


def _normalize_native_chunk(chunk) -> tuple[str, str, object]:
    """把 native 流式 chunk 统一为 (正文, 推理链, 原始 tool_calls)。"""
    if isinstance(chunk, dict):
        return (chunk.get("content") or "", chunk.get("reasoning") or "", chunk.get("tool_calls"))
    if isinstance(chunk, str):
        return chunk, "", None
    return (
        getattr(chunk, "content", None) or getattr(chunk, "delta", "") or "",
        getattr(chunk, "reasoning", None) or "",
        getattr(chunk, "tool_calls", None),
    )


def _is_native_stream_timed_out(now: float, start_ts: float, last_activity_ts: float) -> bool:
    """停滞超时或总超时任一触发即中止（双阈值避免误杀长推理）。"""
    return now - last_activity_ts > _STALL_TIMEOUT or now - start_ts > _MAX_TOTAL


def _emit_native_thought(agent, text: str) -> AgentEvent | None:
    """源头清洗 thought：思考过程是模型内部推理展示，无论角色是否启用都不应带角色语气。

    角色扮演开启时仅保留最终回复（delta）按角色发声；thought 一律标准助手语气。
    """
    if not text:
        return None
    text = agent._strip_roleplay_tone(text)
    return AgentEvent(type="thought", content=text[:2000])


async def _yield_thought(agent, text: str):
    """过滤空文本：_emit_native_thought 对空片段返回 None，流式模型可能产出空 reasoning，直接透传会让
    消费方（如 plan_engine 的 item[1].type）撞 NoneType，故统一在此跳过。"""
    evt = _emit_native_thought(agent, text)
    if evt is not None:
        yield evt


async def _invoke_native_stream(agent, messages, llm_stream_fn, tools, result: dict):
    """流式调用 LLM（native 模式）：实时 yield thought 事件，累积 content/tool_calls 到 result。"""
    collected = ""
    reasoning_collected = ""
    loop = asyncio.get_running_loop()
    start_ts = loop.time()
    last_activity_ts = start_ts
    thought_buffer = ""
    crossed_boundary = False
    in_tool_phase = False
    try:
        async for chunk in llm_stream_fn(messages, agent._model, tools=tools):
            content, reasoning, raw_tc = _normalize_native_chunk(chunk)
            if not content and not reasoning and not raw_tc:
                continue
            now = loop.time()
            last_activity_ts = now
            # 推理链实时下发（去重前缀，避免多轮重复）
            if reasoning:
                reasoning_collected += reasoning
                new_reasoning = agent._deduplicate_reasoning_prefix(reasoning)
                if new_reasoning:
                    async for _ev in _yield_thought(agent, new_reasoning):
                        yield _ev
            # 工具调用阶段：把叙述性文本作为 thought 展示一次
            if raw_tc:
                result["tool_calls"] = raw_tc  # brick 已累积完整列表
                if not in_tool_phase and collected.strip():
                    async for _ev in _yield_thought(agent, collected.strip()):
                        yield _ev
                    in_tool_phase = True
            if content:
                collected += content
                if in_tool_phase:
                    async for _ev in _yield_thought(agent, content):
                        yield _ev
                else:
                    thought_buffer += content
                    if not crossed_boundary and _NATIVE_BOUNDARY_RE.search(thought_buffer):
                        crossed_boundary = True
                        async for _ev in _yield_thought(agent, thought_buffer.strip()):
                            yield _ev
                        thought_buffer = ""
                    elif len(thought_buffer) >= _NATIVE_EMIT_INTERVAL:
                        async for _ev in _yield_thought(agent, thought_buffer.strip()):
                            yield _ev
                        thought_buffer = ""
            if _is_native_stream_timed_out(now, start_ts, last_activity_ts):
                _LOGGER.info("native LLM 超时（停滞 %.0fs/总 %.0fs）", now - last_activity_ts, now - start_ts)
                break
        async for _ev in _yield_thought(agent, thought_buffer.strip()):
            yield _ev
    except Exception as exc:
        _LOGGER.error("native LLM 流式异常: %s", exc)
        raise
    result["collected"] = collected
    result["reasoning"] = reasoning_collected


# ── 反思自检（P3：回答成立性闸门） ───────────────────────────
# 仅在「本轮用过工具」时多调一次轻量 LLM 判定回答是否成立，避免给纯闲聊白烧一次调用。
# 判定 revise 则把修正指令注入记忆并重跑一轮（不向用户展示草稿）；ok 才下发答案。
# 最多 1 次重跑（agent._reflected_once 守卫），杜绝死循环；解析失败/异常一律降级为 ok（不自残）。

_REFLECT_PROMPT = """你是一个严苛的回答自我审查员。请判断「本次回答」是否真正、完整地满足了「用户请求」。

用户请求：
{request}

本次回答：
{draft}
{failure_note}

仅输出一个 JSON 对象，不要任何额外文字：
{{"verdict": "ok" 或 "revise", "issue": "若存在问题，用一句话说明", "instruction": "若需修正，给自己的具体修正指令（中文）"}}

判定要点：
- 回答明显未回应请求、遗漏用户明确要求的重点、或声称完成但仍有未解决的工具失败，则 verdict="revise"。
- 回答已合理满足请求则为 "ok"。
"""


def _parse_reflect_json(text: str) -> dict:
    """从模型输出中稳健提取首个 JSON 对象（容忍 ```json 包裹/前后噪声）。"""
    text = (text or "").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return {}
    try:
        return json.loads(text[start:end + 1])
    except Exception:  # noqa: BLE001
        return {}


async def _call_llm_text(agent, llm_stream_fn, messages: list[dict]) -> str:
    """无工具地调用 LLM 取纯文本（供自检等内部判断），累积流式输出。

    自审属杂活，改走 flash_model 压低成本（未配置 flash 档位则回退主力模型）。
    """
    collected = ""
    try:
        async for chunk in llm_stream_fn(messages, select_model("trivial", agent._model)):
            content, _, _ = _normalize_native_chunk(chunk)
            if content:
                collected += content
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("自检 LLM 调用异常（降级放行）: %s", exc)
    return collected


def _should_reflect(agent, state: dict) -> bool:
    """仅在「反思开关开启且本轮用过工具」时自检（纯闲聊不浪费 LLM 调用）。

    开关通过 agent._enable_reflection 控制（缺省视为开启）。
    """
    if state.get("skip_reflect"):
        return False
    if not getattr(agent, "_enable_reflection", True):
        return False
    return bool(state.get("used_tools"))


async def _reflect(agent, llm_stream_fn, request: str, draft: str,
                   had_failure: bool) -> tuple[str, str]:
    """自检：判断回答是否成立，返回 (verdict, instruction)。

    verdict="revise" 时附带修正指令；解析失败或异常一律降级为 "ok"（不自残）。
    """
    failure_note = ""
    if had_failure:
        failure_note = (
            "\n注意：本次有工具执行失败或被拦截，但回答可能未提及，"
            "请核实是否应向用户如实说明。\n"
        )
    prompt = _REFLECT_PROMPT.format(
        request=request, draft=draft, failure_note=failure_note)
    messages = [
        {"role": "system", "content": "你是回答质量审查员，只输出 JSON。"},
        {"role": "user", "content": prompt},
    ]
    raw = await _call_llm_text(agent, llm_stream_fn, messages)
    data = _parse_reflect_json(raw)
    if (data.get("verdict") or "").lower() == "revise":
        instruction = (data.get("instruction") or data.get("issue")
                       or "请检查并补全回答").strip()
        return "revise", instruction
    return "ok", ""


def _extract_structured(text: str, schema: dict) -> dict | None:
    """从模型最终答案中抽取并校验 JSON 对象（匹配结构化输出 schema）。

    优先取 ```json 围栏块；否则取首个 { 到末个 } 的子串。校验 schema.required 必填键齐全。
    任何异常（解析失败/缺键）返回 None（不阻断主流程，降级为普通文本）。
    """
    if not text or not isinstance(schema, dict):
        return None
    candidate = ""
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        candidate = fence.group(1)
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            candidate = text[start:end + 1]
    if not candidate:
        return None
    try:
        data = json.loads(candidate)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(data, dict):
        return None
    required = schema.get("required", []) or []
    if all(k in data for k in required):
        return data
    return None


async def _run_native_step(agent, llm_stream_fn, tool_schemas, adjudicator_check_fn,
                           tool_call_history, state, outcome, emit_done, control: dict):
    """执行一轮 native 迭代：流式、执行工具或回复。置 control["stop"] 终止外层循环。"""
    messages = _build_prompt_native(agent)
    result: dict = {}
    async for evt in _invoke_native_stream(agent, messages, llm_stream_fn, tool_schemas, result):
        yield evt
    collected = result.get("collected", "")
    # 无角色扮演时清洗最终文本，阻断角色语气落盘/下发/回灌（一处见效，覆盖下方存储与 delta）
    if not agent._persona_text:
        collected = agent._strip_roleplay_tone(collected)
    tool_calls_acc = result.get("tool_calls", [])
    reasoning = result.get("reasoning", "")

    if not collected and not tool_calls_acc:
        outcome["error"] = True
        if emit_done:
            yield AgentEvent(type="error", content="模型未返回有效内容")
            yield AgentEvent(type="done")
        control["stop"] = True
        return

    if tool_calls_acc:
        async for ev in _dispatch_tool_calls(
            agent, collected, tool_calls_acc, adjudicator_check_fn, tool_call_history, state, emit_done, reasoning):
            yield ev
        completion_answer = state.pop("completion_answer", "")
        if completion_answer:
            state["skip_reflect"] = True
            async for ev in _emit_text_reply(
                agent, completion_answer, llm_stream_fn, state, outcome, emit_done, control):
                yield ev
        return

    async for ev in _emit_text_reply(
        agent, collected, llm_stream_fn, state, outcome, emit_done, control):
        yield ev


async def _dispatch_tool_calls(agent, collected, tool_calls_acc, adjudicator_check_fn,
                               tool_call_history, state, emit_done, reasoning: str = "") -> None:
    """工具调用分支：记 assistant 消息（含 tool_calls）→ 即时下发 tool_call 事件 → 执行工具轮。"""
    # assistant 消息（含 tool_calls + 伴随文本）写入记忆，供下一轮续调用
    agent._memory.add("assistant", collected, tool_calls=tool_calls_acc, reasoning=reasoning)
    # 在工具执行前立即下发 tool_call：前端可马上显示「调用中」+ 输入参数 + 计时，
    # 不必等耗时工具（如 run_code 扫盘）跑完才看到调用标志。
    for tc in tool_calls_acc:
        fn = tc.get("function") or {}
        name = fn.get("name", "")
        args = _parse_tool_arguments(fn)
        yield AgentEvent(type="tool_call", tool_name=name, tool_input=args)
    progress = await _execute_tool_round(
        agent, tool_calls_acc, adjudicator_check_fn, tool_call_history, state)
    for ev in progress["events"]:
        yield ev
    # 继续外层循环（不 emit done）


async def _emit_text_reply(agent, collected, llm_stream_fn, state, outcome, emit_done, control) -> None:
    """纯文本回复分支：反思自检 → 流式发射 + 入记忆。"""
    outcome["text"] = collected
    # P5 结构化输出：从最终答案抽取并校验 JSON（仅当请求带 schema）
    schema = getattr(agent, "_structured_schema", None)
    if schema:
        extracted = _extract_structured(collected, schema)
        if extracted is not None:
            outcome["structured_output"] = extracted
    # P3 反思闸门：本轮用过工具才自检；revise 则注入修正指令重跑一轮（不展示草稿）
    if _should_reflect(agent, state) and not getattr(agent, "_reflected_once", False):
        verdict, instruction = await _reflect(
            agent, llm_stream_fn,
            getattr(agent, "_current_request", ""), collected,
            bool(state.get("last_failed")),
        )
        if verdict == "revise":
            agent._reflected_once = True
            agent._memory.add("assistant", collected)
            agent._memory.add(
                "user", f"[自检反馈，请据此修正回答] {instruction}")
            yield AgentEvent(type="thought", content="（自检发现回答需补充，正在修正…）")
            control["stop"] = False
            return
    agent._memory.add("assistant", collected)
    for piece in agent._split_delta(collected):
        yield AgentEvent(type="delta", content=piece)
        await asyncio.sleep(0.008)
    if emit_done:
        yield AgentEvent(type="done", structured_output=outcome.get("structured_output") or {})
    control["stop"] = True


async def run_native(agent, message, llm_stream_fn, adjudicator_check_fn,
                    outcome, emit_done: bool = True):
    """原生结构化工具调用主循环。

    Worker 模式增强：
    - 每步执行前检查干预队列（cancel/pause/redirect）
    - 所有事件同步记录到 trace_store（思维链/工具调用/输出/错误）
    """
    outcome["text"] = None
    outcome["error"] = False
    agent._force_text_hint = None
    # 反思自检状态：每轮 run 重置（规划模式按步调用，各自独立一次重跑机会）
    agent._reflected_once = False
    agent._current_request = message
    is_worker = getattr(agent, "_agent_role", None) == "worker"
    trace = getattr(agent, "_trace_store", None) if is_worker else None
    # Worker 模式：记录任务开始
    if trace:
        trace.add("output", f"开始执行任务: {message[:300]}")
    state = {"consec_tool": "", "consec_count": 0, "consec_last_output": "",
             "used_tools": False, "last_failed": False}
    tool_call_history: list = []  # 跨轮防重复检测
    tool_schemas = [t.to_openai_tool() for t in agent._tools.list_tools()]
    control = {"stop": False}
    for _step in range(1, agent._max_iterations + 1):
        # Worker 模式：每步检查干预指令
        if is_worker:
            intervention = await agent.check_intervention()
            if intervention == "cancel":
                if trace:
                    trace.add("error", "任务被 Boss 取消")
                outcome["error"] = True
                if emit_done:
                    yield AgentEvent(type="error", content="任务被取消")
                    yield AgentEvent(type="done")
                return
            elif intervention == "pause":
                if trace:
                    trace.add("output", "任务暂停，等待恢复")
                await agent._wait_for_resume()
                if trace:
                    trace.add("output", "任务恢复执行")
            elif intervention == "redirect":
                new_msg = getattr(agent, "_redirect_instruction", "")
                if new_msg:
                    message = new_msg
                    agent._current_request = message
                    if trace:
                        trace.add("output", f"任务重定向: {message[:200]}")
        async for evt in _run_native_step(
            agent, llm_stream_fn, tool_schemas, adjudicator_check_fn,
            tool_call_history, state, outcome, emit_done, control):
            # Worker 模式：按事件类型记录轨迹
            if trace and evt.type == "thought":
                trace.add("thought", evt.content or "")
            elif trace and evt.type == "tool_call":
                trace.add("tool_call", str(evt.tool_input or ""),
                          {"tool_name": evt.tool_name or ""})
            elif trace and evt.type == "delta":
                trace.add("output", evt.content or "")
            elif trace and evt.type == "error":
                trace.add("error", evt.content or "")
            yield evt
        if control["stop"]:
            return
    outcome["error"] = True
    if trace:
        trace.add("error", "达到最大迭代次数")
    if emit_done:
        yield AgentEvent(type="error", content="Agent 已达到最大迭代次数，请简化指令")
        yield AgentEvent(type="done")

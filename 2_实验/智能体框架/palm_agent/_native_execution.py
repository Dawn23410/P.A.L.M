"""native 模式工具执行编排（从 native_runner.py 下沉，单一职责）。

承载：单工具分发、结果写记忆、连续同工具计数、后台任务安全网、提示注入剥离。
本模块只依赖 schemas / question_hub / tool_base / code_guard，不回引 native_runner，
避免循环导入；提示构建与流式分发仍留在 native_runner.py。
"""
from __future__ import annotations

import json
import re

from .schemas import AgentEvent
from .question_hub import get_question_hub
from .tool_base import validate_tool_args
from .code_guard import _run_code_guard, guard_background_command

# 连续同工具计数阈值（与 native_runner 保持一致，避免跨文件魔法数漂移）
_CONSEC_LIMIT_PROGRESS = 5
_CONSEC_LIMIT_STUCK = 3

# 提示注入高信号短语：工具结果写记忆前剔除（H1 防护）。仅移除短语而非整句，避免误删合法内容。
_INJECTION_RE = re.compile(
    r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions|prompts?)"
    r"|disregard\s+(the\s+)?(above|previous)"
    r"|you\s+are\s+now\s+"
    r"|system\s+prompt\s*[:：]"
    r"|#+\s*instructions"
    r"|忽略(之前|上述|以上|前面)的(所有)?(指令|提示|要求)"
    r"|忘记(之前|上述|以上)的(指令|对话|设定)"
    r"|(系统|开发者|开发者模式)\s*提示(词)?\s*[:：]",
    re.IGNORECASE,
)


def _strip_prompt_injection(text: str) -> str:
    """工具结果写记忆前剔除常见「提示注入」指令短语（H1 防护，保守移除短语）。"""
    if not text:
        return text
    return _INJECTION_RE.sub("", text)


def _parse_tool_arguments(fn: dict) -> dict:
    """解析 tool_call 的 arguments 字段为字典（失败回退空）。"""
    raw = fn.get("arguments", "") or "{}"
    try:
        return json.loads(raw) if raw.strip() else {}
    except Exception:  # noqa: BLE001
        return {}


def _update_consec_state(state: dict, name: str) -> None:
    """维护连续同工具调用计数（跨轮保持，换工具即重置）。"""
    if name == state["consec_tool"]:
        state["consec_count"] += 1
    else:
        state["consec_tool"] = name
        state["consec_count"] = 1
        state["consec_last_output"] = ""


async def _is_run_code_blocked(agent, args: dict, events: list, tc: dict) -> bool:
    """run_code 前置安全网；被拒则记录取消事件并返回 True。"""
    decision = await _run_code_guard(agent, args, events)
    if decision != "blocked":
        return False
    events.append(AgentEvent(
        type="tool_result", tool_name="run_code",
        tool_output="[已取消] 用户拒绝在还原点缺失或代码风险下执行",
        adjudicated=True, adjudicated_reason="用户拒绝"))
    agent._memory.add("tool", "用户拒绝执行 run_code", tool_call_id=tc.get("id"))
    return True


async def _is_background_task_blocked(agent, args: dict, events: list, tc: dict) -> bool:
    """start_background_task 前置安全网：扫危险模式 + 建还原点 + 确认弹窗（H4 修复）。
    被拒则记录取消事件并返回 True。
    """
    decision = await guard_background_command(agent, args.get("command", ""), events)
    if decision != "blocked":
        return False
    events.append(AgentEvent(
        type="tool_result", tool_name="start_background_task",
        tool_output="[已取消] 命令存在高风险，已被安全网拦截",
        adjudicated=True, adjudicated_reason="安全网拦截"))
    agent._memory.add("tool", "后台任务被安全网拦截", tool_call_id=tc.get("id"))
    return True


async def _record_ask_user(agent, args: dict, events: list, tc: dict) -> tuple[str, str]:
    """处理 ask_user 工具：弹窗、等待、记记忆，返回 (动作, 输出)。

    ask_user 事件经即时队列在 wait 前推送（agent._ask_events），否则消费方收不到
    事件无法应答、wait 永不返回（SSE 层并发消费该队列即时下发）。
    """
    spec = {
        "title": args.get("title", "请回答以下问题"),
        "content": args.get("content", "") or "",
        "qtype": args.get("question_type", "text"),
        "options": args.get("options") or [],
    }
    qid, spec = get_question_hub().create(agent._conversation_id, spec)
    ev = AgentEvent(type="ask_user", question=spec)
    events.append(ev)
    queue = getattr(agent, "_ask_events", None)
    if queue is not None:
        await queue.put(ev)
    answer = await get_question_hub().wait(qid)
    answer_text = agent._format_answer(args, answer)
    agent._memory.add("tool", f"用户回答: {answer_text}", tool_call_id=tc.get("id"))
    return "ask_user", answer_text


def _record_tool_memory(agent, exec_message: str, tc: dict,
                        artifacts: list | None = None) -> None:
    """工具结果回灌记忆；先剥离提示注入短语（H1），过长先截断，避免污染上下文。

    截图类产物（internal=True）在此注入模型上下文：
    - text 类型（ASCII）：追加到 observation 文本，所有模型可见
    - image 类型（原图）：tool 消息后追加一条 user 消息携带图像，需视觉模型支持
    """
    observation = _strip_prompt_injection(exec_message)
    images_to_inject = []
    if artifacts:
        for a in artifacts:
            if not a.get("internal"):
                continue
            if a.get("type") == "text":
                # ASCII 转义：直接追加到工具结果文本
                observation += f"\n\n[屏幕内容 ASCII 转义]\n{a['data']}\n[/屏幕内容 ASCII 转义]"
            elif a.get("type") == "image":
                # 原图：收集，稍后以独立 user 消息注入
                images_to_inject.append({"data": a["data"], "mime": a.get("mime", "image/png")})
    if len(observation) > 8000:
        observation = observation[:8000] + f"\n…（工具输出过长已截断，原始共 {len(exec_message)} 字符）"
    agent._memory.add("tool", observation, tool_call_id=tc.get("id"))
    # 原图模式：tool 消息后追加 user 消息携带图像（OpenAI tool 消息不支持 image content）
    if images_to_inject:
        agent._memory.add(
            "user",
            "[系统注入：截图原图回传] 以下是刚才截取的屏幕内容，请据此分析屏幕布局和内容：",
            images=images_to_inject,
        )


async def _record_normal_tool(agent, name: str, args: dict, tool_call_history,
                              adjudicator_check_fn, tc: dict, events: list) -> tuple[str, str]:
    """执行普通工具：处理裁决、写回记忆与事件。

    tool_call 事件由调用方在工具执行「前」即时下发，避免工具长时间运行（如扫盘）时
    前端要等结果返回才看到调用标志。这里只下发 tool_result。
    """
    action, exec_message, artifacts = await agent._handle_tool_call(
        name, args, tool_call_history, adjudicator_check_fn,
    )
    if action == "missing":
        events.append(AgentEvent(type="tool_result", tool_name=name, tool_output=exec_message))
        agent._memory.add("tool", exec_message, tool_call_id=tc.get("id"))
    elif action == "dedup":
        events.append(AgentEvent(type="tool_result", tool_name=name, tool_output=exec_message))
        agent._memory.add("tool", exec_message, tool_call_id=tc.get("id"))
    elif action == "blocked":
        events.append(AgentEvent(type="tool_result", tool_name=name, tool_output=exec_message,
                                 adjudicated=True, adjudicated_reason=exec_message))
        agent._memory.add("tool", exec_message, tool_call_id=tc.get("id"))
    else:
        # 内部产物（截图 ASCII/原图）不发给前端，仅注入模型上下文
        user_artifacts = [a for a in artifacts if not a.get("internal")]
        events.append(AgentEvent(type="tool_result", tool_name=name,
                                 tool_output=exec_message[:3000], artifacts=user_artifacts))
        _record_tool_memory(agent, exec_message, tc, artifacts=artifacts)
        internal_text = "\n\n".join(
            a.get("data", "") for a in artifacts
            if a.get("internal") and a.get("type") == "text" and a.get("data")
        )
        if internal_text:
            exec_message = f"{exec_message}\n\n{internal_text}"
    return action, exec_message


async def _run_single_tool(agent, tc: dict, adjudicator_check_fn, tool_call_history,
                           state: dict, events: list) -> tuple[str, str]:
    """分发单个 tool_call：run_code 守卫 / ask_user / 后台任务守卫 / 普通工具。"""
    fn = tc.get("function") or {}
    name = fn.get("name", "")
    args = _parse_tool_arguments(fn)
    _update_consec_state(state, name)
    allowed = getattr(agent, "_allowed_tool_names", None)
    if allowed is not None and name not in allowed:
        exec_message = f"工具 {name} 不在本次任务允许范围内，已拒绝执行"
        events.append(AgentEvent(type="tool_result", tool_name=name,
                                 tool_output=exec_message,
                                 adjudicated=True,
                                 adjudicated_reason="工具白名单限制"))
        agent._memory.add("tool", exec_message, tool_call_id=tc.get("id"))
        return "blocked", exec_message
    if name == "run_code" and await _is_run_code_blocked(agent, args, events, tc):
        return "blocked", "用户拒绝"
    # H4：后台任务脱离沙箱执行，必须过一遍安全网（扫危险模式 + 建还原点 + 确认）
    if name == "start_background_task" and await _is_background_task_blocked(agent, args, events, tc):
        return "blocked", "安全网拦截"
    if name == "ask_user":
        return await _record_ask_user(agent, args, events, tc)
    # P2a：参数 schema 校验，失败则回灌结构化错误（自愈），不执行工具。
    tool = agent._tools.get(name)
    if tool is not None:
        validation_error = validate_tool_args(tool.spec, args)
        if validation_error:
            events.append(AgentEvent(type="tool_result", tool_name=name,
                                     tool_output=validation_error))
            agent._memory.add("tool", validation_error, tool_call_id=tc.get("id"))
            state["consec_last_output"] = validation_error
            return "missing", validation_error
    last_action, last_output = await _record_normal_tool(
        agent, name, args, tool_call_history, adjudicator_check_fn, tc, events)
    state["consec_last_output"] = last_output
    return last_action, last_output


def _enforce_consec_limit(agent, state: dict, last_action: str | None) -> None:
    """连续同工具超阈值 → 注入强制收尾提示（仅 system prompt，不落盘）。"""
    is_stuck = last_action in ("blocked", "missing", "dedup")
    limit = _CONSEC_LIMIT_STUCK if is_stuck else _CONSEC_LIMIT_PROGRESS
    if state["consec_count"] >= limit:
        agent._force_text_hint = (
            f"（系统）检测到你已连续 {state['consec_count']} 次调用同一工具"
            f"{'且未推进任务' if is_stuck else ''}，"
            "请立即停止调用工具，直接把已有的工具结果用自然语言总结并回复用户。"
        )


async def _execute_tool_round(agent, tool_calls_acc, adjudicator_check_fn,
                              tool_call_history, state) -> dict:
    """执行本轮全部 tool_call，产出事件、写回结构化记忆、维护连续同工具计数与强制收尾。"""
    events: list[AgentEvent] = []
    last_action: str | None = None
    last_output = ""
    failed_this_round = False
    for tc in tool_calls_acc:
        fn = tc.get("function") or {}
        name = fn.get("name", "")
        last_action, last_output = await _run_single_tool(
            agent, tc, adjudicator_check_fn, tool_call_history, state, events)
        if last_action in ("missing", "blocked"):
            failed_this_round = True
        final_answer = agent._completion_gate.try_complete(
            getattr(agent, "_current_request", ""), name, last_output)
        if final_answer:
            state["completion_answer"] = final_answer
            state["last_failed"] = False
            state["used_tools"] = True
            return {"events": events, "last_action": last_action, "last_output": last_output}
    _enforce_consec_limit(agent, state, last_action)
    state["used_tools"] = bool(tool_calls_acc)
    state["last_failed"] = failed_this_round
    return {"events": events, "last_action": last_action, "last_output": last_output}

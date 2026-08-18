"""闲置编排器：闲置时主动进化/习惯推测并提案（分级自主权 B 方案核心）。

设计要点（源自自主进化架构决策）：
- 闲置判定用后端 last_user_activity_ts（每次对话 API 调用刷新），不依赖前端心跳。
- 闲置触发 → 读偏好简报/近期记忆 → habit_engine 排 top-1 最可能任务 → adjudicator 风险门 → 提案气泡。
- 分级自主权：autonomy_level=proposal 始终提案；balanced/full 当前亦提案（自动执行留作安全接缝），
  风险门（adjudicator blocked/deny）始终拦截高风险提案。
- 实时对话始终走 LLM，本模块只切主动/闲时层，人格零回归。
"""
from __future__ import annotations

import time

from palm_sdk.bricks.base import registry
from palm_sdk.guardrail.engine import get_guardrail_capability

_IDLE_THRESHOLD_DEFAULT = 15  # 分钟；设置 idle_minutes 可覆盖。


def _load_settings() -> dict:
    brick = registry.get("settings")
    if not brick:
        return {}
    fn = (getattr(brick, "capabilities", {}) or {}).get("load_app_settings")
    if not fn:
        return {}
    try:
        return fn() or {}
    except Exception:
        return {}


# 后端活动时间戳（模块级，由 agent 砖在 /run、/ask-response 时刷新）。
_LAST_ACTIVITY = time.time()


def touch_activity() -> None:
    # 刷新最后用户活动时间；agent 砖在对话入口调用。
    global _LAST_ACTIVITY
    _LAST_ACTIVITY = time.time()


def get_idle_seconds() -> float:
    # 距最后用户活动的秒数；供闲置判定与测试。
    return time.time() - _LAST_ACTIVITY


def _is_idle() -> bool:
    minutes = int(_load_settings().get("idleMinutes", _IDLE_THRESHOLD_DEFAULT))
    return get_idle_seconds() >= max(1, minutes) * 60


def _autonomy_level() -> str:
    return _load_settings().get("autonomyLevel", "balanced")


def _adjudicator_allows() -> bool:
    # 风险门：经统一护栏（palm_sdk.guardrail）评估主动提案事件；拒绝/deny 则拦截。
    # 裁决引擎砖已拆，安全门由 guardrail 承接；默认宽松档放行，异常时 fail-closed 拦截。
    try:
        cap = get_guardrail_capability()
        result = cap("agent.proactive", {"source": "idle_orchestrator"})
        if result is None:
            return True
        if getattr(result, "blocked", False):
            return False
        return getattr(result, "action_type", "") != "deny"
    except Exception:
        # 护栏为核心安全基础设施，不应缺失；异常时 fail-closed 拦截而非放行。
        return False


async def maybe_idle_run(conversation_id: str, character_id: str, model: str) -> bool:
    # 闲置且满足自主权/风险门时，推送一条习惯推测提案气泡。返回是否真的推送了。
    if not _is_idle():
        return False
    if not _adjudicator_allows():
        return False
    from .habit_engine import describe_task, infer_top_task

    task = infer_top_task(character_id)
    label = describe_task(task)
    if not label:
        return False

    # 分级自主权：proposal/balanced 走提案；full 当前亦提案（自动执行留作安全接缝）。
    text = f"（闲置推测）你常在这个时段做这类事——要我{label}吗？"
    _push_bubble(conversation_id, text)
    return True


def _push_bubble(conversation_id: str, text: str) -> None:
    # 经 agent 砖暴露的 push_bubble 能力把提案作为助手气泡推到会话队列
    #（气泡的 SSE 序列化与 AgentEvent 由 agent 负责，evolution 不反向 import agent 内部符号）。
    from palm_sdk.bricks._shared.interop import get_agent_api
    api = get_agent_api()
    if api is not None:
        api.push_bubble(conversation_id, text)
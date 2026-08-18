"""主动推送 / 闲置编排 / 每日摘要的编排入口（原属 agent 砖的「自主进化」域）。

本砖收编：background_tasks（SSE/心跳调度单例）/ habit_engine（习惯推断）/
fallback_engine（本地兜底）/ idle_orchestrator（闲置提案）/ offline_digest（每日偏好简报），
并暴露统一主动推送入口 run_proactive 供 scheduler 砖经 capabilities 触发。

砖间契约：本砖经 app.bricks._shared.interop 取用 agent（run_proactive_stream /
push_bubble）/ settings / monitor / scheduler（砖）能力，零反向 import。
"""
from __future__ import annotations

import asyncio
import logging

from palm_sdk.bricks.base import registry
from .background_tasks import scheduler
from . import idle_orchestrator
from . import offline_digest
from . import fallback_engine

from palm_sdk.bricks._shared.interop import get_agent_api

_LOGGER = logging.getLogger(__name__)


# 闲置编排任务哨兵与系统会话（供调度器周期触发习惯推测提案）。
IDLE_SENTINEL = "__IDLE__::"
IDLE_CONV = "__idle__"
IDLE_JOB_TITLE = "闲置习惯推测"

_IDLE_JOB_REGISTERED = False


def _load_app_settings() -> dict:
    # 经 settings 砖能力读取应用设置。
    settings_brick = registry.get("settings")
    if not settings_brick:
        return {}
    load_fn = (getattr(settings_brick, "capabilities", {}) or {}).get("load_app_settings")
    if not load_fn:
        return {}
    try:
        return load_fn() or {}
    except Exception:
        return {}


def _resolve_effective_mode() -> str:
    # 经 monitor 砖能力解析有效模式（max/eco）；缺砖/异常降级 max。
    monitor = registry.get("monitor")
    if monitor:
        fn = (getattr(monitor, "capabilities", {}) or {}).get("resolve_effective_mode")
        if fn:
            try:
                return fn()
            except Exception as exc:
                _LOGGER.debug("模式解析失败，降级 max: %s", exc)
    return "max"


def push_local_bubble(conversation_id: str, text: str) -> None:
    # 不经 LLM 的本地推送：让 agent 把文本作为助手气泡投到会话队列（eco/闲置共用）。
    api = get_agent_api()
    if api is not None:
        api.push_bubble(conversation_id, text)


def ensure_idle_job() -> None:
    # 惰性注册闲置周期任务（运行时 scheduler 砖已就绪，避开导入顺序问题）。
    global _IDLE_JOB_REGISTERED
    if _IDLE_JOB_REGISTERED:
        return
    _IDLE_JOB_REGISTERED = True
    scheduler_brick = registry.get("scheduler")
    if not scheduler_brick:
        return
    caps = getattr(scheduler_brick, "capabilities", {}) or {}
    create_fn = caps.get("create_job")
    store_fn = caps.get("list_jobs")
    if not create_fn:
        return
    try:
        if store_fn and any(j.get("title") == IDLE_JOB_TITLE for j in store_fn()):
            return
        minutes = int(_load_app_settings().get("idleMinutes", 15))
        create_fn(
            conversation_id=IDLE_CONV,
            character_id="",
            model="",
            title=IDLE_JOB_TITLE,
            brief=IDLE_SENTINEL,
            schedule_type="interval",
            schedule_value=str(max(1, minutes) * 60),
        )
    except Exception:
        _IDLE_JOB_REGISTERED = False


def run_proactive(conversation_id: str, character_id: str, model: str, brief: str) -> None:
    """主动推送同步入口：把异步推送提交到 agent 事件循环（跨线程安全）。

    调度引擎在守护线程同步调用本函数，若直接定义为 async 协程会被丢弃、
    定时提醒永不触发；改为同步入口 + run_coroutine_threadsafe 真正驱动推送。
    """
    loop = getattr(scheduler, "_loop", None)
    if loop is None:
        _LOGGER.warning("事件循环未就绪，主动推送延迟（会话 %s）", conversation_id)
        return
    asyncio.run_coroutine_threadsafe(
        run_proactive_async(conversation_id, character_id, model, brief), loop
    )


async def run_proactive_async(conversation_id: str, character_id: str, model: str, brief: str) -> None:
    """主动推送异步实现：模式分支（eco 本地 / 摘要 / 闲置 / max 走 LLM）。

    eco 模式与闲置推测只切主动/闲时层，实时对话始终走 LLM，人格零回归。
    """
    # 惰性注册每日摘要与闲置任务（运行时 scheduler 砖已就绪）。
    try:
        offline_digest.register_daily_digest()
        ensure_idle_job()
    except Exception:  # noqa: BLE001
        _LOGGER.warning("主动任务惰性注册失败（下次重试）")

    # 摘要任务：不经 LLM 推送，直接生成并保存简报到记忆体系。
    if brief.startswith(offline_digest.DIGEST_SENTINEL):
        await offline_digest.run_digest(conversation_id, character_id, model or "")
        return

    # 闲置编排：触发习惯推测提案（含 adjudicator 风险门 + 分级自主权）。
    if brief.startswith(IDLE_SENTINEL):
        await idle_orchestrator.maybe_idle_run(conversation_id, character_id, model or "")
        return

    # 模式分支：eco 且非摘要/闲置 → 本地确定性推送，不经 LLM。
    if _resolve_effective_mode() == "eco":
        push_local_bubble(conversation_id, fallback_engine.local_proactive_content(brief))
        return

    # max / 默认 → LLM 生成（原逻辑）。
    if not model:
        _LOGGER.warning("主动推送缺少模型（会话 %s），跳过", conversation_id)
        return
    api = get_agent_api()
    if api is None or not hasattr(api, "run_proactive_stream"):
        _LOGGER.warning("agent 砖未就绪，主动推送跳过（会话 %s）", conversation_id)
        return
    req_dict = {
        "conversation_id": conversation_id,
        "message": brief,
        "model": model,
        "character_id": character_id or "",
        "persona_text": "",
        "use_planning": False,
        "tool_mode": "native",
        "max_iterations": 10,
    }
    try:
        async for sse_line in api.run_proactive_stream(req_dict, is_wakeup=True):
            scheduler.push_event(conversation_id, sse_line)
    except Exception:  # noqa: BLE001
        _LOGGER.exception("主动推送 Agent 失败（会话 %s）", conversation_id)


async def wakeup_agent(conversation_id: str, model: str, reminder: str) -> None:
    """后台任务完成回调：以无角色模式唤醒 Agent 总结。"""
    run_proactive(conversation_id, "", model, reminder)
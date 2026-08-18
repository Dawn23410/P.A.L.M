"""自主进化砖：主动推送 / 闲置编排 / 每日摘要 / 习惯推断 / 本地兜底。

原属 agent 砖的「自主进化」域（后台任务调度 / 闲置提案 / 偏好简报 / 习惯学习 / 本地兜底），
现抽为独立砖。经 capabilities["evolution_api"] 暴露全部符号，供 agent / scheduler 经
app.bricks._shared.interop.get_evolution_api() 取用，保持砖间零互导。

注意：本砖经 agent 砖能力 run_proactive_stream / push_bubble 回调，注册顺序须 agent 在前。
"""
from __future__ import annotations

from .background_tasks import scheduler
from .habit_engine import (
    infer_top_task,
    describe_task,
    record_feedback,
)
from .fallback_engine import (
    local_proactive_content,
    should_override,
    on_timeout,
    on_offline,
)
from .idle_orchestrator import (
    touch_activity,
    get_idle_seconds,
    maybe_idle_run,
)
from .offline_digest import (
    run_digest,
    register_daily_digest,
    DIGEST_SENTINEL,
    DIGEST_CONV,
    DIGEST_CHAR,
    DIGEST_JOB_TITLE,
    DIGEST_CRON,
)
from .proactive import (
    IDLE_SENTINEL,
    IDLE_CONV,
    IDLE_JOB_TITLE,
    run_proactive,
    run_proactive_async,
    wakeup_agent,
    push_local_bubble,
    ensure_idle_job,
)

__all__ = [
    "scheduler",
    "infer_top_task",
    "describe_task",
    "record_feedback",
    "local_proactive_content",
    "should_override",
    "on_timeout",
    "on_offline",
    "touch_activity",
    "get_idle_seconds",
    "maybe_idle_run",
    "run_digest",
    "register_daily_digest",
    "DIGEST_SENTINEL",
    "DIGEST_CONV",
    "DIGEST_CHAR",
    "DIGEST_JOB_TITLE",
    "DIGEST_CRON",
    "IDLE_SENTINEL",
    "IDLE_CONV",
    "IDLE_JOB_TITLE",
    "run_proactive",
    "run_proactive_async",
    "wakeup_agent",
    "push_local_bubble",
    "ensure_idle_job",
]

from . import brick  # noqa: E402,F401  触发砖注册

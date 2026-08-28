"""定时与提醒工具：让 agent 在对话中为用户创建定时任务 / 提醒。

工具读取当前会话/角色/模型上下文（contextvar），调用 scheduler 砖的 create_job 能力，
不跨砖直接 import。permission 留空（fail-open）：仅登记本地通知，不触碰文件/系统/外部。
"""
from __future__ import annotations

from palm._core.tooling import (
    Tool,
    ToolSpec,
    agent_character_id,
    agent_conversation_id,
    agent_model,
)
from palm._core.container import registry


def _scheduler_create():
    sched = container.get("scheduler")
    if not sched:
        return None
    return (getattr(sched, "capabilities", {}) or {}).get("create_job")


def _resolve_when(when: str) -> tuple[str, str]:
    """把 remind 工具的 when 归一到 (schedule_type, schedule_value)。"""
    w = (when or "").strip()
    low = w.lower()
    if low in ("daily", "weekly", "monthly"):
        cron_map = {"daily": "0 9 * * *", "weekly": "0 9 * * 1", "monthly": "0 9 1 * *"}
        return "cron", cron_map[low]
    if len(w.split()) == 5:  # 5 字段 cron
        return "cron", w
    if "t" in low or ("-" in w and ":" in w):  # ISO 时间
        return "once", w
    return "", ""


def _create(title: str, brief: str, schedule_type: str, schedule_value: str) -> str:
    create_fn = _scheduler_create()
    if not create_fn:
        return "定时任务引擎未就绪，无法创建任务。"
    conversation_id = agent_conversation_id.get()
    character_id = agent_character_id.get()
    model = agent_model.get()
    if not conversation_id:
        return "当前会话上下文缺失，无法创建定时任务。"
    try:
        job = create_fn(
            conversation_id, character_id, model, title, brief, schedule_type, schedule_value
        )
    except Exception as exc:  # noqa: BLE001
        return f"创建定时任务失败：{type(exc).__name__}: {exc}"
    return f"已创建定时任务（{job.id}）：「{title}」，周期 {schedule_type}={schedule_value}。"


class RemindTool(Tool):
    """对话中设置提醒：在指定时间主动向当前会话推送提醒。"""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="remind",
            description=(
                "为用户设置一个提醒：在指定时间主动向当前会话推送一条提醒（助理会主动发消息）。"
                "when 支持：ISO 时间（如 2026-08-05T09:00，一次性）、cron 表达式"
                "（分 时 日 月 周，如 0 9 * * * 每天 9 点）、或 daily/weekly/monthly。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "提醒内容，会作为推送文案（助理可据角色润色）。"},
                    "when": {"type": "string", "description": "触发时间：ISO 时间 / cron 表达式 / daily|weekly|monthly。"},
                    "title": {"type": "string", "description": "可选，任务标题，便于管理页识别。"},
                },
                "required": ["text", "when"],
            },
            event_type="",
            permission="",
        )

    async def execute(self, text: str, when: str, title: str = "") -> str:
        schedule_type, schedule_value = _resolve_when(when)
        if not schedule_type:
            return "无法解析提醒时间，请使用 ISO 时间（如 2026-08-05T09:00）、cron 表达式或 daily/weekly/monthly。"
        return _create(text, title or text, schedule_type, schedule_value)


class ScheduleTaskTool(Tool):
    """创建周期性主动推送任务（每日简报、定期报告等）。"""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="schedule_task",
            description=(
                "创建一个周期性主动推送任务（如每日简报、定期报告）：在设定周期主动向当前会话推送内容。"
                "schedule_type 为 once/interval/cron/rrule；schedule_value 对应：ISO 时间 / 秒数 /"
                " cron 表达式（分 时 日 月 周）/ RRULE 串（如 FREQ=DAILY;BYHOUR=9）。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "任务标题。"},
                    "brief": {"type": "string", "description": "推送时给助理的提示（决定推送内容）。"},
                    "schedule_type": {"type": "string", "description": "once | interval | cron | rrule"},
                    "schedule_value": {"type": "string", "description": "与类型对应的时间串。"},
                },
                "required": ["title", "brief", "schedule_type", "schedule_value"],
            },
            event_type="",
            permission="",
        )

    async def execute(self, title: str, brief: str, schedule_type: str, schedule_value: str) -> str:
        if schedule_type not in ("once", "interval", "cron", "rrule"):
            return f"不支持的周期类型：{schedule_type}（应为 once/interval/cron/rrule）。"
        return _create(title, brief, schedule_type, schedule_value)


SCHEDULER_TOOLS = [RemindTool, ScheduleTaskTool]
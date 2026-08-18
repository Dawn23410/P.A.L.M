"""执行器共享常量与模块级工具函数（被各 mixin 与 core 共同引用，避免循环依赖）。"""
import logging

_LOGGER = logging.getLogger(__name__)

# 用户移动鼠标超过该距离视为主动干预，执行器自动取消
_MOUSE_INTERRUPT_PX = 50
# 每步之间的稳定延迟（防误点；步骤可传 delay 覆盖，界面切换场景自行加大）
_DEFAULT_STEP_DELAY = 0.2
# wait 动作单步上限（配合 run 总超时防卡死）
_MAX_WAIT_SEC = 10
_PAUSE_POLL_SEC = 0.2

# 执行器状态常量
_IDLE, _EXECUTING, _PAUSED, _CANCELLED = "idle", "executing", "paused", "cancelled"


def _step_key(step: dict) -> str:
    """定位条件规范化键（用于缓存命中）：只取影响目标身份的字段。"""
    return "|".join([
        step.get("name", ""), step.get("automation_id", ""),
        step.get("control_type", ""), step.get("action", ""),
    ])

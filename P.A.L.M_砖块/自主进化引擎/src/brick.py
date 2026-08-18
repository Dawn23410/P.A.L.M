"""自主进化砖：注册 + 对外暴露 evolution_api 门面。

原属 agent 砖的「自主进化」域（后台任务调度 / 闲置提案 / 偏好简报 / 习惯学习 / 本地兜底），
现抽为独立砖。所有符号经 capabilities["evolution_api"] 暴露，供 agent / scheduler 经
app.bricks._shared.interop.get_evolution_api() 取用，保持砖间零互导。

启动时把后台任务调度器的唤醒回调注册为 wakeup_agent，使调度器能反向驱动 Agent 总结。
"""
from __future__ import annotations

import sys

from palm_sdk.bricks.base import Brick, BrickManifest, registry
from .background_tasks import scheduler
from .proactive import wakeup_agent

# evolution_api 即本砖包对象：__init__ 已把全部符号（scheduler / run_proactive /
# touch_activity / 各类引擎函数等）挂为包属性，consumers 直接取用。
evolution_api = sys.modules[__package__]

# 启动即注册唤醒回调，使调度器能反向驱动 Agent（后台任务完成自动唤醒总结）。
scheduler.set_wakeup_handler(wakeup_agent)

brick = Brick(
    manifest=BrickManifest(
        name="evolution",
        title="自主进化引擎",
        description="后台任务调度 / 闲置习惯推测 / 每日偏好简报 / 习惯学习 / 本地兜底（eco 模式）。",
        bus_type="board",
    ),
    capabilities={
        "evolution_api": evolution_api,
    },
)

registry.register(brick)
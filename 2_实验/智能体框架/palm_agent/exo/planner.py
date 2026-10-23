"""薄桥接层：实现在主工程 agent 框架（`palm.services.agent.dual.dual_planner`）。

外骨骼并入主工程时去重：本模块原为移植副本，现直接复用主工程原件。
"""
from palm_agent.dual.dual_planner import *  # noqa: F401,F403
from palm_agent.dual.dual_planner import (  # noqa: F401
    STEP_PENDING,
    STEP_RUNNING,
    STEP_DONE,
    STEP_FAILED,
    STEP_SKIPPED,
    PlanStep,
    Plan,
    Planner,
)

_HostPlanner = Planner


class Planner(_HostPlanner):  # type: ignore[no-redef]
    """适配层：主工程版 plan 是 async 且需 model 参数；外骨骼按同步调用。"""

    def plan(self, goal, tools_summary="", memory_context="", llm_fn=None,
             model="", total=0, **kwargs):
        from .model import _run_sync

        return _run_sync(super().plan(goal, tools_summary, memory_context,
                                      llm_fn, model, total=total, **kwargs))

"""薄桥接层：实现在主工程 agent 框架（`palm.services.agent.dual.trace_store`）。

外骨骼并入主工程时去重：本模块原为移植副本，现直接复用主工程原件。
"""
from palm_agent.dual.trace_store import *  # noqa: F401,F403
from palm_agent.dual.trace_store import (  # noqa: F401
    T_THOUGHT,
    T_TOOL_CALL,
    T_TOOL_RESULT,
    T_OUTPUT,
    T_PLAN,
    T_ERROR,
    T_INTERVENTION,
    TraceEntry,
    TraceStore,
)

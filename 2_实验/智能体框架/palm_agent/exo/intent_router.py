"""薄桥接层：实现在主工程 agent 框架（`palm.services.agent.dual.intent_router`）。

外骨骼并入主工程时去重：本模块原为移植副本，现直接复用主工程原件。
"""
from palm_agent.dual.intent_router import *  # noqa: F401,F403
from palm_agent.dual.intent_router import (  # noqa: F401
    I_CHAT,
    I_TASK,
    I_INTERVENTION,
    I_QUERY,
    IntentResult,
    IntentRouter,
)

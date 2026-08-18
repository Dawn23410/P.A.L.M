"""记忆砖：统一记忆接口 + 五子模块 + 短期语义筛选 + 向量记忆。

原属 agent 砖的「记忆」域（长期归档 / 核心记忆 / 向量语义检索 / Token 预算 / 压缩），
现抽为独立砖。经 capabilities["memory_api"] 暴露全部符号，供 agent / evolution 经
app.bricks._shared.interop.get_memory_api() 取用，保持砖间零互导。

注意：本砖强依赖 roleplay 砖（剥离角色语气、双线好感度状态），注册顺序须 roleplay 在前。
"""
from __future__ import annotations

from .memory import Memory, create_memory
from .memory_layer.base import Conversation
from .memory_layer.core_memory import CoreMemory
from .memory_layer.archived_memory import ArchivedMemory, DecayCalculator
from .memory_layer.token_budget import TokenBudgetAllocator
from .memory_layer.memory_writer import MemoryWriter
from .memory_layer.vector_memory import VectorMemory, purge_vector_by_conv_id

__all__ = [
    "Memory",
    "create_memory",
    "Conversation",
    "CoreMemory",
    "ArchivedMemory",
    "DecayCalculator",
    "TokenBudgetAllocator",
    "MemoryWriter",
    "VectorMemory",
    "purge_vector_by_conv_id",
]

from . import brick  # noqa: E402,F401  触发砖注册

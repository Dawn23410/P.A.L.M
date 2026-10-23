"""palm_memory — P.A.L.M 记忆层独立可跑版。

从 D:\\P.A.L.M 记忆大块抽出的最小可运行子集，专注**双幂律衰减 + 去噪归一 + 情绪五因子**。
仅依赖标准库；不引入 numpy / chromadb / httpx，无需网络与本地模型。

    from palm_memory import DecayCalculator, ArchivedMemory
"""
from __future__ import annotations

from .domain_memory.archived_memory import DecayCalculator, ArchivedMemory
from .domain_memory.base import ArchivedItem, CoreMemoryData, Personality, UserProfile
from .domain_memory.core_memory import CoreMemory
from .domain_memory.memory_writer import MemoryWriter

__all__ = [
    "DecayCalculator",
    "ArchivedMemory",
    "ArchivedItem",
    "CoreMemory",
    "CoreMemoryData",
    "MemoryWriter",
    "Personality",
    "UserProfile",
]

__version__ = "1.0.0-standalone"

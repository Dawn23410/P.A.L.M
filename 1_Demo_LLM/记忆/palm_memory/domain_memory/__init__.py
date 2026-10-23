"""domain_memory —— 记忆算法本体（双幂律衰减 + 去噪归一 + 情绪五因子）。

从产线 palm_memory/domain_memory 抽出的最小集：
  - base            数据结构
  - archived_memory DecayCalculator（核心算法，逐字取自产线）+ ArchivedMemory
  - core_memory     CoreMemory（去除了角色扮演/好感度宿主依赖，保留核心事实 + 持久化）
  - memory_writer   MemoryWriter（写入决策 + 授权断言防伪）
"""
from __future__ import annotations

from .archived_memory import ArchivedMemory, DecayCalculator
from .base import ArchivedItem, CoreMemoryData, Personality, SafetyConstraints, UserProfile
from .core_memory import CoreMemory
from .memory_writer import MemoryWriter

__all__ = [
    "ArchivedMemory",
    "DecayCalculator",
    "ArchivedItem",
    "CoreMemory",
    "CoreMemoryData",
    "MemoryWriter",
    "Personality",
    "SafetyConstraints",
    "UserProfile",
]

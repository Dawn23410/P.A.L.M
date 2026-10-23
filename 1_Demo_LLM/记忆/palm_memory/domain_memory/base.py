"""记忆层数据结构 —— 与产线 base.py 字段完全一致（去除了与独立运行无关的可选项）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class SafetyLevel(str, Enum):
    STRICT = "strict"
    MODERATE = "moderate"
    RELAXED = "relaxed"


@dataclass
class Personality:
    name: str = ""
    traits: list[str] = field(default_factory=list)
    preferences: dict[str, Any] = field(default_factory=dict)
    affinity: float = 0.0


@dataclass
class UserProfile:
    real_name: str = ""
    basic_info: dict[str, Any] = field(default_factory=dict)


@dataclass
class SafetyConstraints:
    forbidden_topics: list[str] = field(default_factory=list)
    safety_level: SafetyLevel = SafetyLevel.MODERATE


@dataclass
class CoreMemoryData:
    personality: Personality = field(default_factory=Personality)
    user_profile: UserProfile = field(default_factory=UserProfile)
    safety_bottom_line: SafetyConstraints = field(default_factory=SafetyConstraints)
    recent_history: list[dict] = field(default_factory=list)
    last_updated: datetime = field(default_factory=datetime.now)
    violation_count: int = 0
    cooldown_active: bool = False
    cooldown_remaining: int = 0
    current_age: str = ""
    current_grade: str = ""


@dataclass
class ArchivedItem:
    id: str = ""
    content: str = ""
    importance: int = 3
    weight_imp: float = 1.0
    last_accessed: datetime = field(default_factory=datetime.now)
    access_count: int = 0
    create_time: datetime = field(default_factory=datetime.now)
    aging_bonus: float = 0.0
    # 情绪向量（编码时捕获，用于非对称衰减）
    valence: float = 0.0              # 效价 [-1, +1]，正=积极 负=消极
    arousal: float = 0.0              # 唤醒 [0, 1]，0=平静 1=极度激动
    emotion_confidence: float = 0.0   # 情绪置信度 [0, 1]，0=无情绪数据(向后兼容)

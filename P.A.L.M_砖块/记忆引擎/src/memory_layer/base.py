"""记忆层数据结构。"""
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
    # 越界追踪（角色扮演引擎使用）
    violation_count: int = 0              # 当前累计越界次数（10 轮内）
    cooldown_active: bool = False         # 是否处于冷却模式
    cooldown_remaining: int = 0           # 冷却剩余轮数
    current_age: str = ""                 # 当前年龄（如"16"）
    current_grade: str = ""               # 当前年级（如"高一"）


@dataclass
class Conversation:
    id: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    user_input: str = ""
    agent_response: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


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


@dataclass
class ProgramRule:
    id: str = ""
    content: str = ""
    context: str = ""
    importance: int = 5
    create_time: datetime = field(default_factory=datetime.now)


@dataclass
class ScheduledTask:
    id: str = ""
    trigger_time: datetime = field(default_factory=datetime.now)
    action: str = ""
    content: str = ""
    status: str = "pending"

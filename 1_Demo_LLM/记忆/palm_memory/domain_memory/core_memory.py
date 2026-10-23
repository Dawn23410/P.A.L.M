"""核心记忆 —— 永久冻结、每轮注入的事实层 + JSON 持久化。

取自产线 core_memory.py，剥离了角色扮演砖（roleplay）与好感度砖（affinity）依赖：
独立版只保留"核心事实 + 近期历史 + 越界/冷却状态字段"的读写能力，不依赖任何宿主砖。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .base import CoreMemoryData, Personality, SafetyConstraints, SafetyLevel, UserProfile

_LOGGER = logging.getLogger(__name__)


class CoreMemory:
    def __init__(self, persist_path: str | None = None, character_card: Any | None = None):
        self._data = CoreMemoryData()
        self._persist_path = Path(persist_path) if persist_path else None
        self._character_card = character_card

    # ── 持久化 ─────────────────────────────────────────

    async def initialize(self) -> None:
        if self._persist_path and self._persist_path.exists():
            try:
                raw = json.loads(self._persist_path.read_text(encoding="utf-8"))
                up = raw.get("user_profile", {})
                sf = raw.get("safety", {})
                self._data = CoreMemoryData(
                    personality=Personality(**raw.get("personality", {})),
                    recent_history=raw.get("recent_history", []),
                    user_profile=UserProfile(
                        real_name=up.get("real_name", ""),
                        basic_info=up.get("basic_info", {}),
                    ),
                    safety_bottom_line=SafetyConstraints(
                        forbidden_topics=sf.get("forbidden_topics", []),
                        safety_level=SafetyLevel(sf.get("safety_level", "moderate")),
                    ),
                    violation_count=raw.get("violation_count", 0),
                    cooldown_active=raw.get("cooldown_active", False),
                    cooldown_remaining=raw.get("cooldown_remaining", 0),
                    current_age=raw.get("current_age", ""),
                    current_grade=raw.get("current_grade", ""),
                )
                _LOGGER.info("核心记忆已加载")
            except Exception as exc:
                _LOGGER.warning("核心记忆加载失败: %s", exc)
        else:
            _LOGGER.info("核心记忆初始化为默认值")

    async def shutdown(self) -> None:
        if not self._persist_path:
            return
        self._persist_path.parent.mkdir(parents=True, exist_ok=True)
        raw = {
            "personality": {
                "name": self._data.personality.name,
                "traits": self._data.personality.traits,
                "preferences": self._data.personality.preferences,
            },
            "recent_history": self._data.recent_history,
            "user_profile": {
                "real_name": self._data.user_profile.real_name,
                "basic_info": self._data.user_profile.basic_info,
            },
            "safety": {
                "forbidden_topics": self._data.safety_bottom_line.forbidden_topics,
                "safety_level": self._data.safety_bottom_line.safety_level.value,
            },
            "violation_count": self._data.violation_count,
            "cooldown_active": self._data.cooldown_active,
            "cooldown_remaining": self._data.cooldown_remaining,
            "current_age": self._data.current_age,
            "current_grade": self._data.current_grade,
        }
        self._persist_path.write_text(
            json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    # ── 事实读写 ────────────────────────────────────────

    def update_profile(self, text: str) -> None:
        """从自述文本抽取姓名（产线同款极简规则）。"""
        if "我叫" in text:
            name = text.split("我叫", 1)[1].strip().rstrip("。，！,.")
            if name:
                self._data.user_profile.real_name = name

    def set_trait(self, trait: str) -> None:
        if trait and trait not in self._data.personality.traits:
            self._data.personality.traits.append(trait)

    @property
    def affinity(self) -> float:
        """独立版无好感度砖，恒返回角色卡声明的静态值（默认 0.0）。"""
        return float(self._data.personality.affinity)

    def inject_into_context(self) -> str:
        parts = [f"记忆摘要：{self._data.personality.name}"]
        if self._data.personality.name:
            parts.append(f"姓名：{self._data.personality.name}")
        if self._data.user_profile.real_name:
            parts.append(f"用户姓名：{self._data.user_profile.real_name}")
        return "\n".join(parts)

    # ── 越界 / 冷却（字段保留，供上层引擎使用） ─────────────

    @property
    def violation_count(self) -> int:
        return self._data.violation_count

    def record_violation(self) -> int:
        self._data.violation_count += 1
        return self._data.violation_count

    def reset_violations(self) -> None:
        self._data.violation_count = 0

    @property
    def cooldown_active(self) -> bool:
        return self._data.cooldown_active

    def enter_cooldown(self) -> None:
        self._data.cooldown_active = True
        self._data.cooldown_remaining = 3

    def tick_cooldown(self) -> None:
        if not self._data.cooldown_active:
            return
        self._data.cooldown_remaining -= 1
        if self._data.cooldown_remaining <= 0:
            self._data.cooldown_active = False
            self._data.cooldown_remaining = 0
            self._data.violation_count = 0

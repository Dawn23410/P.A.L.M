"""
核心记忆 —— 永久冻结，每轮注入。

同时承载角色扮演引擎的状态（越界追踪、冷却、年龄等），
由人格引擎代码管理，不在 prompt 中暴露计算过程。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from .base import CoreMemoryData, Personality, UserProfile, SafetyConstraints, SafetyLevel
from palm._core.interop import get_roleplay_api, get_affinity_api

_LOGGER = logging.getLogger(__name__)


def _rp():
    """取角色扮演砖门面（memory 依赖 roleplay，缺失即报错，便于及早发现注册顺序问题）。"""
    api = get_roleplay_api()
    if api is None:
        raise RuntimeError("记忆砖依赖的 roleplay 砖未注册")
    return api


def _aff():
    """取好感度砖门面（好感度域 2026-08-06 拆出独立砖，缺失即报错）。"""
    api = get_affinity_api()
    if api is None:
        raise RuntimeError("记忆砖依赖的 affinity 砖未注册")
    return api


class CoreMemory:
    def __init__(self, persist_path: str | None = None, character_card: Any | None = None):
        self._data = CoreMemoryData()
        self._persist_path = Path(persist_path) if persist_path else None
        self._character_card = character_card
        enabled = bool(getattr(character_card, "affinity_enabled", True)) if character_card else True
        # 好感度砖可能未注册（离线条件/注册顺序问题）——降级而非硬失败，
        # 保证核心记忆读写始终可用（fail-operational）。
        self._affinity_disabled = False
        self._affinity_store = None
        try:
            self._affinity_store = _aff().AffinityStore(self._persist_path)
        except Exception as exc:
            self._affinity_disabled = True
            _LOGGER.warning("好感度砖不可用，CoreMemory 进入降级模式（仅核心记忆可用）: %s", exc)

    def _aff_store(self):
        """安全访问好感度 store；未注册时返回 None（调用方需短路）。"""
        return self._affinity_store

    def build_dynamic_overlay(self, user_message: str, stage_name: str = "") -> str:
        """整合角色动态机制：解析运行时叠加层（年龄/关系/叙事），绝不回写角色卡。

        同时接入记忆层幂律复苏（关键词"被想起"时，情感记忆按幂律衰减形状苏醒，
        产出一段临时心境注入 dynamics 方向）。角色未启用好感度时返回空串（短路）。
        stage_name 缺省时按当前 base 自动匹配档名（relation 类依赖）。
        """
        if self._aff_store() is None or not self._affinity_store.is_enabled():
            return ""
        # 档名缺省：从当前 base 匹配（避免调用方重复推导）
        if not stage_name:
            try:
                st = self._affinity_store.get_state()
                rs = _aff().resolve_ruleset(self._character_card)
                tier = rs.match_base_tier(float(st.get("base", 0.0)))
                stage_name = tier.name
            except Exception:
                stage_name = ""
        resonance = self.memory_decay_resonance(user_message)
        from datetime import date as _date
        st = self._affinity_store.get_state()
        ctx = _aff().RuntimeContext(
            stage_name=stage_name,
            user_message=user_message,
            first_active_date=st.get("first_active_date", ""),
            now_date=_date.today().isoformat(),
            resonance=resonance,
        )
        overlay = _aff().resolve_dynamic_overlays(ctx)
        return overlay.merged_text()

    def memory_decay_resonance(self, user_message: str) -> list[str]:
        """关键词幂律复苏：当前用户消息命中的情感记忆，按记忆层衰减形状苏醒。

        复用 archived_memory 的 DecayCalculator（(1/(1+λ·天))^γ × 重要度权重）：
        越近期、越重要的暖心/扎心瞬间被提起时，复苏越强，产出一段临时心境文本
        （正向→温柔暖意，负向→淡淡酸涩），随后由 dynamics_engine 注入方向。
        角色未启用好感度 / 无记忆层时返回空列表（干净短路）。
        """
        if self._aff_store() is None or not self._affinity_store.is_enabled():
            return []
        archived = getattr(self, "_archived", None)
        if archived is None:
            return []
        try:
            # 用当前用户消息作为关键词锚，检索情感记忆（不触碰 last_accessed，
            # 否则每轮重置会让所有条目永不衰减；复苏是"被动想起"，不算显式召回）。
            hits = archived.search(user_message, top_k=3, touch=False)
            lines: list[str] = []
            for item in hits:
                # 仅复苏带"关系升温/受挫"语义的情感事件（由 _record_emotion_event 写入）
                if "关系明显" not in item.content and "好感度" not in item.content:
                    continue
                decay = item.weight_imp  # 已含重要度权重 1+ln(importance)
                positive = "升温" in item.content
                if positive:
                    mood = "（旧日暖意）你又想起那次让彼此靠近的瞬间，语气不自觉地温柔了几分。"
                else:
                    mood = "（旧日微涩）你想起那次让关系轻轻受挫的瞬间，此刻多了点小心翼翼。"
                # 强度随衰减形状衰减：decay 越大（越近/越重要）复苏越明显
                prefix = "（深刻）" if decay >= 3 else "（淡淡）"
                lines.append(prefix + mood)
            return lines
        except Exception as exc:
            _LOGGER.debug("记忆复苏失败（非致命）: %s", exc)
            return []

    async def initialize(self) -> None:
        enabled = bool(getattr(self._character_card, "affinity_enabled", True)) if self._character_card else True
        self._archived = None  # 由 Memory 注入（避免循环依赖）
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
        st = self._aff_store()
        if st is not None:
            await st.initialize(affinity_enabled=enabled)

    async def shutdown(self) -> None:
        if self._persist_path:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            st = self._aff_store()
            if st is not None:
                await st.shutdown()
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
            self._persist_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    @property
    def affinity(self) -> float:
        st = self._aff_store()
        return st.get() if st is not None else 0.0

    def get_affinity(self) -> float:
        """兼容旧调用：返回 base（饱和后）。"""
        st = self._aff_store()
        return st.get() if st is not None else 0.0

    def get_affinity_state(self) -> dict:
        """返回完整双线状态（新流程）。"""
        st = self._aff_store()
        if st is None:
            return {"base": 0.0, "dynamics": 0.0, "bond": 0.0,
                    "last_active_date": "", "affinity_enabled": False}
        return st.get_state()

    def set_affinity(self, value: float) -> None:
        """兼容旧调用：直接设定 base（用于迁移/测试）。"""
        st = self._aff_store()
        if st is not None:
            st.apply_settlement(value, 0.0, 0.0, "")

    def settle_affinity_from_model(self, model_text: str) -> dict:
        """从模型回复末尾 JSON 结算一轮双线好感度，写回 store。

        角色未启用好感度时短路返回中性状态（引擎不结算、不落盘）。
        大幅涨/跌时由调用方（brick done 钩子）记录情感事件到记忆层。
        """
        st = self._aff_store()
        if st is None or not st.is_enabled():
            if st is not None:
                return st.get_state()
            return {"base": 0.0, "dynamics": 0.0, "bond": 0.0,
                    "last_active_date": "", "affinity_enabled": False}
        cur = st.get_state()
        state = _aff().AffinityState(
            base=cur["base"], dynamics=cur["dynamics"], bond=cur["bond"],
            last_active_date=cur["last_active_date"], affinity_enabled=True,
        )
        result = _aff().settle_from_model(state, model_text, self._character_card)
        st.apply_settlement(
            result.base, result.dynamics, result.bond, state.last_active_date
        )
        return {
            "base": result.base, "dynamics": result.dynamics, "bond": result.bond,
            "stage_name": result.stage_name, "greeting": result.greeting,
            "bond_gained": result.bond_gained, "overflowed": result.overflowed,
            "raw_base_delta": result.raw_base_delta, "raw_dyn_delta": result.raw_dyn_delta,
        }

    # ── 角色扮演引擎状态 ──

    @property
    def violation_count(self) -> int:
        return self._data.violation_count

    def record_violation(self) -> int:
        """记录一次越界，返回累计次数。"""
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
        """每轮递减冷却计数，结束后重置。"""
        if not self._data.cooldown_active:
            return
        self._data.cooldown_remaining -= 1
        if self._data.cooldown_remaining <= 0:
            self._data.cooldown_active = False
            self._data.cooldown_remaining = 0
            self._data.violation_count = 0

    @property
    def age(self) -> tuple[str, str]:
        return (self._data.current_age, self._data.current_grade)

    def set_age(self, age: str, grade: str) -> None:
        self._data.current_age = age
        self._data.current_grade = grade

    def inject_into_context(self) -> str:
        parts = [f"记忆摘要：{self._data.personality.name}"]
        if self._data.personality.name:
            parts.append(f"姓名：{self._data.personality.name}")
        return "\n".join(parts)

    # ── 角色扮演引擎 stance 注入（由 brick.py 每轮调用） ──

    def build_stance_injection(self, card: Any = None) -> str:
        """态度注入：仅称呼 + 语气 + 当下心情方向，零数值（前端也不显示数值）。

        角色未启用好感度时返回空串（引擎短路，不注入任何态度指令）。
        冷却态保留（越界后角色冷淡少说话）。
        """
        st = self._affinity_store.get_state()
        if not st.get("affinity_enabled", True):
            return ""
        affinity = _aff().AffinityState(
            base=st["base"], dynamics=st["dynamics"], bond=st["bond"],
            last_active_date=st["last_active_date"], affinity_enabled=True,
        )
        # CharacterCard 仍属角色扮演砖（roleplay），isinstance 判断经 roleplay 门面取。
        base_text = _aff().stance_text(
            affinity, card if isinstance(card, _rp().CharacterCard) else None)
        if self._data.cooldown_active:
            return (base_text + "\n越界冷却中：明显冷淡，少说话。").strip()
        return base_text

    def update_profile(self, text: str) -> None:
        if "我叫" in text:
            name = text.split("我叫", 1)[1].strip().rstrip("。，！,.")
            if name:
                self._data.personality.name = name
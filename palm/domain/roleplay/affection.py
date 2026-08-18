"""双线好感度系统：规则驱动（YAML 规则文件 + 引擎零硬编码）。

设计（2026-08-03 锁定，取代旧版单线信号词表）：
- 双线情感：base（地基，信任/熟悉，变化慢，范围 -50~100，档位饱和于 100）
            + dynamics（温度计，当下心情，变化快，范围 -50~50，自然回归 0）
            + bond（羁绊值，无上限，承接 base 溢出，纯装饰/叙事）。
- 升降由模型每轮回复末尾 JSON 决定（{"affinity_delta","emotion_delta"}），
  后端解析后按当前档 max_up/max_down 钳制，降幅显著高于升幅。
- 范围 -50~100，可正可负；无每日上限，但档位与经验系数饱和于 100。
- 角色可选：affinity_enabled=False 时调用方短路，不结算、不建存储。
- 数值全隐藏：stance 仅输出称呼 + 语气，绝不出现数值或档名数字。
- 规则与代码低耦合：引擎只认 RuleSet，档位来自 official_6stage.yaml 或
  角色卡 affinity_stages（完全自定义）。
- 2026-08-06 独立成砖（affinity）：与角色卡（roleplay 砖）解耦，仅依赖
  AffinityCardLike 鸭子契约（affinity_stages / affinity_enabled），不再 import CharacterCard。

遗留兼容（`AffinityTierHelper` / `affinity_stage` / `adjust_affinity_from_turn`）
保留为薄壳，委托新引擎，避免测试与旧调用方一次性全红；新代码应直接调用
`affinity_engine`。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Protocol

from .affinity_engine import (
    RuleSet,
    SettlementResult,
    load_official_ruleset,
    load_ruleset_from_stages,
    parse_model_affinity_json,
    settle,
)


class AffinityCardLike(Protocol):
    """角色卡的鸭子契约：好感度域只读这两个字段，不依赖角色卡砖（roleplay）。"""
    affinity_enabled: bool
    affinity_stages: list | None


@dataclass
class AffinityState:
    """一轮好感度的完整状态。仅承载数值，规则由引擎提供。"""
    base: float = 0.0
    dynamics: float = 0.0
    bond: float = 0.0
    last_active_date: str = field(default_factory=lambda: date.today().isoformat())
    affinity_enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "base": self.base,
            "dynamics": self.dynamics,
            "bond": self.bond,
            "last_active_date": self.last_active_date,
            "affinity_enabled": self.affinity_enabled,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "AffinityState":
        return cls(
            base=float(raw.get("base", 0.0)),
            dynamics=float(raw.get("dynamics", 0.0)),
            bond=float(raw.get("bond", 0.0)),
            last_active_date=str(raw.get("last_active_date", date.today().isoformat())),
            affinity_enabled=bool(raw.get("affinity_enabled", True)),
        )


def resolve_ruleset(card: AffinityCardLike | None) -> RuleSet:
    """按角色卡选择规则集：自定义档优先，否则官方 6 阶。"""
    if card and getattr(card, "affinity_stages", None):
        return load_ruleset_from_stages(card.affinity_stages)
    return load_official_ruleset()


def days_absent_since(last_active_date: str) -> int:
    """距上次活跃的整天数（今天仍活跃返回 0）。"""
    try:
        last = datetime.fromisoformat(last_active_date).date()
    except Exception:
        return 0
    return max(0, (date.today() - last).days)


def settle_from_model(
    state: AffinityState,
    model_text: str,
    card: AffinityCardLike | None = None,
) -> SettlementResult:
    """从模型回复文本结算一轮双线好感度（纯计算，不落盘）。

    流程：解析末尾 JSON → 仅当今天未活跃时应用整段久别冷却（不跨天复利）
          → 引擎 settle → 写回 state（含 last_active 更新）→ 返回结果。
    """
    rs = resolve_ruleset(card)
    # 直接解析模型末尾结算 JSON（含 affinity_delta/emotion_delta 键）。
    # 注意：不要用 react_parser._strip_affinity_json 预处理——那会删掉我们要解析的 JSON。
    # 模型泄露的 ```json 代码块由 react_parser 在正文显示侧剥离，不影响此处数值结算。
    raw_base, raw_dyn = parse_model_affinity_json(model_text)

    absent = days_absent_since(state.last_active_date)
    # 久别冷却只在"今天首次活跃（跨天断裂）"时针对整段缺席应用一次；
    # 之后立即把 last_active 更新为今天，当天后续对话 absent=0，不复利。
    apply_absent = absent if absent >= 1 else 0

    result = settle(
        base=state.base,
        dynamics=state.dynamics,
        bond=state.bond,
        raw_base_delta=raw_base,
        raw_dyn_delta=raw_dyn,
        rs=rs,
        days_absent=apply_absent,
        days_since_dyn_event=apply_absent,
    )
    state.base = result.base
    state.dynamics = result.dynamics
    state.bond = result.bond
    state.last_active_date = date.today().isoformat()
    return result


def stance_text(state: AffinityState, card: AffinityCardLike | None = None) -> str:
    """返回行为立场提示（注入 system）：仅称呼 + 语气，零数值。

    角色未启用好感度时返回空串（干净短路，不注入任何态度指令）。
    """
    if not state.affinity_enabled:
        return ""
    rs = resolve_ruleset(card)
    # 表现值 = base（饱和后）+ dynamics；档位按 base 饱和值匹配
    tier = rs.match_base_tier(state.base)
    greet = tier.greeting
    tone = tier.tone
    # 温度计轻微调语气（熟但此刻冷 / 生但此刻热）——仅用方向词，不露数值
    mood = ""
    if state.dynamics <= -20:
        mood = "此刻略显冷淡疏离"
    elif state.dynamics >= 20:
        mood = "此刻格外热情投入"
    parts = [f"称呼用户为「{greet}」。" if greet else ""]
    if tone:
        parts.append(tone)
    if mood:
        parts.append(mood)
    return "\n".join(p for p in parts if p)


# ── 遗留兼容壳（委托新引擎；新代码直接用 affinity_engine / AffinityState） ──

# 旧版官方 6 档阈值（2026-08-03 早期稿），仅用于兼容壳与遗留测试，新代码勿用。
_LEGACY_TIERS = [
    {"name": "抵触", "threshold": -100, "greeting": "喂", "tone": "冷漠、厌恶、回避，不愿多说话", "max_up": 0.2, "max_down": 0.3},
    {"name": "疏远", "threshold": -50, "greeting": "你", "tone": "冷淡、保持距离，不带感情", "max_up": 0.3, "max_down": 0.3},
    {"name": "初识", "threshold": -10, "greeting": "同学", "tone": "礼貌平淡，偶尔傲娇嘴硬，但不亲密", "max_up": 0.4, "max_down": 0.4},
    {"name": "友好", "threshold": 10, "greeting": "你", "tone": "友好、会关心人，傲娇较轻", "max_up": 0.4, "max_down": 0.3},
    {"name": "亲近", "threshold": 40, "greeting": "你", "tone": "语气更亲密、更依赖，傲娇很轻", "max_up": 0.3, "max_down": 0.2},
    {"name": "亲密", "threshold": 70, "greeting": "主人", "tone": "热情卖萌 + 中度傲娇 + 可爱病娇", "max_up": 0.2, "max_down": 0.1},
]


class AffinityTierHelper:
    """兼容旧签名与遗留测试：默认走旧阈值，仅当角色自定义档时委托新引擎。

    注意：本类是过渡垫片，新代码应直接使用 affinity_engine / AffinityState，
    不要再依赖此处的旧档位语义。
    """

    def __init__(self, card: AffinityCardLike | None = None) -> None:
        self._card = card
        self._custom = bool(card and getattr(card, "affinity_stages", None))
        if self._custom:
            self._rs = resolve_ruleset(card)

    def _legacy_tier(self, affinity: float) -> dict:
        matched = [t for t in _LEGACY_TIERS if affinity >= t.get("threshold", 0)]
        return matched[-1] if matched else _LEGACY_TIERS[-1]

    def find_tier(self, affinity: float) -> dict:
        if self._custom:
            t = self._rs.match_base_tier(affinity)
            return {"name": t.name, "greeting": t.greeting, "tone": t.tone,
                    "max_up": t.max_up, "max_down": t.max_down, "threshold": t.lower_bound}
        return {**self._legacy_tier(affinity)}

    def name(self, affinity: float) -> str:
        return self.find_tier(affinity)["name"]

    def greeting(self, affinity: float) -> str:
        return self.find_tier(affinity)["greeting"]

    def tone(self, affinity: float) -> str:
        return self.find_tier(affinity)["tone"]

    def max_up(self, affinity: float) -> float:
        return self.find_tier(affinity)["max_up"]

    def max_down(self, affinity: float) -> float:
        return self.find_tier(affinity)["max_down"]

    def all_names(self) -> list[str]:
        return [t["name"] for t in _LEGACY_TIERS]

    def stance_text(self, affinity: float) -> str:
        t = self.find_tier(affinity)
        parts = [f"称呼用户为「{t['greeting']}」。" if t.get("greeting") else ""]
        if t.get("tone"):
            parts.append(t["tone"])
        return "\n".join(p for p in parts if p)

    def tier_summary(self) -> str:
        lines = ["好感度等级（仅供内部参考）："]
        for t in sorted(_LEGACY_TIERS, key=lambda x: x.get("threshold", 0)):
            lines.append(f"  {t['threshold']:+.0f}~ {t['name']}：称呼「{t['greeting']}」，{t['tone']}（+{t['max_up']}/-{t['max_down']}）")
        return "\n".join(lines)


def affinity_stage(affinity: float, card: AffinityCardLike | None = None) -> str:
    """兼容旧调用：按 base 值取档名。"""
    return AffinityTierHelper(card).name(affinity)


def adjust_affinity_from_turn(
    user_text: str,
    assistant_text: str,
    card: AffinityCardLike | None = None,
    current_affinity: float = 0.0,
) -> float:
    """遗留兼容：单线词表已弃用，新流程改由 settle_from_model 经模型 JSON 结算。

    保留签名仅作兼容垫片——返回当前值（无启发式增减），避免旧调用方崩溃。
    新代码请勿调用。
    """
    return current_affinity

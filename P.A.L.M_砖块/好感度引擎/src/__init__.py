"""好感度引擎子包（独立砖）：双线好感度 / 动态叠加 / 存储 / 结算。

2026-08-06 从 roleplay 砖拆出：好感度域（affection / affinity_engine /
affinity_store / dynamics_engine + 规则 yaml）拥有独立数据（agent_affinity/）
与独立生命周期，消费方（memory / agent）经 capabilities["affinity_api"] 取用，
砖间零互导。对角色卡的依赖收敛为 AffinityCardLike 鸭子契约（见 affection.py）。
"""
from __future__ import annotations

from .affection import (
    AffinityCardLike,
    adjust_affinity_from_turn,
    affinity_stage,
    AffinityState,
    AffinityTierHelper,
    resolve_ruleset,
    settle_from_model,
    stance_text,
)
from .affinity_engine import (
    RuleSet,
    SettlementResult,
    load_official_ruleset,
    load_ruleset_from_stages,
    parse_model_affinity_json,
    settle,
)
from .affinity_store import AffinityStore
from .dynamics_engine import RuntimeContext, resolve_dynamic_overlays

__all__ = [
    "AffinityCardLike",
    "adjust_affinity_from_turn",
    "affinity_stage",
    "AffinityState",
    "AffinityTierHelper",
    "resolve_ruleset",
    "settle_from_model",
    "stance_text",
    "RuleSet",
    "SettlementResult",
    "load_official_ruleset",
    "load_ruleset_from_stages",
    "parse_model_affinity_json",
    "settle",
    "AffinityStore",
    "RuntimeContext",
    "resolve_dynamic_overlays",
]

from . import brick  # noqa: E402,F401  触发砖注册

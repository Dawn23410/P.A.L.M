"""双线好感度规则引擎：规则（YAML）与代码低耦合。

设计（2026-08-03 锁定）：
- 引擎只认 RuleSet 数据结构，零硬编码任何档位 / 名称 / 系数。
- 两条线：
  · base（地基）：信任 / 熟悉度，变化极慢，范围 -50~100，档位匹配饱和于 saturation。
  · dynamics（温度计）：当下心情，变化快，范围 -50~50，自然回归 0。
  · bond（羁绊值）：无上限，承接 base 溢出与超额增益，纯装饰 / 叙事。
- 升降由模型每轮回复末尾 JSON 决定（见 resolve_from_model），前端数值全隐藏。
- 角色可选：affinity_enabled=False 时调用方应短路，不进入本引擎结算。
- 久别疏离：base 乘温柔幂律冷却因子（复用记忆层衰减形状），比"被冒犯"温柔 10 倍。

规则文件优先用 pyyaml；不可用时回退 _minimal_yaml（仅服务本仓库规整格式）。
"""
from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)

_RULES_DIR = Path(__file__).parent / "affection_rules"


@dataclass
class Stage:
    """单个关系档：lower_bound 下限 + 名称 + 称呼 + 语气 + 升降幅上限。"""
    lower_bound: float
    name: str
    greeting: str
    tone: str
    max_up: float
    max_down: float


@dataclass
class RuleSet:
    """一套完整好感度规则（来自一个 YAML 文件）。引擎只认这个结构。"""
    base_range: tuple[float, float] = (-50.0, 100.0)
    base_saturation: float = 100.0
    base_stages: list[Stage] = field(default_factory=list)
    dyn_range: tuple[float, float] = (-50.0, 50.0)
    dyn_max_up: float = 10.0
    dyn_max_down: float = 15.0
    dyn_regression_lambda: float = 0.2
    dyn_regression_gamma: float = 0.9
    bond_unbounded: bool = True

    def match_base_tier(self, base: float) -> Stage:
        """按 lower_bound 找到当前所处档（取满足下界的最大值）。"""
        matched = [s for s in self.base_stages if base >= s.lower_bound]
        if matched:
            return max(matched, key=lambda s: s.lower_bound)
        # 低于所有下界：返回下限最低的一档（兜底，理论不会触发）
        return min(self.base_stages, key=lambda s: s.lower_bound)


# ── 规则文件加载（优先 pyyaml，失败回退内置安全网） ──

def _load_yaml_text(text: str) -> dict | None:
    try:
        import yaml  # 生产环境已具备（adjudicator 砖使用）
        return yaml.safe_load(text)
    except Exception:
        # 无 yaml：返回 None，调用方回退到内置常量（与 official_6stage.yaml 内容一致）。
        return None


def _build_ruleset(raw: dict) -> RuleSet:
    base = raw.get("base", {}) or {}
    dyn = raw.get("dynamics", {}) or {}
    bond = raw.get("bond", {}) or {}
    stages = [
        Stage(
            lower_bound=float(s.get("lower_bound", -50)),
            name=str(s.get("name", "未命名")),
            greeting=str(s.get("greeting", "你")),
            tone=str(s.get("tone", "")),
            max_up=float(s.get("max_up", 0.05)),
            max_down=float(s.get("max_down", 0.5)),
        )
        for s in (base.get("stages", []) or [])
    ]
    return RuleSet(
        base_range=tuple(base.get("range", [-50, 100])),
        base_saturation=float(base.get("saturation", 100)),
        base_stages=stages,
        dyn_range=tuple(dyn.get("range", [-50, 50])),
        dyn_max_up=float(dyn.get("max_up", 10)),
        dyn_max_down=float(dyn.get("max_down", 15)),
        dyn_regression_lambda=float(dyn.get("regression_lambda", 0.2)),
        dyn_regression_gamma=float(dyn.get("regression_gamma", 0.9)),
        bond_unbounded=bool(bond.get("unbounded", True)),
    )


# 内置安全网：与 official_6stage.yaml 内容一致。仅在 pyyaml 不可用时启用，
# 保证功能不崩；正常情况下规则来自 YAML 文件（规则与代码解耦）。
_BUILTIN_OFFICIAL: dict = {
    "base": {
        "range": [-50, 100], "saturation": 100,
        "stages": [
            {"lower_bound": -50, "name": "抵触", "greeting": "喂", "tone": "冷漠、厌恶、回避，不愿多说话", "max_up": 0.05, "max_down": 0.60},
            {"lower_bound": -10, "name": "陌生", "greeting": "你", "tone": "冷淡、保持距离，不带感情", "max_up": 0.10, "max_down": 0.50},
            {"lower_bound": 0, "name": "初识", "greeting": "同学", "tone": "礼貌平淡，偶尔傲娇嘴硬，但不亲密", "max_up": 0.08, "max_down": 0.40},
            {"lower_bound": 30, "name": "友好", "greeting": "你", "tone": "友好、会关心人，傲娇较轻", "max_up": 0.05, "max_down": 0.30},
            {"lower_bound": 60, "name": "亲近", "greeting": "你", "tone": "语气更亲密、更依赖，傲娇很轻", "max_up": 0.03, "max_down": 0.20},
            {"lower_bound": 85, "name": "亲密", "greeting": "主人", "tone": "热情卖萌 + 中度傲娇 + 可爱病娇", "max_up": 0.02, "max_down": 0.15},
        ],
    },
    "dynamics": {"range": [-50, 50], "max_up": 10.0, "max_down": 15.0, "regression_lambda": 0.2, "regression_gamma": 0.9},
    "bond": {"unbounded": True},
}


_OFFICIAL_RULESET: RuleSet | None = None


def load_official_ruleset() -> RuleSet:
    """加载内置官方 6 阶规则（默认规则文件）。结果缓存。

    优先从 affection_rules/official_6stage.yaml 加载（规则与代码解耦）；
    pyyaml 不可用时回退内置常量，保证功能可用。
    """
    global _OFFICIAL_RULESET
    if _OFFICIAL_RULESET is not None:
        return _OFFICIAL_RULESET
    raw: dict | None = None
    path = _RULES_DIR / "official_6stage.yaml"
    try:
        if path.exists():
            raw = _load_yaml_text(path.read_text(encoding="utf-8"))
    except Exception:
        raw = None
    if not raw:
        raw = _BUILTIN_OFFICIAL
    _OFFICIAL_RULESET = _build_ruleset(raw)
    return _OFFICIAL_RULESET


def load_ruleset_from_stages(stages: list[dict]) -> RuleSet:
    """从角色卡传入的自定义档位（affinity_stages）构造 RuleSet。

    自定义档：用户全自定义边界/名称/称呼/反应/增减幅度——与官方 6 阶共用同一引擎。
    """
    base_stages = [
        Stage(
            lower_bound=float(s.get("lower_bound", -50)),
            name=str(s.get("name", "未命名")),
            greeting=str(s.get("greeting", "你")),
            tone=str(s.get("tone", "")),
            max_up=float(s.get("max_up", 0.05)),
            max_down=float(s.get("max_down", 0.5)),
        )
        for s in stages
    ]
    rs = load_official_ruleset()
    # 自定义档：复用官方 dynamics/bond，仅替换 base 档位与范围
    rs.base_stages = base_stages
    if stages:
        lowers = [s.lower_bound for s in base_stages]
        rs.base_range = (min(lowers), max(lowers))
    return rs


# ── 双线结算 ──

def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def absence_cooling_factor(days_absent: float) -> float:
    """久别温柔幂律冷却因子：base 乘以它。

    复用记忆层衰减形状（(1/(1+λ·天))^γ），比"被冒犯"温柔 10 倍；
    一天未见≈0.98、一周≈0.88、一月≈0.62——回来聊聊即回暖，非惩罚。
    """
    if days_absent <= 0:
        return 1.0
    lam, gamma = 0.05, 1.0
    return (1.0 / (1.0 + lam * days_absent)) ** gamma


def dynamics_regression(dynamics: float, days_since_event: float, rs: RuleSet) -> float:
    """温度计按幂律形状朝 0 平复（越久无新情绪波动，越往 0 收）。"""
    if days_since_event <= 0:
        return dynamics
    factor = (1.0 / (1.0 + rs.dyn_regression_lambda * days_since_event)) ** rs.dyn_regression_gamma
    return dynamics * factor


def resolve_base_delta(base: float, raw_delta: float, rs: RuleSet) -> float:
    """把模型给出的 base 增量按当前档 max_up/max_down 钳制。降幅显著高于升幅。"""
    tier = rs.match_base_tier(base)
    if raw_delta > 0:
        return min(raw_delta, tier.max_up)
    if raw_delta < 0:
        return max(raw_delta, -tier.max_down)
    return 0.0


def resolve_dynamics_delta(raw_delta: float, rs: RuleSet) -> float:
    """温度计增量钳制（快线，幅度比地基大）。"""
    return _clamp(raw_delta, -rs.dyn_max_down, rs.dyn_max_up)


@dataclass
class SettlementResult:
    """一轮好感度结算结果。"""
    base: float
    dynamics: float
    bond: float
    stage_name: str
    greeting: str
    tier_tone: str
    bond_gained: float
    overflowed: bool          # base 是否溢出 saturation 流入 bond
    raw_base_delta: float = 0.0
    raw_dyn_delta: float = 0.0


def settle(
    base: float,
    dynamics: float,
    bond: float,
    raw_base_delta: float,
    raw_dyn_delta: float,
    rs: RuleSet,
    days_absent: float = 0.0,
    days_since_dyn_event: float = 0.0,
) -> SettlementResult:
    """执行一轮双线结算（纯函数，不落盘）。

    流程：温度计先回归 → base 先久别冷却 → 各自叠加模型增量（按阶钳制）
          → base 饱和于 saturation，溢出流入 bond。
    """
    # 1) 温度计幂律回归
    dynamics = dynamics_regression(dynamics, days_since_dyn_event, rs)
    # 2) 地基久别温柔冷却
    base = base * absence_cooling_factor(days_absent)
    # 3) 叠加模型增量（钳制）
    base = base + resolve_base_delta(base, raw_base_delta, rs)
    dynamics = dynamics + resolve_dynamics_delta(raw_dyn_delta, rs)
    # 4) base 饱和：超出 saturation 的溢出流入 bond
    bond_gained = 0.0
    overflowed = False
    sat = rs.base_saturation
    if base > sat:
        bond_gained = base - sat
        bond = bond + bond_gained
        base = sat
        overflowed = True
    # 5) 钳制到 base 范围（允许短暂低于 0 的负区间，但守住硬下限）
    base = _clamp(base, rs.base_range[0], max(sat, rs.base_range[1]))
    dynamics = _clamp(dynamics, rs.dyn_range[0], rs.dyn_range[1])
    # 6) 档位匹配（仅用饱和后的 base）
    tier = rs.match_base_tier(base)
    return SettlementResult(
        base=round(base, 4),
        dynamics=round(dynamics, 4),
        bond=round(bond, 4),
        stage_name=tier.name,
        greeting=tier.greeting,
        tier_tone=tier.tone,
        bond_gained=round(bond_gained, 4),
        overflowed=overflowed,
        raw_base_delta=raw_base_delta,
        raw_dyn_delta=raw_dyn_delta,
    )


def parse_model_affinity_json(text: str) -> tuple[float, float]:
    """从模型回复末尾解析 {"affinity_delta": x, "emotion_delta": y}。

    找不到则返回 (0.0, 0.0)。模型输出格式宽松：键名兼容
    affinity_delta / emotion_delta，也兼容中文键（当前好感度/情绪变化）。
    解析失败静默返回零，绝不抛错污染对话流。
    """
    # 取文本中最后一个 {…} 片段（好感度 JSON 极简、无嵌套，[^{}]* 足够）。
    # 先去掉 ``` 代码围栏行，避免 ```json 包裹干扰。
    cleaned = re.sub(r"```(?:json)?\s*", "", text)
    matches = re.findall(r"\{[^{}]*\}", cleaned.strip())
    if not matches:
        return (0.0, 0.0)
    try:
        obj = json.loads(matches[-1])
    except Exception:
        return (0.0, 0.0)
    if not isinstance(obj, dict):
        return (0.0, 0.0)
    base_delta = _extract_delta(obj, ("affinity_delta", "base_delta", "好感度变化", "当前好感度变化"))
    dyn_delta = _extract_delta(obj, ("emotion_delta", "dynamics_delta", "情绪变化", "心情变化"))
    return (float(base_delta), float(dyn_delta))


def _extract_delta(obj: dict, keys: tuple[str, ...]) -> float:
    for k in keys:
        if k in obj:
            try:
                return float(obj[k])
            except (TypeError, ValueError):
                return 0.0
    return 0.0

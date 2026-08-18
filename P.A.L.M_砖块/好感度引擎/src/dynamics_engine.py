"""角色动态信息机制：规则引擎驱动，仅预设接口、不开放自定义。

设计（2026-08-03 锁定）：
- 三类预设动态（详见 dynamics_rules/*.yaml，与引擎零耦合）：
  · time（时间型）：随现实/会话时间推移发生的状态变化，如年龄/年级增长。
  · relation（关系型）：随好感度档位跨越触发的状态变化，如关系里程碑称呼/身份。
  · narrative（叙事型）：由用户侧关键词触发的临时状态变化，如某话题被提起时的心境。
- 只作用于运行时人设（persona overlay），绝不回写角色卡（character.json）。
- 引擎只认 DynamicRule 数据结构，规则来自 YAML；无 YAML 时回退内置常量。
- 关键不变量：动态字段是"叠加层"，不修改 CharacterCard 的任何原始字段。

注：narrative 类的"关键词复苏"会进一步影响 emotional_dynamics 注入值（见
memory_decay_resonance），本文件只负责产出 overlay 文本，复苏项由上游传入。
"""
from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)

_RULES_DIR = Path(__file__).parent / "dynamics_rules"


# ── 数据结构 ──

@dataclass
class DynamicRule:
    """一条动态规则：在满足条件时产出一段人设 overlay 文本。"""
    kind: str                      # time / relation / narrative
    id: str
    when: str = ""                 # 人类可读的触发条件（仅文档，不参与计算）
    trigger: str = ""              # 触发键：time→无；relation→档名；narrative→关键词（支持 * 通配）
    overlay: str = ""             # 注入到运行时人设的文本（叠加，不回写卡）
    priority: int = 0              # 同 kind 多命中时取最高优先级（数值大优先）
    min_days: int = 0              # time 类：自首次活跃起至少经过的天数（年龄增长节奏）


@dataclass
class DynamicOverlay:
    """一次动态解析结果（运行时叠加层，不落盘）。"""
    texts: list[str] = field(default_factory=list)
    applied_rule_ids: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not self.texts

    def merged_text(self) -> str:
        return "\n".join(self.texts)


# ── 规则加载（优先 pyyaml，失败回退内置常量） ──

def _load_yaml_text(text: str) -> list[dict] | None:
    try:
        import yaml
        raw = yaml.safe_load(text)
        if isinstance(raw, dict):
            rules = raw.get("rules", [])
        elif isinstance(raw, list):
            rules = raw
        else:
            return None
        return [r for r in rules if isinstance(r, dict)] if rules else None
    except Exception:
        return None


def _build_rules(raw_list: list[dict]) -> list[DynamicRule]:
    out: list[DynamicRule] = []
    for r in raw_list:
        out.append(DynamicRule(
            kind=str(r.get("kind", "narrative")),
            id=str(r.get("id", "")),
            when=str(r.get("when", "")),
            trigger=str(r.get("trigger", "")),
            overlay=str(r.get("overlay", "")),
            priority=int(r.get("priority", 0)),
            min_days=int(r.get("min_days", 0)),
        ))
    return out


# 内置安全网：与 dynamics_rules/*.yaml 内容一致。仅在 pyyaml 不可用时启用。
_BUILTIN_RULES: list[dict] = [
    # 时间型：年龄/年级随"自首次活跃起经过的天数"增长（min_days 控制节奏）
    {"kind": "time", "id": "age_growth", "when": "自首次活跃起经过足够天数，角色心境更成熟",
     "trigger": "", "priority": 10, "min_days": 365,
     "overlay": "（时间推移）你已比初遇时长了一岁，心境更成熟从容。"},
    # 关系型：跨越到「亲密」档时解锁专属身份称呼
    {"kind": "relation", "id": "intimate_title", "when": "好感度到达亲密档",
     "trigger": "亲密", "priority": 10,
     "overlay": "（关系里程碑）你们已亲密无间，你以更私密的口吻与对方相处。"},
    {"kind": "relation", "id": "close_title", "when": "好感度到达亲近档",
     "trigger": "亲近", "priority": 5,
     "overlay": "（关系进展）你们的关系已明显亲近，你更自然地流露依赖。"},
    # 叙事型：用户提起特定话题时触发临时心境（仅运行时，不回写）
    {"kind": "narrative", "id": "mention_hometown", "when": "用户提及家乡/故乡",
     "trigger": "*家乡*", "priority": 5,
     "overlay": "（情境）对方提到了家乡，你想起自己远方的家，语气里多了一丝柔软。"},
    {"kind": "narrative", "id": "mention_future", "when": "用户提及未来/梦想",
     "trigger": "*未来*", "priority": 5,
     "overlay": "（情境）对方聊起未来，你眼里亮了一下，认真接住了这个话题。"},
]


_RULES_CACHE: list[DynamicRule] | None = None


def load_dynamics_rules() -> list[DynamicRule]:
    """加载全部动态规则（合并目录下所有 YAML）。结果缓存。

    优先加载 dynamics_rules/ 下所有 *.yaml；pyyaml 不可用时回退内置常量，
    保证动态机制不崩（规则与代码解耦）。
    """
    global _RULES_CACHE
    if _RULES_CACHE is not None:
        return _RULES_CACHE
    rules: list[DynamicRule] = []
    raw_all: list[dict] = []
    try:
        if _RULES_DIR.exists():
            for p in sorted(_RULES_DIR.glob("*.yaml")):
                try:
                    parsed = _load_yaml_text(p.read_text(encoding="utf-8"))
                    if parsed:
                        raw_all.extend(parsed)
                except Exception:
                    continue
    except Exception:
        raw_all = []
    if raw_all:
        rules = _build_rules(raw_all)
    else:
        rules = _build_rules(_BUILTIN_RULES)
    _RULES_CACHE = rules
    return rules


# ── 解析：按当前运行时上下文产出叠加层 ──

@dataclass
class RuntimeContext:
    """解析动态 overlay 所需的运行时上下文（不含角色卡原始字段）。

    stage_name：当前好感度档名（如「亲密」），用于 relation 类匹配。
    user_message：本轮用户消息，用于 narrative 类关键词匹配。
    first_active_date：角色（会话）首次活跃日期（ISO），time 类据此推算经过天数。
    now_date：当前日期（ISO），time 类按经过天数推移。
    共振项（resonance）：来自记忆层幂律复苏的临时心境文本（见 memory_decay_resonance）。
    """
    stage_name: str = ""
    user_message: str = ""
    first_active_date: str = ""
    now_date: str = ""
    resonance: list[str] = field(default_factory=list)


def resolve_dynamic_overlays(ctx: RuntimeContext) -> DynamicOverlay:
    """按运行时上下文产出动态叠加层（纯计算，不回写角色卡）。

    匹配规则：
    - time：自首次活跃经过天数 ≥ rule.min_days 时命中（年龄/年级增长节奏）。
    - relation：rule.trigger 等于当前 stage_name 时命中（取同 kind 最高优先级）。
    - narrative：user_message 命中 rule.trigger 通配模式时命中（可多条）。
    - 共振项：直接并入 texts（由记忆层复苏注入，不在此计算）。
    """
    rules = load_dynamics_rules()
    overlay = DynamicOverlay()

    # time 类：自首次活跃起经过足够天数触发年龄/年级增长（避免每轮触发）
    days_since = _days_between(ctx.first_active_date, ctx.now_date)
    if days_since is not None:
        for r in rules:
            if r.kind == "time" and r.overlay and days_since >= r.min_days:
                overlay.texts.append(r.overlay)
                overlay.applied_rule_ids.append(r.id)

    # relation 类：当前档名匹配，多命中取优先级最高
    best_rel: DynamicRule | None = None
    for r in rules:
        if r.kind == "relation" and r.trigger and r.trigger == ctx.stage_name and r.overlay:
            if best_rel is None or r.priority > best_rel.priority:
                best_rel = r
    if best_rel is not None:
        overlay.texts.append(best_rel.overlay)
        overlay.applied_rule_ids.append(best_rel.id)

    # narrative 类：用户消息关键词通配匹配（可多条）
    msg = ctx.user_message or ""
    for r in rules:
        if r.kind == "narrative" and r.trigger and r.overlay and msg:
            trigger = r.trigger.lower()
            lowered = msg.lower()
            if fnmatch.fnmatch(lowered, trigger) or trigger.strip("*") in lowered:
                overlay.texts.append(r.overlay)
                overlay.applied_rule_ids.append(r.id)

    # 记忆层幂律复苏的临时心境（由上游 memory_decay_resonance 计算注入）
    for rtext in (ctx.resonance or []):
        if rtext:
            overlay.texts.append(rtext)
            overlay.applied_rule_ids.append("memory_resonance")

    return overlay


def _days_between(first_iso: str, now_iso: str) -> int | None:
    """两日期（ISO）相隔整天数；任一为空或非法返回 None。"""
    if not first_iso or not now_iso:
        return None
    try:
        from datetime import date as _date
        first = _date.fromisoformat(first_iso)
        now = _date.fromisoformat(now_iso)
        return max(0, (now - first).days)
    except Exception:
        return None

"""安全护栏规则引擎（移植自 palm/_core/guardrail，适配 exo 语境）。

定位：权限闸门（标签集合）之外的「工具级精细裁决层」——按 trigger + 条件 AND
匹配规则，动作分 allow/deny/warn/ask 四元；无规则命中时按 5 档 Profile 兜底。

Profile 语义（mentalcore 适配版，默认 strict 完全兼容现有 fail-closed 行为）：
- hardline : ask→deny、warn→deny（最严，无确认通道即拒绝一切不确定）
- strict   : ask→deny、warn 保留（放行+告警）——默认档，权限闸门放行的工具照常执行
- loose    : ask→warn、warn 保留（宽松演示档）
- ai       : ask→deny（无 AI 回调即 fail-closed）、warn 保留
- whitelist: 仅 allow 规则放行，未命中一律 deny（白名单模式，显式开启才生效）

规则格式（与归档 rules.py 一致）：
  {id, trigger, conditions:[{field,op,value}...], action:"deny|ask|warn|allow",
   priority, enabled}
trigger 支持工具名（write_file/delete_file/run_shell/run_code/web_fetch/...）或
归档事件名（file.write/file.delete/process.execute/network.request）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Profile(str, Enum):
    """5 档策略：决定无规则命中（或 ask 无确认通道）时的兜底处置。"""

    HARDLINE = "hardline"
    STRICT = "strict"
    LOOSE = "loose"
    AI = "ai"
    WHITELIST = "whitelist"


# 工具名 → 归档事件名（便于复用归档规则文件的 trigger）
_TOOL_EVENT_MAP = {
    "read_file": "file.read", "write_file": "file.write", "append_file": "file.write",
    "copy_file": "file.write", "move_file": "file.write", "delete_file": "file.delete",
    "list_directory": "file.read", "get_file_info": "file.read",
    "search_files": "file.read", "file_hash": "file.read", "create_directory": "file.write",
    "run_shell": "process.execute", "run_code": "process.execute",
    "web_search": "network.request", "web_fetch": "network.request",
    "ask_user": "user.interaction", "automate": "gui.operate",
    "summarize": "compute.run", "danger_reset": "system.danger",
}


class _ConditionOp(str, Enum):
    eq = "eq"
    contains = "contains"
    startswith = "startswith"
    matches = "matches"
    gte = "gte"
    lt = "lt"
    in_op = "in"


@dataclass
class Condition:
    field: str
    op: str
    value: Any = None


@dataclass
class Rule:
    id: str
    trigger: str
    action: str                      # allow | deny | warn | ask
    conditions: list[Condition] = field(default_factory=list)
    priority: int = 50               # 越大越优先
    enabled: bool = True
    description: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "Rule":
        conds = [Condition(c.get("field", ""), c.get("op", "eq"), c.get("value"))
                 for c in (data.get("conditions") or [])]
        return cls(
            id=str(data["id"]), trigger=str(data["trigger"]),
            action=str(data.get("action", "deny")),
            conditions=conds,
            priority=int(data.get("priority", 50)),
            enabled=bool(data.get("enabled", True)),
            description=str(data.get("description", "")),
        )


def _eval_condition(actual: Any, cond: Condition) -> bool:
    """单条件求值；actual 缺省视为不匹配（fail-closed 方向）。"""
    if actual is None:
        return False
    try:
        op = _ConditionOp(cond.op)
    except ValueError:
        return False
    match op:
        case _ConditionOp.eq:
            return str(actual) == str(cond.value)
        case _ConditionOp.contains:
            return cond.value in str(actual)
        case _ConditionOp.startswith:
            return str(actual).startswith(str(cond.value))
        case _ConditionOp.matches:
            try:
                return bool(re.search(str(cond.value), str(actual)))
            except re.error:
                return False
        case _ConditionOp.gte:
            return float(actual) >= float(cond.value)
        case _ConditionOp.lt:
            return float(actual) < float(cond.value)
        case _ConditionOp.in_op:
            return str(actual) in list(cond.value or [])
    return False


def _match_event(trigger: str, event: str) -> bool:
    return trigger == event or trigger == _TOOL_EVENT_MAP.get(event)


class GuardRail:
    """护栏：规则匹配 + Profile 兜底；提供策略导出/热更新（对齐 GuardPort 契约）。"""

    # ask 无确认通道时的降级表（按 Profile）
    _ASK_FALLBACK = {
        Profile.HARDLINE: "deny", Profile.STRICT: "deny", Profile.LOOSE: "warn",
        Profile.AI: "deny", Profile.WHITELIST: "deny",
    }
    # warn 是否升级 deny（hardline 升级，其余保留）
    _WARN_UPGRADE = {Profile.HARDLINE}

    def __init__(self, profile: str | Profile = Profile.STRICT,
                 rules: list[Rule] | None = None):
        self.profile = profile if isinstance(profile, Profile) else Profile(profile)
        self._rules: list[Rule] = list(rules or [])

    @classmethod
    def profile_enum(cls, profile: str) -> Profile:
        """字符串档位 → Profile 枚举；非法档位抛 ValueError。"""
        return profile if isinstance(profile, Profile) else Profile(profile)

    # ── 策略管理（GuardPort：policies / set_policy 热更新）──────────
    def policies(self) -> list[dict]:
        return [{"id": r.id, "trigger": r.trigger, "action": r.action,
                 "conditions": [{"field": c.field, "op": c.op, "value": c.value}
                                for c in r.conditions],
                 "priority": r.priority, "enabled": r.enabled,
                 "description": r.description} for r in self._rules]

    def set_policy(self, policy: dict) -> None:
        """新增/替换一条规则；同 id 覆盖，非法动作抛 ValueError。"""
        rule = Rule.from_dict(policy)
        if rule.action not in ("allow", "deny", "warn", "ask"):
            raise ValueError(f"非法规则动作：{rule.action}")
        self._rules = [r for r in self._rules if r.id != rule.id] + [rule]

    def evaluate(self, event: str, ctx: dict) -> str:
        """裁决一次工具动作：返回 allow/deny/warn/ask（未命中按 Profile 兜底）。"""
        for rule in sorted((r for r in self._rules if r.enabled),
                           key=lambda r: r.priority, reverse=True):
            if not _match_event(rule.trigger, event):
                continue
            if all(_eval_condition(ctx.get(c.field), c) for c in rule.conditions):
                return self._resolve(rule.action)
        return self._fallback()

    def _resolve(self, action: str) -> str:
        if action == "allow":
            return "allow"
        if action == "deny":
            return "deny"
        if action == "warn":
            return "deny" if self.profile in self._WARN_UPGRADE else "warn"
        if action == "ask":
            return self._ASK_FALLBACK.get(self.profile, "deny")
        return "deny"

    def _fallback(self) -> str:
        # whitelist 档：未命中任何 allow 规则即拒绝；其余档位放行（交由权限闸门）
        if self.profile == Profile.WHITELIST:
            return "deny"
        return "allow"

    def load_yaml(self, path: str) -> int:
        """从 yaml 文件加载规则（字段对齐归档 rules.yaml）；返回加载条数。"""
        try:
            import yaml
        except ImportError:
            raise RuntimeError("加载规则 yaml 需要 pyyaml 依赖")
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        loaded = 0
        for item in data.get("rules", []) or []:
            item.setdefault("id", f"yaml_{loaded}")
            self.set_policy(item)
            loaded += 1
        return loaded

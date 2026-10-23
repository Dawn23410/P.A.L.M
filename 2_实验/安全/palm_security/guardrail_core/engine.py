"""统一安全护栏引擎（裁决引擎内核的继任者，去砖依赖）。

设计定位：
- 抽自原裁决引擎，仅依赖 palm_sdk.guardrail.rules（pydantic 模型）+ 标准库 + yaml，
  不反向依赖任何业务砖；归属砖（agent / 自主进化 / 网卡）一律经能力取用。
- 5 档策略（profile）控制「无规则命中时的默认处置」与「规则动作是否被升级」：
    死线 HARDLINE   : 默认拒绝；warn 升级为 deny（只允许显式 allow 规则）
    严格 STRICT     : 默认询问；warn 保持提醒
    宽松 LOOSE      : 默认提醒（放行 + advisory），不升级
    AI 兜底 AI      : 默认走 AI 回调（未配置则 fail-closed 拒绝）
    白名单 WHITELIST : 默认拒绝；仅 allow 规则可放行
- 规则匹配沿用 rules.py：按 priority 降序，首条命中规则生效；规则内条件 AND 组合。
- 与 execute_tool_with_safety 的 adjudicator_cap 接口对齐：
  get_guardrail_capability() 返回 (event_type, ctx) -> 带 blocked/action_type/ask_message/reason 的对象。
"""
from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

import yaml

from .rules import Rule, RulesConfig


# ── 5 档策略 ─────────────────────────────────────────────────────
class Profile(str, Enum):
    """策略档位：决定无规则命中时的兜底处置与动作升级规则。"""

    HARDLINE = "hardline"      # 死线
    STRICT = "strict"          # 严格
    LOOSE = "loose"            # 宽松
    AI = "ai"                  # AI 兜底
    WHITELIST = "whitelist"    # 白名单


PROFILE_LABELS: dict[Profile, str] = {
    Profile.HARDLINE: "死线",
    Profile.STRICT: "严格",
    Profile.LOOSE: "宽松",
    Profile.AI: "AI 兜底",
    Profile.WHITELIST: "白名单",
}


# ── 裁决结果 ─────────────────────────────────────────────────────
@dataclass
class Decision:
    """单次护栏裁决结果（与 adjudicator_cap 接口字段对齐）。"""

    action: str                       # allow / deny / ask / warn
    reason: str = ""
    rule: Rule | None = None
    ask_message: str = ""
    ask_timeout_ms: int = 30_000
    ask_on_timeout: str = "deny"

    @property
    def blocked(self) -> bool:
        """deny / ask 视为阻塞（等待期间不执行）。"""
        return self.action in ("deny", "ask")

    @property
    def action_type(self) -> str:
        return self.action


# ── 模板插值（供 ask / warn 文案引用上下文字段） ─────────────────
def _interpolate(template: str, context: dict) -> str:
    """将 {field} 替换为上下文值；支持 paths_preview / bytes_formatted 等派生字段。"""

    def _replacer(m: re.Match) -> str:
        key = m.group(1)
        if key == "paths_preview":
            paths = context.get("paths", context.get("path", ""))
            if isinstance(paths, list):
                preview = paths[:3]
                rest = len(paths) - 3
                suffix = f"…及其他 {rest} 个" if rest > 0 else ""
                return ", ".join(preview) + suffix
            return str(paths)
        if key == "bytes_formatted":
            return _format_bytes(context.get("bytes", 0))
        val = context.get(key, f"{{{key}}}")
        if isinstance(val, list):
            return ", ".join(str(v) for v in val[:5])
        return str(val)

    return re.sub(r"\{(\w+)\}", _replacer, template)


def _format_bytes(raw: Any) -> str:
    """字节数转人类可读格式。"""
    try:
        b = float(raw)
    except (TypeError, ValueError):
        return str(raw)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"


# ── 引擎 ─────────────────────────────────────────────────────────
class GuardrailEngine:
    """统一安全护栏引擎：规则评估 + 5 档策略兜底，线程安全。"""

    def __init__(self) -> None:
        self._rules: list[Rule] = []
        # 默认宽松：无规则命中即放行（advisory），不破坏既有「默认放行」行为。
        self._profile: Profile = Profile.LOOSE
        self._lock = threading.Lock()
        self._ai_adjudicator: Callable[[str, dict], Decision] | None = None

    # ── 档位与 AI 回调 ──────────────────────────────────────────
    def set_profile(self, profile: Profile | str) -> None:
        self._profile = Profile(profile)

    def get_profile(self) -> Profile:
        return self._profile

    def set_ai_adjudicator(self, fn: Callable[[str, dict], Decision]) -> None:
        """注入 AI 兜底裁决回调（由归属砖接入真实模型后端）。"""
        self._ai_adjudicator = fn

    # ── 规则管理 ────────────────────────────────────────────────
    def load_rules(self, source: RulesConfig | list[Rule]) -> None:
        rules = source.rules if isinstance(source, RulesConfig) else list(source)
        with self._lock:
            self._rules = list(rules)
            self._sort_rules()

    def load_defaults(self) -> None:
        """加载同目录下的 default_rules.yaml。"""
        path = os.path.join(os.path.dirname(__file__), "default_rules.yaml")
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        self.load_rules(RulesConfig(**raw))

    def add_rule(self, rule: Rule) -> None:
        with self._lock:
            self._rules.append(rule)
            self._sort_rules()

    def remove_rule(self, rule_id: str) -> bool:
        with self._lock:
            before = len(self._rules)
            self._rules = [r for r in self._rules if r.id != rule_id]
            return len(self._rules) < before

    def get_rules(self) -> list[Rule]:
        with self._lock:
            return list(self._rules)

    def validate_rule(self, rule: Rule) -> tuple[bool, str]:
        """校验规则合法性（前端创建/编辑时调用）。"""
        if not rule.id.strip():
            return False, "规则 ID 不能为空"
        if not rule.trigger.strip():
            return False, "必须指定触发的 AI 行为"
        if not rule.actions:
            return False, "必须指定至少一个执行行为"
        max_c = self.get_max_conditions(rule.trigger)
        if len(rule.conditions) > max_c:
            return False, (
                f"AI 行为「{rule.trigger}」最多允许 {max_c} 个条件（当前 {len(rule.conditions)} 个）"
            )
        for act in rule.actions:
            for key in act:
                if key not in ("ask", "warn", "deny", "allow"):
                    return False, f"不支持的执行行为：{key}"
        return True, ""

    # ── 核心裁决 ────────────────────────────────────────────────
    def evaluate(self, event: str, context: dict) -> Decision:
        """对给定事件 + 上下文执行全量规则匹配，无命中则按档位兜底。"""
        ctx = dict(context)
        ctx["_event"] = event
        with self._lock:
            rules = list(self._rules)
        for rule in rules:
            action = rule.evaluate(ctx)
            if action is None:
                continue
            return self._apply_rule(rule, action, ctx)
        return self._default_decision(event, ctx)

    def _apply_rule(self, rule: Rule, action: dict, ctx: dict) -> Decision:
        """规则命中：按动作类型生成裁决，并按档位决定是否升级 warn。"""
        atype = next(iter(action))
        if atype == "allow":
            return Decision("allow", rule=rule)
        if atype == "deny":
            return Decision("deny", "操作已被安全规则拒绝", rule=rule)
        if atype == "ask":
            msg = _build_ask_message(action, ctx)
            return Decision("ask", ask_message=msg, rule=rule)
        # warn：死线 / 白名单档位下升级为拒绝（只允许显式 allow）。
        if self._profile in (Profile.HARDLINE, Profile.WHITELIST):
            return Decision("deny", "策略档位禁止该操作（死线 / 白名单）", rule=rule)
        return Decision("warn", _build_warn_message(action, ctx), rule=rule)

    def _default_decision(self, event: str, ctx: dict) -> Decision:
        """无规则命中：按当前档位给出兜底裁决。"""
        if self._profile == Profile.HARDLINE:
            return Decision("deny", "死线策略：未命中放行规则即拒绝")
        if self._profile == Profile.WHITELIST:
            return Decision("deny", "白名单策略：未命中放行规则即拒绝")
        if self._profile == Profile.STRICT:
            return Decision("ask", ask_message="严格策略：需用户确认该操作")
        if self._profile == Profile.AI:
            if self._ai_adjudicator is not None:
                try:
                    return self._ai_adjudicator(event, ctx)
                except Exception:
                    return Decision("deny", "AI 兜底裁决异常，fail-closed 拒绝")
            return Decision("deny", "AI 兜底未配置，fail-closed 拒绝")
        # 宽松：放行 + 提醒（不阻塞），保持「默认放行」语义。
        return Decision("warn", "宽松策略：无规则命中，已放行（提醒）")

    def _sort_rules(self) -> None:
        """按 priority 降序排列（高优先先匹配）。"""
        self._rules.sort(key=lambda r: r.priority, reverse=True)

    # ── 前端适配元数据 ──────────────────────────────────────────
    @staticmethod
    def get_event_metadata() -> list[dict]:
        """返回受支持的 AI 行为元数据（供前端渲染下拉选择器）。"""
        return [
            {
                "event": "file.delete", "label": "删除文件",
                "description": "AI 删除文件或目录时触发",
                "max_conditions": 3, "default_max_conditions": 3,
                "fields": [
                    {"field": "count", "label": "删除数量", "value_type": "number"},
                    {"field": "path", "label": "目标路径", "value_type": "string"},
                    {"field": "paths", "label": "文件列表", "value_type": "list"},
                ],
            },
            {
                "event": "file.write", "label": "写入/修改文件",
                "description": "AI 创建、写入或修改文件时触发",
                "max_conditions": 3, "default_max_conditions": 3,
                "fields": [
                    {"field": "count", "label": "文件数量", "value_type": "number"},
                    {"field": "path", "label": "目标路径", "value_type": "string"},
                    {"field": "bytes", "label": "写入字节数", "value_type": "number"},
                ],
            },
            {
                "event": "process.execute", "label": "执行命令",
                "description": "AI 执行外部命令或脚本时触发",
                "max_conditions": 3, "default_max_conditions": 3,
                "fields": [
                    {"field": "count", "label": "命令数量", "value_type": "number"},
                    {"field": "command", "label": "命令内容", "value_type": "string"},
                    {"field": "commands", "label": "命令列表", "value_type": "list"},
                ],
            },
            {
                "event": "network.request", "label": "网络请求",
                "description": "AI 向外发送 HTTP 请求时触发",
                "max_conditions": 3, "default_max_conditions": 3,
                "fields": [
                    {"field": "url", "label": "目标 URL", "value_type": "string"},
                    {"field": "bytes", "label": "传输字节数", "value_type": "number"},
                    {"field": "is_external", "label": "是否外网", "value_type": "boolean"},
                ],
            },
            {
                "event": "batch.operation", "label": "批量操作",
                "description": "AI 批量执行重复操作时触发（兜底规则）",
                "max_conditions": 2, "default_max_conditions": 2,
                "fields": [
                    {"field": "count", "label": "操作次数", "value_type": "number"},
                    {"field": "operation", "label": "操作描述", "value_type": "string"},
                ],
            },
            {
                "event": "agent.proactive", "label": "主动推送",
                "description": "AI 在闲置/定时场景下主动向用户推送提案或提醒时触发",
                "max_conditions": 2, "default_max_conditions": 2,
                "fields": [
                    {"field": "source", "label": "推送来源", "value_type": "string"},
                ],
            },
        ]

    @staticmethod
    def get_operator_metadata() -> list[dict]:
        """返回条件算子元数据（供前端渲染条件编辑器）。"""
        return [
            {"op": "gte", "label": "≥（大于等于）", "value_type": "number", "group": "数值"},
            {"op": "gt", "label": ">（大于）", "value_type": "number", "group": "数值"},
            {"op": "eq", "label": "==（等于）", "value_type": "number", "group": "数值"},
            {"op": "lt", "label": "（小于）", "value_type": "number", "group": "数值"},
            {"op": "lte", "label": "≤（小于等于）", "value_type": "number", "group": "数值"},
            {"op": "matches", "label": "正则匹配", "value_type": "string", "group": "字符串"},
            {"op": "startswith", "label": "开头是", "value_type": "string", "group": "字符串"},
            {"op": "endswith", "label": "结尾是", "value_type": "string", "group": "字符串"},
            {"op": "contains", "label": "包含", "value_type": "string", "group": "字符串"},
            {"op": "not_startswith", "label": "开头不是", "value_type": "string", "group": "字符串"},
            {"op": "not_endswith", "label": "结尾不是", "value_type": "string", "group": "字符串"},
            {"op": "not_contains", "label": "不包含", "value_type": "string", "group": "字符串"},
            {"op": "in", "label": "属于集合", "value_type": "list", "group": "集合"},
            {"op": "not_in", "label": "不属于集合", "value_type": "list", "group": "集合"},
            {"op": "is_true", "label": "为真", "value_type": "boolean", "group": "布尔"},
            {"op": "is_false", "label": "为假", "value_type": "boolean", "group": "布尔"},
        ]

    @staticmethod
    def get_action_metadata() -> list[dict]:
        """返回响应动作元数据。"""
        return [
            {"action": "ask", "label": "询问", "description": "询问用户确认，超时可设降级行为", "needs_config": True},
            {"action": "warn", "label": "提醒", "description": "放行但记录告警日志", "needs_config": False},
            {"action": "deny", "label": "拒绝", "description": "直接拒绝操作并报错", "needs_config": True},
            {"action": "allow", "label": "允许", "description": "静默放行（白名单）", "needs_config": False},
        ]

    def get_max_conditions(self, event: str) -> int:
        """查询特定事件允许的最大条件数。"""
        for meta in self.get_event_metadata():
            if meta["event"] == event:
                return meta.get("max_conditions", meta.get("default_max_conditions", 5))
        return 5


# ── 内部辅助：从动作字典提取文案 ─────────────────────────────────
def _build_ask_message(action: dict, ctx: dict) -> str:
    """解析 ask 动作的提示文案（支持 str / dict / AskConfig 形态）。"""
    from .rules import AskConfig

    raw = action.get("ask", "")
    if isinstance(raw, AskConfig):
        cfg = raw
    elif isinstance(raw, dict):
        cfg = AskConfig(**raw)
    elif isinstance(raw, str):
        cfg = AskConfig(message=raw)
    else:
        cfg = AskConfig()
    return _interpolate(cfg.message, ctx)


def _build_warn_message(action: dict, ctx: dict) -> str:
    """从 warn 动作取首条字符串文案（插值上下文）。"""
    for v in action.values():
        if isinstance(v, str):
            return _interpolate(v, ctx)
    return ""


# ── 进程级默认引擎 + 能力适配 ───────────────────────────────────
_default_engine: GuardrailEngine | None = None


def get_default_engine() -> GuardrailEngine:
    """返回进程级默认引擎（惰性加载默认规则 + 档位取环境变量）。"""
    global _default_engine
    if _default_engine is None:
        eng = GuardrailEngine()
        env_profile = os.environ.get("PALM_GUARDRAIL_PROFILE", "loose")
        try:
            eng.set_profile(env_profile)
        except ValueError:
            eng.set_profile(Profile.LOOSE)
        try:
            eng.load_defaults()
        except Exception:
            pass
        _default_engine = eng
    return _default_engine


def get_guardrail_capability():
    """返回匹配 execute_tool_with_safety 的 adjudicator_cap 接口的可调用对象。

    签名：(event_type, ctx) -> Decision（含 blocked / action_type / ask_message / reason）。
    """
    eng = get_default_engine()

    def _cap(event_type: str, ctx: dict) -> Decision:
        return eng.evaluate(event_type, ctx)

    return _cap

"""供应商方言 Profile 与模型级 ModelRule（两级匹配的数据基础）。

两级匹配
--------
- **一级**（骨架层）：`cfg.type` ＞ 端点/域名特征 ＞ generic → `Profile`
- **二级**（模型层）：model id 正则 → `ModelRule`，**未命中回落 Profile 且不报错**

为什么规则是数据而不是类
------------------------
厂商月月上新型号，模型级差异（思考开关写法、档位枚举、禁参、固定参）变化频率远高于
协议骨架。做成数据后，新增供应商/模型只改 `profiles_data.py`，不会让 provider 类 O(N) 爆炸。

设计要点
--------
- **未命中一律回落**：厂商上新模型时硬报错会把新模型直接打死。
- **合并语义**：`ModelRule` 只对**非空字段**覆盖 `Profile`，其余继承。
- 规则须带 `as_of`，便于定期复审（档位会随厂商迭代变）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Optional

# 调用方可能用这些键表达"思考开关"，统一消费后翻译为目标写法
THINK_KEYS = ("think", "enable_thinking", "reasoning_effort", "thinking")


@dataclass(frozen=True)
class ModelRule:
    """模型级规则（二级匹配命中后生效）。"""

    pattern: str                              # 对 model.lower() 做 fullmatch
    priority: int = 0                         # 多条命中取最大
    as_of: str = ""                           # 规则取材日期
    # ── 思考语义（None = 继承 Profile）──
    thinking: Optional[str] = None            # always_on / always_off / toggle / unsupported
    thinking_param: Optional[str] = None      # thinking_type / enable_thinking / reasoning_effort / none
    # 协议自带的"思考强度 API 形态"（currently only Gemini 用）：level / budget / none。
    # 单独成一列而不是靠 forbid_params 反推 —— 反推是隐式耦合，改一处禁参会静默改掉判定。
    thinking_api: Optional[str] = None
    effort_allowed: Optional[tuple] = None
    effort_map: Optional[dict] = None
    # ── 参数卫生 ──
    forbid_params: tuple = ()                 # 传了会 400 → 剔除
    fixed_params: dict = field(default_factory=dict)   # 锁死值 → 覆盖
    # ── 能力 ──
    max_output: Optional[int] = None
    supports_vision: Optional[bool] = None
    doc_mimes: Optional[tuple] = None
    max_file_mb: Optional[float] = None
    # 思考块回传契约的模型级覆盖（同厂商不同代际可能相反，如 DeepSeek V4 vs legacy reasoner）
    needs_reasoning_echo: Optional[bool] = None
    # 该模型是否**不接受**强制工具选择（tool_choice=any/tool 会 400），只留 auto
    reject_forced_tool: Optional[bool] = None
    # 该模型是否**不原生吃文档**（如 GLM 文本系列，须先经文件解析服务转文本）。
    # 与 `doc_mimes` 的分工：`doc_mimes` 是"能吃哪些"，本字段是"一个都不吃"——
    # 后者无法用空元组表达（空元组在合并语义里等于"未声明"）。
    # None = 继承 Profile（Profile 默认 False）；显式 False 可把整家都拒文档的档位放开。
    reject_documents: Optional[bool] = None
    note: str = ""


@dataclass(frozen=True)
class Profile:
    """供应商级方言（一级匹配命中后生效）。"""

    name: str = "generic"
    reasoning_keys: tuple = ("reasoning_content", "reasoning")
    thinking_param: Optional[str] = None
    needs_reasoning_echo: bool = False        # 多轮是否必须回传思考块
    stop_semantics: str = "before"            # 混元是 "after"
    require_usage_option: bool = False
    vendor_params: dict = field(default_factory=dict)
    max_output: Optional[int] = None
    supports_vision: bool = False
    doc_mimes: tuple = ()
    max_file_mb: Optional[float] = None
    # 整家都不原生吃文档（须走各家独立的文件上传/解析 API）→ 发请求前拦掉。
    # 单条 ModelRule 可置 False 覆盖（如 GLM-5.3-Flash 原生支持文件）。
    reject_documents: bool = False
    # 该档位的能力矩阵是否可信。本机 ollama / generic 这类"模型名不固定"的档位填 False——
    # 矩阵不知道你拉了哪个模型，硬拦会把 llava 这类合法用法打死（见 capability.py 铁律 1）。
    capabilities_known: bool = True
    model_rules: tuple = ()


_MERGE_FIELDS = (
    "thinking_param", "max_output", "supports_vision", "doc_mimes",
    "max_file_mb", "needs_reasoning_echo", "stop_semantics",
    "require_usage_option", "vendor_params", "reasoning_keys",
    "reject_forced_tool", "reject_documents",
)


def resolve_provider(base_url: str = "", type_hint: str = "") -> Profile:
    """一级匹配：显式 type ＞ 端点/域名特征 ＞ generic。"""
    from .profiles_data import PROFILES, DOMAIN_HINTS

    if type_hint and type_hint in PROFILES:
        return PROFILES[type_hint]
    host = (base_url or "").lower()
    for frag, name in DOMAIN_HINTS:
        if frag in host:
            return PROFILES[name]
    return PROFILES["generic"]


def resolve_model(profile: Profile, model_id: str):
    """二级匹配：返回 (生效 Profile, 命中的 ModelRule 或 None)。

    未命中时原样返回 profile —— 不报错，行为等同现状。
    """
    name = (model_id or "").lower()
    for rule in sorted(profile.model_rules, key=lambda r: -r.priority):
        try:
            hit = re.fullmatch(rule.pattern, name)
        except re.error:
            continue
        if hit:
            return _merge(profile, rule), rule
    return profile, None


def apply_rule(payload: dict, profile: Profile, rule: Optional[ModelRule] = None) -> dict:
    """按规则做参数卫生与思考翻译。

    顺序很重要：先读调用方意图（并消费掉其原始写法）→ 剔禁参 → 写目标写法
    → **最后**套 fixed_params。若 fixed 先写，会被翻译逻辑当成"调用方意图"再消费一遍。
    """
    out = dict(payload)
    want: Optional[bool] = None
    effort: Optional[str] = None
    if profile.thinking_param:
        want, effort = _read_intent(out)
        if rule is not None and rule.thinking == "always_on" and want is False:
            want, effort = True, "low"      # 关不掉：降级为最低档（官方迁移指南口径）
        if rule is not None:
            effort = _clamp_effort(effort, rule)
    if rule is not None:
        for key in rule.forbid_params:
            out.pop(key, None)
        if rule.thinking != "unsupported":
            _write_thinking(out, profile.thinking_param, want, effort)
            # 开关与档位是两件事：目标写法只管开关，档位另写
            if effort and rule.effort_allowed:
                out["reasoning_effort"] = effort
        out.update(rule.fixed_params)
    if profile.vendor_params:
        out.update(profile.vendor_params)
    return out


def _merge(profile: Profile, rule: ModelRule) -> Profile:
    """ModelRule 的非空字段覆盖 Profile，其余继承。"""
    patch = {f: getattr(rule, f) for f in _MERGE_FIELDS if not _blank(getattr(rule, f, None))}
    return replace(profile, **patch) if patch else profile


def _blank(value) -> bool:
    return value is None or value in ((), {}, "")




def _read_intent(out: dict):
    """从 payload 里读出 (开/关意图, 档位)，并消费掉原始键。"""
    want: Optional[bool] = None
    effort: Optional[str] = None
    for key in THINK_KEYS:
        if key not in out:
            continue
        value = out.pop(key)
        if value is None:
            continue
        if key == "reasoning_effort" and isinstance(value, str):
            effort = value
            want = False if value == "none" else True
        elif isinstance(value, dict):
            kind = value.get("type")
            if kind == "disabled":
                want = False
            elif kind in ("enabled", "adaptive", "auto"):
                want = True
        elif isinstance(value, bool):
            want = value
    return want, effort


def _clamp_effort(effort: Optional[str], rule: ModelRule) -> Optional[str]:
    """档位先过映射表，再收敛到允许集合内。"""
    if not effort:
        return effort
    if rule.effort_map:
        effort = rule.effort_map.get(effort, effort)
    if rule.effort_allowed and effort not in rule.effort_allowed:
        return rule.effort_allowed[-1]
    return effort


def _write_thinking(out: dict, target: str, want: Optional[bool], effort: Optional[str]) -> None:
    if target == "thinking_type":
        out["thinking"] = {"type": "disabled" if want is False else "enabled"}
    elif target == "enable_thinking":
        out["enable_thinking"] = want is not False
    elif target == "reasoning_effort":
        out["reasoning_effort"] = effort or ("none" if want is False else "medium")

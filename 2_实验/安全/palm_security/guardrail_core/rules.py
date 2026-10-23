"""安全护栏规则数据模型（抽自裁决引擎，去砖依赖）。

规则格式：<AI行为><条件组合><执行行为>
  AI行为      : file.delete / file.write / process.execute / network.request / batch.operation
  条件组合    : 多个条件以 AND 逻辑组合；字段+算子+值自由搭配
  执行行为    : 询问 / 提醒 / 拒绝 / 允许

本模块为纯标准库 + pydantic，不依赖任何砖；归属砖的工具链预检经
palm_sdk.guardrail 复用本模型与 engine 的评估器。
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


# ── 条件算子 ──────────────────────────────────────────────────────

class ConditionOp(str, Enum):
    """条件算子枚举：覆盖数值、字符串、集合、布尔全场景。"""
    # 数值比较
    gte = "gte"    # >=
    gt = "gt"      # >
    eq = "eq"      # ==
    lt = "lt"      # <
    lte = "lte"    # <=
    # 字符串匹配
    matches = "matches"             # 正则匹配
    startswith = "startswith"
    endswith = "endswith"
    contains = "contains"
    not_startswith = "not_startswith"
    not_endswith = "not_endswith"
    not_contains = "not_contains"
    # 集合
    in_op = "in"                    # 值在集合中
    not_in = "not_in"               # 值不在集合中
    # 布尔
    is_true = "is_true"
    is_false = "is_false"


class Condition(BaseModel):
    """单条匹配条件：字段 + 算子 + 目标值（值类型随算子变化）。"""
    field: str
    op: ConditionOp
    # 目标值：数值、字符串、列表均可；布尔算子忽略此字段。
    value: Any | None = None
    # 条件不满足时的替代提示模板（可选）；留空则使用默认提示。
    label: str | None = None


# ── 响应动作 ──────────────────────────────────────────────────────

class AskConfig(BaseModel):
    """ask 动作的详细配置（超时、超时降级行为）。"""
    message: str = ""               # 确认提示模板，支持 {field} 插值
    timeout_ms: int = 30_000        # 等待用户确认的超时毫秒数
    on_timeout: Literal["deny", "allow", "warn"] = "deny"


ResponseAction = dict[Literal["ask", "deny", "allow", "warn"], str | AskConfig]
# 执行行为：
#   deny  - 拒绝：直接拒绝操作并报错
#   ask   - 询问：等待用户确认（可设超时降级）
#   warn  - 提醒：放行但记录告警
#   allow - 允许：静默放行（白名单）
# 注意：quarantine（隔离）设计时纳入但第一期不实现


class Rule(BaseModel):
    """单条安全裁决规则。

    所有条件以 AND 逻辑组合——全部满足才触发响应动作。
    优先级高的规则优先匹配（数字越大越优先）。
    """
    id: str
    description: str = ""
    enabled: bool = True
    priority: int = 50              # 0~100，越大越优先
    # 触发事件类型：如 file.delete / file.write / process.execute / network.request
    trigger: str
    conditions: list[Condition] = Field(default_factory=list)
    # 响应动作列表，按顺序尝试匹配（通常只有1个）。
    actions: list[ResponseAction] = Field(..., min_length=1)

    def evaluate(self, context: dict) -> ResponseAction | None:
        """检查上下文是否匹配此规则；全部条件满足返回对应响应，否则 None。"""
        if not self.enabled:
            return None
        # 事件类型先行匹配
        if context.get("_event") != self.trigger:
            return None
        for cond in self.conditions:
            actual = context.get(cond.field)
            if not _eval_condition(actual, cond):
                return None
        # 全部条件通过 → 返回第一条响应动作
        return self.actions[0]


def _eval_condition(actual: Any, cond: Condition) -> bool:
    """单条件求值。"""
    op = cond.op
    value = cond.value

    # 布尔类算子
    if op == ConditionOp.is_true:
        return bool(actual) is True
    if op == ConditionOp.is_false:
        return bool(actual) is False

    # 数值类算子
    if op in (ConditionOp.gte, ConditionOp.gt, ConditionOp.eq,
              ConditionOp.lt, ConditionOp.lte):
        try:
            a = float(actual) if actual is not None else float("-inf")
            v = float(value)
        except (TypeError, ValueError):
            return False
        match op:
            case ConditionOp.gte: return a >= v
            case ConditionOp.gt:  return a > v
            case ConditionOp.eq:  return a == v
            case ConditionOp.lt:  return a < v
            case ConditionOp.lte: return a <= v

    # 字符串类算子
    if actual is None:
        return False
    s = str(actual)
    match op:
        case ConditionOp.matches:
            import re
            try:
                return bool(re.search(str(value), s))
            except re.error:
                return False
        case ConditionOp.startswith:     return s.startswith(str(value))
        case ConditionOp.endswith:       return s.endswith(str(value))
        case ConditionOp.contains:       return str(value) in s
        case ConditionOp.not_startswith: return not s.startswith(str(value))
        case ConditionOp.not_endswith:   return not s.endswith(str(value))
        case ConditionOp.not_contains:   return str(value) not in s

    # 集合类算子
    match op:
        case ConditionOp.in_op:   return str(actual) in [str(v) for v in (value or [])]
        case ConditionOp.not_in:  return str(actual) not in [str(v) for v in (value or [])]

    return False


class RulesConfig(BaseModel):
    """整个规则文件的结构。"""
    version: int = 1
    rules: list[Rule]

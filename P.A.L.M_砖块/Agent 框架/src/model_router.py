"""模型路由：按任务复杂度在用户设定的 Pro/Flash 模型间路由。

设计要点（源自自主进化架构决策）：
- Pro=本地大模型，Flash=本地小模型；用户在模型界面自行设定，本地/网络均可，**零约束**（覆盖原「严禁第三方」）。
- 未设定对应档位时回退调用方默认模型（None），由 Agent 用请求自带 model。
- 降级：micro_reason 用 max_completion_tokens 把大模型压制成微型推理，省显存/低延迟。
"""
from __future__ import annotations

from palm_sdk.bricks.base import registry


def _load_settings() -> dict:
    # 经 settings 砖能力读取；缺砖/异常降级空字典。
    brick = registry.get("settings")
    if not brick:
        return {}
    fn = (getattr(brick, "capabilities", {}) or {}).get("load_app_settings")
    if not fn:
        return {}
    try:
        return fn() or {}
    except Exception:
        return {}


def resolve_model(tier: str) -> str | None:
    # tier="complex"→pro_model；tier="trivial"→flash_model；其余回退 None。
    s = _load_settings()
    if tier == "complex":
        return s.get("proModel") or None
    if tier == "trivial":
        return s.get("flashModel") or None
    return None


def select_model(tier: str, fallback: str | None = None) -> str | None:
    # 路由到用户设定模型；未设定则回退调用方默认模型。
    return resolve_model(tier) or fallback


def micro_reason(model: str | None, cap: int = 200) -> str | None:
    # 降级标识：返回带 max_completion_tokens 压制的模型标识（大模型当微型推理用）。
    # 当前 Agent 调用未透传该压制参数，故仅返回原模型；参数 cap 预留给后续接线。
    if not model:
        return None
    return model
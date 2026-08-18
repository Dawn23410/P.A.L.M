"""monitor 砖内部共享：经 settings 砖能力读取应用设置（零跨砖 import 依赖）。"""
from __future__ import annotations

from palm_sdk.bricks.base import registry


def load_settings() -> dict:
    # 经 settings 砖的 load_app_settings 能力读取；缺砖/异常降级空字典，绝不阻断调用方。
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
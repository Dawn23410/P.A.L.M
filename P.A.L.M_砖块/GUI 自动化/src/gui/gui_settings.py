"""GUI 工具组共享设置读取：中立模块，供 executor 与 automation 砖共用。

通过 registry 拿 settings 砖的 load_app_settings capability 读取用户设置，避免与各砖
形成模块级循环依赖（capability 解耦，运行时查找而非 import 时绑定）。
"""
from __future__ import annotations

import logging

from palm_sdk.bricks.base import registry

_LOGGER = logging.getLogger(__name__)
_SETTING_KEY = "gui_llm_enhance"


def is_llm_enhance_enabled() -> bool:
    """读取用户设置：是否允许 GUI LLM 增强（文本/视觉兜底）。默认关闭=纯逻辑模式。"""
    try:
        settings_brick = registry.get("settings")
        loader = (getattr(settings_brick, "capabilities", {}) or {}).get("load_app_settings")
        if callable(loader):
            return bool((loader() or {}).get(_SETTING_KEY, False))
    except Exception as exc:
        _LOGGER.warning("读取 gui_llm_enhance 失败，按关闭处理: %s", exc)
    return False
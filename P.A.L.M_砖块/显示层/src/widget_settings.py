"""每组件通用设置的合并与应用（Rainmeter 式：点击穿透 / 透明度 / 固定 / 置顶）。

配置存于 settings.widgets[widget_id]；此处只负责把"存储的配置"与"manifest 默认值"
合并，并把结果应用到原生窗（穿透/透明度/置顶）与 DOM（锁定禁拖拽）。
"""

import logging

from .win32_style import set_click_through, set_opacity, set_topmost

LOG = logging.getLogger("palm.wsettings")

BOOL_KEYS = ("clickThrough", "locked", "alwaysOnTop")


def default_widget_config(manifest):
    """从 manifest 取默认通用设置。"""
    return {
        "clickThrough": bool(manifest.get("clickThrough", False)),
        "opacity": 1.0,
        "locked": False,
        "alwaysOnTop": False,
    }


def merge_widget_config(stored, manifest):
    """存储值覆盖 manifest 默认值，并做类型收敛。"""
    cfg = default_widget_config(manifest)
    if not isinstance(stored, dict):
        return cfg
    for key in BOOL_KEYS:
        value = stored.get(key)
        if isinstance(value, bool):
            cfg[key] = value
    saved = stored.get("opacity")
    if isinstance(saved, (int, float)):
        cfg["opacity"] = min(1.0, max(0.0, float(saved)))
    return cfg


def apply_widget_native(window, cfg):
    """把通用设置应用到原生窗：点击穿透、透明度、保持最前。"""
    set_click_through(window, bool(cfg.get("clickThrough")))
    set_opacity(window, float(cfg.get("opacity", 1.0)))
    set_topmost(window, bool(cfg.get("alwaysOnTop", True)))


def apply_widget_lock(window, cfg):
    """锁定：给 body 加 locked 类，shim 据此禁用拖拽并隐藏拖拽把手。"""
    verb = "add" if cfg.get("locked") else "remove"
    try:
        window.evaluate_js(f"document.body.classList.{verb}('locked')")
    except Exception:
        pass

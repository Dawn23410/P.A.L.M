"""后台接触式采集（只读 UIA 树，不干扰、不截图、不降级 OCR）。

设计约束（点⑧）：
- 仅在用户空闲 / 已知窗口聚焦时被动运行（频率由调用方控制，本模块只做单次扫描）；
- 只读枚举 UIA 树（build_uia_tree_progressive），不抢焦点、不点击、不截图、不 OCR；
- 硬性约束：拿不到 UIA 树（Electron/纯画布等）直接不扫，绝不降级 OCR——
  因为 OCR 要截图，既侵入又可能捕获敏感内容，与「接触式/不干扰」矛盾；
- 扫到的树蒸馏进 Atlas（derive_and_merge），补坐标/结构（fail-soft）。

与反向建图分工：本模块成功扫到 UIA 树时走蒸馏（源更准）；扫不到时由调用方
决定是否启用 reverse_builder（被动长周期预热）。本模块自身不调 reverse_builder。
"""
from __future__ import annotations

import logging

_LOGGER = logging.getLogger(__name__)


def _is_idle() -> bool:
    """极简空闲判定：最近无键鼠输入（GetLastInputInfo）。非空闲时调用方不应触发扫描。"""
    try:
        import ctypes
        class _LASTINPUT(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
        li = _LASTINPUT()
        li.cbSize = ctypes.sizeof(li)
        if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(li)):
            import time
            idle_ms = (ctypes.windll.kernel32.GetTickCount() - li.dwTime) & 0xFFFFFFFF
            return idle_ms > 30000  # 空闲 >30s 才视为可后台扫描
    except Exception:
        pass
    return False


def background_scan_once(hwnd: int | None = None, max_nodes: int = 800) -> dict:
    """单次接触式扫描：只读 UIA 树并蒸馏进 Atlas。失败/不可扫返回 scanned=False。

    hwnd 为空取前台窗口（调用方应先判空闲）。Electron 等禁用 UIA 的窗口直接跳过，
    绝不降级 OCR（符合硬约束）。
    """
    try:
        from .desktop_control import is_electron_app, get_window_exe
        from .perceive import build_uia_tree_progressive
        if hwnd is None:
            import uiautomation as auto
            hwnd = auto.GetForegroundControl().NativeWindowHandle
        if not hwnd:
            return {"scanned": False, "reason": "no_hwnd"}
        if is_electron_app(hwnd):
            # 禁用 UIA 遍历（防 ntdll）；不降级 OCR，直接不扫
            return {"scanned": False, "reason": "electron_skip"}
        tree = build_uia_tree_progressive(hwnd, max_nodes=max_nodes, max_rescan=0)
        if not tree or tree.get("node_count", 0) == 0:
            # 拿不到 UIA 树：直接不扫，绝不降级 OCR
            return {"scanned": False, "reason": "no_uia"}
        try:
            from .world_model_cache import derive_and_merge
            model = {"meta": {"hwnd": hwnd,
                              "title": (get_window_exe(hwnd) or "")},
                     "uia_tree": tree["tree"]}
            derive_and_merge(model)
        except Exception as atlas_err:
            _LOGGER.warning("后台扫描 Atlas 蒸馏失败（不阻塞）: %s", atlas_err)
        return {"scanned": True, "nodes": tree.get("node_count", 0),
                "late_loaded": tree.get("late_loaded_count", 0),
                "software_id": get_window_exe(hwnd) or "unknown"}
    except Exception as exc:
        _LOGGER.warning("后台接触式扫描异常（不阻塞）: %s", exc)
        return {"scanned": False, "reason": str(exc)[:60]}


def maybe_background_scan(hwnd: int | None = None) -> dict:
    """空闲判定 + 单次扫描的组合入口（供自动化砖/守护调用）。"""
    if not _is_idle() and hwnd is None:
        return {"scanned": False, "reason": "not_idle"}
    return background_scan_once(hwnd)

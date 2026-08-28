"""常驻点击采集（无感、不干扰、不 OCR、自绘可适配）。

设计目标：在用户真实操作（非自动化）时被动记录「点哪了 + 起了什么作用」，
全程不抢焦点、不截图、不读文字。作用 = 点击前后界面/系统状态的**结构化 diff**
（标题变化 / 焦点窗口切换），天然不依赖 OCR，也能吃到自绘窗口的外壳层事件。

零 LLM 依赖；记录全部为无 LLM 推理服务。数据先入内存池，由 atlas_calibration
攒够阈值后统一聚合（聚合计算，非高频）。

采集钩子：ctypes WH_MOUSE_LL 低级鼠标钩子（捕获所有左键按下，自绘窗口也能记），
后台守护线程跑消息泵使其触发；失败 fail-soft，不阻断主流程。
"""
from __future__ import annotations

import ctypes
import logging
import threading
import time

_LOGGER = logging.getLogger(__name__)

_user32 = ctypes.windll.user32 if hasattr(ctypes, "windll") else None

# 点击池：内存中攒批，供校准器统一聚合（攒够阈值或空闲触发，避免高频）
_click_pool: list[dict] = []
_pool_lock = threading.Lock()
_MAX_POOL = 200  # 内存上限，超出即丢弃最旧（校准器应及时 drain）

WH_MOUSE_LL = 14
WM_LBUTTONDOWN = 0x0201


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", _POINT), ("mouseData", ctypes.c_ulong),
                ("flags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.c_void_p)]


_hook_proc = None
_hook_handle = None
_pump_thread = None
_running = False


def _screen_metrics() -> dict:
    """读取分辨率/DPI/缩放（相对窗口坐标的元数据，非绝对坐标）。"""
    if not _user32:
        return {"resolution": (0, 0), "dpi": 96, "scale": 1.0}
    cx = _user32.GetSystemMetrics(0)
    cy = _user32.GetSystemMetrics(1)
    try:
        dpi = _user32.GetDpiForSystem()
    except Exception:
        dpi = 96
    return {"resolution": (cx, cy), "dpi": dpi, "scale": round(dpi / 96.0, 3)}


def _relative_from_abs(hwnd: int, abs_x: int, abs_y: int):
    """屏幕绝对坐标相对指定窗口客户区归一化（无绝对坐标落盘）。"""
    if not _user32:
        return None
    class _RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
    rect = _RECT()
    if not _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    w = max(rect.right - rect.left, 1)
    h = max(rect.bottom - rect.top, 1)
    nx, ny = (abs_x - rect.left) / w, (abs_y - rect.top) / h
    if not (0.0 <= nx <= 1.0 and 0.0 <= ny <= 1.0):
        return None
    return (nx, ny)


def _relative_point(hwnd: int):
    """鼠标实时屏幕位置相对窗口归一化（executor 内调用分支）。"""
    if not _user32:
        return None
    class _RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
    rect = _RECT()
    if not _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    class _POINT2(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
    pt = _POINT2()
    if not _user32.GetCursorPos(ctypes.byref(pt)):
        return None
    w = max(rect.right - rect.left, 1)
    h = max(rect.bottom - rect.top, 1)
    nx, ny = (pt.x - rect.left) / w, (pt.y - rect.top) / h
    if not (0.0 <= nx <= 1.0 and 0.0 <= ny <= 1.0):
        return None
    return (nx, ny)


def _window_meta(hwnd: int) -> dict:
    """窗口元数据（类名/标题/exe 标识），不含 OCR 文本。"""
    meta = {"hwnd": hwnd, "window_class": "", "window_title": "", "proc": ""}
    try:
        import uiautomation as auto
        ctrl = auto.ControlFromHandle(hwnd)
        if ctrl:
            meta["window_class"] = ctrl.ClassName or ""
            meta["window_title"] = (ctrl.Name or "")[:60]
            meta["proc"] = ctrl.ProcessId or 0
    except Exception:
        pass
    return meta


_last_title: dict[int, str] = {}
_last_foreground: dict[int, int] = {}


def _effect_diff(hwnd: int, meta: dict) -> dict:
    """作用 diff：比对标题变化与焦点窗口切换（极轻，无 UIA 子树遍历、无 OCR）。

    自绘窗口若冒不出子控件事件，标题/焦点仍可能变（窗口切换、标题变化），
    部分信息可得；若都不变则 effect=none（已知局限，与设计一致）。
    """
    title = meta.get("window_title", "")
    prev_title = _last_title.get(hwnd)
    _last_title[hwnd] = title
    if prev_title is not None and title and title != prev_title:
        return {"type": "window_title_changed", "changed_region": (0.5, 0.1),
                "target": title}
    try:
        fg = _user32.GetForegroundWindow() if _user32 else 0
    except Exception:
        fg = 0
    prev_fg = _last_foreground.get(hwnd)
    _last_foreground[hwnd] = fg
    if prev_fg is not None and fg and fg != prev_fg:
        return {"type": "window_switched", "changed_region": (0.5, 0.5),
                "target": fg}
    return {"type": "none", "changed_region": None, "target": None}


def record_click(hwnd: int, nx: float | None = None, ny: float | None = None,
                 abs_x: int | None = None, abs_y: int | None = None) -> dict | None:
    """记录一次点击到内存池（供钩子与 executor 共用）。

    落库 ClickRecord：相对坐标 + 缩放/分辨率 + 极低单次置信 + 结构化无文本作用签名。
    优先用 abs 坐标（钩子现场），否则从鼠标实时位置推算（executor 分支）。
    """
    if not hwnd:
        return None
    if nx is None or ny is None:
        rp = _relative_from_abs(hwnd, abs_x, abs_y) if abs_x is not None else None
        if rp is None:
            rp = _relative_point(hwnd)
        if rp is None:
            return None
        nx, ny = rp
    meta = _window_meta(hwnd)
    metrics = _screen_metrics()
    rec = {
        "ts": time.time(),
        "hwnd": hwnd,
        "window_class": meta["window_class"],
        "window_title": meta["window_title"],
        "proc": meta["proc"],
        "rel_pos": (round(nx, 4), round(ny, 4)),
        "scale": metrics["scale"],
        "dpi": metrics["dpi"],
        "resolution": metrics["resolution"],
        "effect": _effect_diff(hwnd, meta),
        "confidence": 0.05,  # 单次置信极低，靠聚合才可信
    }
    with _pool_lock:
        _click_pool.append(rec)
        if len(_click_pool) > _MAX_POOL:
            _click_pool.pop(0)
    return rec


def drain_click_pool() -> list[dict]:
    """取出并清空点击池（校准器攒够阈值时调用，统一聚合计算）。"""
    with _pool_lock:
        out = list(_click_pool)
        _click_pool.clear()
    return out


def click_pool_size() -> int:
    with _pool_lock:
        return len(_click_pool)


def _low_level_mouse_proc(n_code, w_param, l_param):
    """WH_MOUSE_LL 回调：捕获左键按下，记录前台窗口内的相对点击。"""
    if n_code >= 0 and w_param == WM_LBUTTONDOWN and _user32:
        try:
            hs = _MSLLHOOKSTRUCT.from_address(l_param)
            hwnd = _user32.GetForegroundWindow()
            record_click(int(hwnd), abs_x=hs.pt.x, abs_y=hs.pt.y)
        except Exception:
            pass
    if _hook_handle:
        return _user32.CallNextHookEx(_hook_handle, n_code, w_param, l_param)
    return 0


def _pump() -> None:
    """消息泵：保持低级钩子回调触发（无泵则钩子不派发）。"""
    msg = ctypes.wintypes.MSG()
    while _running:
        ret = _user32.MsgWaitForMultipleObjects(0, None, 0, 100, 0x04FF)  # QS_ALLINPUT
        if ret in (0, 0xFFFFFFFF):
            continue
        while _user32.PeekMessageW(ctypes.byref(msg), 0, 0, 0, 0x0001):  # PM_REMOVE
            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))


def start_click_collector() -> bool:
    """安装后台点击采集钩子（WH_MOUSE_LL + 消息泵线程）。失败返回 False，不阻断主流程。"""
    global _hook_proc, _hook_handle, _pump_thread, _running
    if _hook_handle:
        return True
    if not _user32:
        return False
    try:
        hk = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int,
                                ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM)
        _hook_proc = hk(_low_level_mouse_proc)
        _hook_handle = _user32.SetWindowsHookExW(WH_MOUSE_LL, _hook_proc, None, 0)
        if not _hook_handle:
            return False
        _running = True
        _pump_thread = threading.Thread(target=_pump, daemon=True)
        _pump_thread.start()
        _LOGGER.info("点击采集钩子(WH_MOUSE_LL)已安装")
        return True
    except Exception as exc:
        _LOGGER.warning("点击采集钩子安装失败（不影响 executor 内记录）: %s", exc)
        return False


def stop_click_collector() -> None:
    """卸载点击采集钩子。"""
    global _hook_handle, _running
    _running = False
    if _hook_handle and _user32:
        try:
            _user32.UnhookWindowsHookEx(_hook_handle)
        except Exception:
            pass
        _hook_handle = None

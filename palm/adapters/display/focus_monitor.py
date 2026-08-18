"""专注模式：检测前台全屏窗口，自动隐藏/恢复桌面组件。

实现要点：
- 仅 Windows 用 ctypes 调 user32 比对前台窗口与主监视器尺寸；其他平台/失败时安全降级（不隐藏）。
- 守护线程每 0.5s 轮询一次，仅在「是否全屏」状态翻转时回调，避免每帧抖动。
- 是否启用由外部 getter 实时读取（设置项可热切换）。
"""

import logging
import threading
import time

try:
    import ctypes
    from ctypes import wintypes
    _HAS_WIN32 = True
except Exception:  # 非 Windows 或 ctypes 缺失
    _HAS_WIN32 = False

LOG = logging.getLogger("palm.focus")


def is_foreground_fullscreen():
    """前台窗口覆盖几乎整个主监视器即判为全屏。"""
    if not _HAS_WIN32:
        return False
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return False
        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return False
        screen_w = user32.GetSystemMetrics(0)   # SM_CXSCREEN
        screen_h = user32.GetSystemMetrics(1)   # SM_CYSCREEN
        win_w = rect.right - rect.left
        win_h = rect.bottom - rect.top
        # 容差 4px：覆盖主屏即视为全屏（游戏/全屏视频）。
        return win_w >= screen_w - 4 and win_h >= screen_h - 4
    except Exception:
        return False


class FocusMonitor:
    """后台轮询前台全屏状态，翻转时通知宿主隐藏/恢复组件。"""

    def __init__(self, on_fullscreen_change):
        self._on_change = on_fullscreen_change
        self._enabled_getter = lambda: True
        self._running = False
        self._is_fullscreen = False
        self._thread = None

    def start(self, enabled_getter):
        self._enabled_getter = enabled_getter
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _poll_loop(self):
        while self._running:
            try:
                enabled = self._enabled_getter()
                full = is_foreground_fullscreen() if enabled else False
                if full != self._is_fullscreen:
                    self._is_fullscreen = full
                    self._on_change(full)
            except Exception:
                pass
            time.sleep(0.5)

"""原生窗控制：点击穿透、透明度、置顶（仅 Windows 生效，跨平台安全降级）。

为什么需要：CSS 的 pointer-events 只能让 HTML 元素不接收鼠标，但操作系统窗口
仍会在命中测试时吃掉点击，导致"点击穿透"名存实亡。要真正穿透到桌面，必须给
原生窗加 WS_EX_TRANSPARENT（点击穿透）与 WS_EX_LAYERED（透明分层，透明度的前提）。
"""

import logging
import platform

try:
    import ctypes
    from ctypes import wintypes
    _AVAILABLE = platform.system() == "Windows"
except Exception:  # 非 Windows 或 ctypes 缺失
    _AVAILABLE = False

LOG = logging.getLogger("palm.win32")

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x80000
WS_EX_TRANSPARENT = 0x20
LWA_ALPHA = 0x2
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
HWND_BOTTOM = 1
SWP_NOMOVE = 0x2
SWP_NOSIZE = 0x1
SWP_NOZORDER = 0x4
SWP_FRAMECHANGED = 0x20


def get_hwnd(window):
    """从 pywebview Window 取原生句柄，失败返回 None。

    pywebview 6.x（WinForms 后端）把原生窗存在 window.native（WinForms.Form），
    HWND 即 window.native.Handle；旧版曾用 window.hwnd / window._native_window，
    这里三种都试，跨版本兜底。
    """
    native = getattr(window, "native", None)
    if native is not None:
        handle = getattr(native, "Handle", None)
        if handle is not None:
            try:
                return int(handle)
            except (TypeError, ValueError):
                pass
    for attr in ("hwnd", "_native_window"):
        val = getattr(window, attr, None)
        if val:
            try:
                return int(val)
            except (TypeError, ValueError):
                pass
    return None


def enum_child_hwnds(hwnd):
    """枚举某窗的所有子窗句柄（含 WebView2 浏览器控件）。"""
    children = []
    if not hwnd:
        return children
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
    try:
        user32 = ctypes.windll.user32

        def _callback(child, _):
            children.append(child)
            return True

        user32.EnumChildWindows(hwnd, callback_type(_callback), 0)
    except Exception as exc:  # 枚举失败不应阻断主流程
        LOG.warning("枚举子窗失败：%s", exc)
    return children


def _set_ex_style(hwnd, bits, on):
    user32 = ctypes.windll.user32
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    style = style | bits if on else style & ~bits
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
    # 改扩展样式后必须重设窗口（SWP_FRAMECHANGED）才能让命中测试/视觉重新生效，
    # 否则 WS_EX_TRANSPARENT 不会真正改变点击行为。
    user32.SetWindowPos(
        hwnd, 0, 0, 0, 0, 0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED,
    )
    return style


def set_click_through(window, enabled):
    """开启：父窗与 WebView2 子控件均加 WS_EX_LAYERED|WS_EX_TRANSPARENT（穿透到桌面）。

    仅给父窗设不够——WebView2 浏览器控件是盖在窗体上的子 HWND，会在命中测试时
    吃掉点击；必须把子控件一并设为透明，点击才能真正落到桌面。关闭时仅去除
    TRANSPARENT（透明度仍由 set_opacity 在之后重加 WS_EX_LAYERED 维持）。
    """
    if not _AVAILABLE:
        return False
    hwnd = get_hwnd(window)
    if not hwnd:
        return False
    try:
        bits = WS_EX_LAYERED | WS_EX_TRANSPARENT
        on = bool(enabled)
        _set_ex_style(hwnd, bits, on)
        for child in enum_child_hwnds(hwnd):
            _set_ex_style(child, WS_EX_TRANSPARENT, on)
        return True
    except Exception as exc:
        LOG.warning("设置点击穿透失败：%s", exc)
        return False


def set_opacity(window, alpha):
    """alpha 0~1：经 WS_EX_LAYERED + SetLayeredWindowAttributes 设置窗口透明度。"""
    if not _AVAILABLE:
        return False
    hwnd = get_hwnd(window)
    if not hwnd:
        return False
    try:
        user32 = ctypes.windll.user32
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        style |= WS_EX_LAYERED
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        value = int(max(0.0, min(1.0, float(alpha))) * 255)
        user32.SetLayeredWindowAttributes(hwnd, 0, value, LWA_ALPHA)
        return True
    except Exception as exc:
        LOG.warning("设置透明度失败：%s", exc)
        return False


def set_topmost(window, enabled):
    """置顶 / 取消置顶。"""
    if not _AVAILABLE:
        return False
    hwnd = get_hwnd(window)
    if not hwnd:
        return False
    try:
        user32 = ctypes.windll.user32
        flag = HWND_TOPMOST if enabled else HWND_NOTOPMOST
        user32.SetWindowPos(hwnd, flag, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)
        return True
    except Exception as exc:
        LOG.warning("设置置顶失败：%s", exc)
        return False


def set_bottommost(window):
    """将窗口置于 z-order 最底层（壁纸窗专用）。

    HWND_BOTTOM 会把窗口发送到所有非顶层窗口的最下方，仅高于桌面图标层。
    配合 WS_EX_TRANSPARENT 实现壁纸窗的全屏穿透 + 置底。
    """
    if not _AVAILABLE:
        return False
    hwnd = get_hwnd(window)
    if not hwnd:
        return False
    try:
        user32 = ctypes.windll.user32
        user32.SetWindowPos(hwnd, HWND_BOTTOM, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE)
        return True
    except Exception as exc:
        LOG.warning("设置置底失败：%s", exc)
        return False


def get_screen_size():
    """返回主监视器分辨率 (width, height)，用于壁纸窗全屏。"""
    if not _AVAILABLE:
        return (1920, 1080)
    try:
        user32 = ctypes.windll.user32
        return (user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))
    except Exception:
        return (1920, 1080)

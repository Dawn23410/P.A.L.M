"""窗口管理工具 + 键鼠同步原语（Windows 桌面自动化增强）。

设计目标：
- 零依赖优先：直接用 ctypes 调 user32.dll / gdi32.dll，不依赖第三方库。
- pygetwindow 作为可选 fallback（装了更好，但不强依赖）。
- 失败一律返回错误文本字符串，绝不抛异常崩溃 Agent。
- 同步原语（wait_for_window / wait_for_pixel）用 asyncio.sleep 轮询，不阻塞事件循环。

工具清单（permission="desktop.control", event_type="desktop.control"）：
  窗口管理：list_windows / focus_window / get_active_window / get_window_rect
            minimize_window / maximize_window / restore_window / close_window
  同步原语：wait_for_window / wait_for_pixel / wait_seconds
"""
from __future__ import annotations

import asyncio
import logging
import sys

from ..tool_base import Tool, ToolSpec

_LOGGER = logging.getLogger(__name__)

# ── 平台与依赖检查 ──────────────────────────────────────
_IS_WINDOWS = sys.platform == "win32"
_HAS_CTYPES_WIN = False
_HAS_PYGETWINDOW = False

# ctypes + wintypes 仅在 Windows 上加载
if _IS_WINDOWS:
    try:
        import ctypes
        from ctypes import wintypes
        _HAS_CTYPES_WIN = True
    except Exception:  # noqa: BLE001
        pass

try:
    import pygetwindow as _gw  # 可选 fallback
    _HAS_PYGETWINDOW = True
except ImportError:
    pass


# ── Win32 常量 ──────────────────────────────────────────
SW_MINIMIZE = 6
SW_MAXIMIZE = 3
SW_RESTORE = 9
SW_SHOW = 5
WM_CLOSE = 0x0010
KEYEVENTF_KEYUP = 0x0002
VK_MENU = 0x12  # Alt 键
CLR_INVALID = 0xFFFFFFFF


# ── Win32 函数原型绑定（一次性，避免 64 位指针截断） ────
def _setup_winapi() -> None:
    """绑定 user32/gdi32 函数原型。仅在 Windows 上执行一次。"""
    if not _HAS_CTYPES_WIN:
        return
    u = ctypes.windll.user32
    g = ctypes.windll.gdi32

    # 枚举 / 状态
    u.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
    u.EnumWindows.restype = wintypes.BOOL
    u.IsWindowVisible.argtypes = [wintypes.HWND]
    u.IsWindowVisible.restype = wintypes.BOOL
    u.IsWindow.argtypes = [wintypes.HWND]
    u.IsWindow.restype = wintypes.BOOL
    u.IsIconic.argtypes = [wintypes.HWND]
    u.IsIconic.restype = wintypes.BOOL
    u.IsZoomed.argtypes = [wintypes.HWND]
    u.IsZoomed.restype = wintypes.BOOL

    # 标题
    u.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    u.GetWindowTextLengthW.restype = ctypes.c_int
    u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    u.GetWindowTextW.restype = ctypes.c_int

    # 位置
    u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    u.GetWindowRect.restype = wintypes.BOOL
    u.MoveWindow.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_int,
                             ctypes.c_int, ctypes.c_int, wintypes.BOOL]
    u.MoveWindow.restype = wintypes.BOOL

    # 前台 / 显示 / 关闭
    u.GetForegroundWindow.argtypes = []
    u.GetForegroundWindow.restype = wintypes.HWND
    u.SetForegroundWindow.argtypes = [wintypes.HWND]
    u.SetForegroundWindow.restype = wintypes.BOOL
    u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    u.ShowWindow.restype = wintypes.BOOL
    u.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                               wintypes.WPARAM, wintypes.LPARAM]
    u.PostMessageW.restype = wintypes.BOOL
    u.BringWindowToTop.argtypes = [wintypes.HWND]
    u.BringWindowToTop.restype = wintypes.BOOL

    # 像素
    u.GetDC.argtypes = [wintypes.HWND]
    u.GetDC.restype = wintypes.HDC
    u.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    u.ReleaseDC.restype = ctypes.c_int
    g.GetPixel.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    g.GetPixel.restype = wintypes.COLORREF

    # keybd_event（用于绕过前台锁的 Alt 技巧）
    u.keybd_event.argtypes = [ctypes.c_uint8, ctypes.c_uint8,
                              ctypes.c_uint32, ctypes.c_size_t]
    u.keybd_event.restype = None


_setup_winapi()

# WNDENUMPROC 回调类型（模块级，保持类型对象存活）
if _HAS_CTYPES_WIN:
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
else:  # 非 Windows 占位，避免引用未定义名
    WNDENUMPROC = None


# ════════════════════════════════════════════════════════
#  Win32 底层封装（同步函数，返回结构化数据或 None）
# ════════════════════════════════════════════════════════

def _win_error(msg: str) -> str:
    """统一错误前缀，便于 AI 识别。"""
    return f"[window_tools] {msg}"


def _get_window_title(hwnd: int) -> str:
    """获取窗口标题，失败返回空串。"""
    if not _HAS_CTYPES_WIN:
        return ""
    u = ctypes.windll.user32
    length = u.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    u.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def _get_window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    """获取窗口 (x, y, w, h)，失败返回 None。"""
    if not _HAS_CTYPES_WIN:
        return None
    u = ctypes.windll.user32
    rect = wintypes.RECT()
    if not u.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    return (rect.left, rect.top,
            rect.right - rect.left, rect.bottom - rect.top)


def enum_visible_windows() -> list[dict] | None:
    """枚举所有可见且有标题的顶级窗口。

    返回 list[dict]，每项含 hwnd/title/x/y/w/h/is_foreground；
    非 Windows 或 ctypes 不可用时返回 None。
    """
    if not _HAS_CTYPES_WIN:
        return None
    u = ctypes.windll.user32
    fg = u.GetForegroundWindow()
    results: list[dict] = []

    def _callback(hwnd, _lparam):
        if not u.IsWindowVisible(hwnd):
            return True  # 跳过不可见，继续枚举
        title = _get_window_title(hwnd)
        if not title:
            return True  # 跳过空标题
        rect = _get_window_rect(hwnd)
        if rect is None:
            return True
        x, y, w, h = rect
        results.append({
            "hwnd": int(hwnd),
            "title": title,
            "x": x, "y": y, "w": w, "h": h,
            "is_foreground": int(hwnd) == int(fg),
        })
        return True

    u.EnumWindows(WNDENUMPROC(_callback), 0)
    return results


def find_windows_by_title(keyword: str) -> list[dict] | None:
    """按标题关键词（大小写不敏感子串匹配）查找窗口。

    返回匹配的窗口 dict 列表（同 enum_visible_windows 结构）；
    不可用时返回 None，无匹配返回空列表。
    """
    all_wins = enum_visible_windows()
    if all_wins is None:
        return None
    kw = keyword.lower()
    return [w for w in all_wins if kw in w["title"].lower()]


def resolve_hwnd(hwnd=None, title=None) -> tuple[int, str, str]:
    """解析窗口句柄。

    优先用 hwnd（整数），其次 title 关键词模糊匹配（取首个匹配）。
    成功返回 (hwnd_int, matched_title, "")；
    失败返回 (0, "", error_msg)。
    """
    if not _HAS_CTYPES_WIN:
        return 0, "", _win_error("非 Windows 平台或 ctypes 不可用")
    u = ctypes.windll.user32

    if hwnd:
        try:
            h = int(hwnd)
        except (TypeError, ValueError):
            return 0, "", _win_error(f"无效的窗口句柄: {hwnd!r}")
        if not u.IsWindow(h):
            return 0, "", _win_error(f"句柄 {h} 不是有效窗口")
        return h, _get_window_title(h), ""

    if title:
        matches = find_windows_by_title(title)
        if matches is None:
            return 0, "", _win_error("窗口枚举不可用")
        if not matches:
            return 0, "", _win_error(f"未找到标题包含「{title}」的窗口")
        w0 = matches[0]
        return w0["hwnd"], w0["title"], ""

    return 0, "", _win_error("需提供 hwnd 或 title 参数")


def set_foreground(hwnd: int) -> bool:
    """把窗口切到前台（含绕过前台锁的 Alt 键技巧 + 最小化先恢复）。"""
    if not _HAS_CTYPES_WIN:
        return False
    u = ctypes.windll.user32
    # 若最小化则先恢复，否则无法切前台
    if u.IsIconic(hwnd):
        u.ShowWindow(hwnd, SW_RESTORE)
    # Alt 键技巧：模拟一次 Alt 按放，绕过 SetForegroundWindow 的前台锁定
    u.keybd_event(VK_MENU, 0, 0, 0)
    u.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
    u.BringWindowToTop(hwnd)
    return bool(u.SetForegroundWindow(hwnd))


def get_pixel_color(x: int, y: int) -> tuple[int, int, int] | None:
    """获取屏幕坐标 (x, y) 的像素颜色 (r, g, b)。

    GetPixel 返回 COLORREF（0x00BBGGRR），需转换为 RGB。
    坐标越界返回 None。
    """
    if not _HAS_CTYPES_WIN:
        return None
    u = ctypes.windll.user32
    g = ctypes.windll.gdi32
    hdc = u.GetDC(0)  # 0 = 整个屏幕的 DC
    if not hdc:
        return None
    try:
        colorref = g.GetPixel(hdc, int(x), int(y))
    finally:
        u.ReleaseDC(0, hdc)
    if colorref == CLR_INVALID:
        return None
    r = colorref & 0xFF
    g_val = (colorref >> 8) & 0xFF
    b = (colorref >> 16) & 0xFF
    return (r, g_val, b)


def _parse_color(text: str) -> tuple[int, int, int] | None:
    """解析颜色字符串为 (r,g,b)；支持 #RRGGBB / RRGGBB / #RGB。无法解析返回 None。"""
    if not text:
        return None
    s = text.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6:
        return None
    try:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except ValueError:
        return None


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#%02X%02X%02X" % rgb


# ════════════════════════════════════════════════════════
#  窗口管理工具
# ════════════════════════════════════════════════════════

class ListWindowsTool(Tool):
    """列出所有可见顶级窗口。"""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="list_windows",
            description="列出当前所有可见的顶级窗口（标题/句柄/位置x,y,w,h/是否前台）。"
                        "自动过滤空标题与不可见窗口。用于了解桌面有哪些窗口可操作。",
            parameters={"type": "object", "properties": {}, "required": []},
            permission="desktop.control",
            event_type="desktop.control",
        )

    async def execute(self, **kwargs) -> str:
        if not _HAS_CTYPES_WIN:
            return _win_error("非 Windows 平台或 ctypes 不可用，无法枚举窗口")
        try:
            wins = await asyncio.to_thread(enum_visible_windows)
        except Exception as e:  # noqa: BLE001
            return _win_error(f"枚举窗口异常: {e}")
        if wins is None:
            return _win_error("窗口枚举不可用")
        if not wins:
            return "当前没有可见且带标题的窗口"
        lines = [f"共 {len(wins)} 个可见窗口:"]
        for w in wins:
            mark = " *" if w["is_foreground"] else ""
            lines.append(
                f"  [{w['hwnd']}] {w['title'][:60]}"
                f" | 位置({w['x']},{w['y']}) {w['w']}x{w['h']}{mark}"
            )
        lines.append("（* = 当前前台窗口）")
        return "\n".join(lines)


class FocusWindowTool(Tool):
    """按标题关键词切换窗口到前台并激活。"""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="focus_window",
            description="按标题关键词（模糊匹配，大小写不敏感）切换窗口到前台并激活。"
                        "若窗口处于最小化状态会先恢复。用于在多窗口间切换焦点后再输入/点击。",
            parameters={"type": "object", "properties": {
                "title": {"type": "string", "description": "窗口标题关键词，如 '记事本'/'Chrome'"},
            }, "required": ["title"]},
            permission="desktop.control",
            event_type="desktop.control",
        )

    async def execute(self, title: str = "") -> str:
        if not title:
            return "未提供窗口标题关键词"
        if not _HAS_CTYPES_WIN:
            # pygetwindow fallback
            if _HAS_PYGETWINDOW:
                return await self._gw_focus(title)
            return _win_error("非 Windows 平台或 ctypes 不可用")
        try:
            hwnd, matched, err = await asyncio.to_thread(resolve_hwnd, None, title)
        except Exception as e:  # noqa: BLE001
            return _win_error(f"查找窗口异常: {e}")
        if err:
            return err
        try:
            ok = await asyncio.to_thread(set_foreground, hwnd)
        except Exception as e:  # noqa: BLE001
            return _win_error(f"激活窗口异常: {e}")
        if ok:
            return f"已激活窗口「{matched}」（句柄 {hwnd}）"
        return _win_error(f"激活窗口「{matched}」失败（可能被系统前台锁阻止）")

    async def _gw_focus(self, title: str) -> str:
        try:
            wins = _gw.getWindowsWithTitle(title)
        except Exception as e:  # noqa: BLE001
            return _win_error(f"pygetwindow 查找异常: {e}")
        if not wins:
            return _win_error(f"未找到标题包含「{title}」的窗口")
        try:
            wins[0].activate()
            return f"已激活窗口「{wins[0].title}」（pygetwindow）"
        except Exception as e:  # noqa: BLE001
            return _win_error(f"激活窗口失败: {e}")


class GetActiveWindowTool(Tool):
    """返回当前前台窗口信息。"""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="get_active_window",
            description="返回当前前台（活动）窗口的标题、句柄、位置与大小。"
                        "用于确认当前焦点在哪个窗口，再决定后续操作。",
            parameters={"type": "object", "properties": {}, "required": []},
            permission="desktop.control",
            event_type="desktop.control",
        )

    async def execute(self, **kwargs) -> str:
        if not _HAS_CTYPES_WIN:
            return _win_error("非 Windows 平台或 ctypes 不可用")
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            title = _get_window_title(hwnd)
            rect = _get_window_rect(hwnd)
        except Exception as e:  # noqa: BLE001
            return _win_error(f"获取前台窗口异常: {e}")
        if not hwnd:
            return "当前没有前台窗口"
        if rect:
            x, y, w, h = rect
            return f"前台窗口: 「{title}」| 句柄 {hwnd} | 位置({x},{y}) {w}x{h}"
        return f"前台窗口: 「{title}」| 句柄 {hwnd} | 位置获取失败"


class GetWindowRectTool(Tool):
    """按句柄或标题关键词获取窗口位置大小。"""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="get_window_rect",
            description="按窗口句柄(hwnd)或标题关键词(title)获取窗口的位置与大小(x,y,w,h)。"
                        "hwnd 与 title 二选一，优先 hwnd。",
            parameters={"type": "object", "properties": {
                "hwnd": {"type": "integer", "description": "窗口句柄（与 title 二选一）"},
                "title": {"type": "string", "description": "窗口标题关键词（与 hwnd 二选一）"},
            }, "required": []},
            permission="desktop.control",
            event_type="desktop.control",
        )

    async def execute(self, hwnd: int | None = None, title: str = "") -> str:
        if not _HAS_CTYPES_WIN:
            return _win_error("非 Windows 平台或 ctypes 不可用")
        try:
            h, matched, err = await asyncio.to_thread(resolve_hwnd, hwnd, title or None)
        except Exception as e:  # noqa: BLE001
            return _win_error(f"查找窗口异常: {e}")
        if err:
            return err
        rect = _get_window_rect(h)
        if rect is None:
            return _win_error(f"获取窗口「{matched}」位置失败")
        x, y, w, h2 = rect
        return f"窗口「{matched}」(句柄 {h}) | 位置({x},{y}) 大小 {w}x{h2}"


class _WindowShowTool(Tool):
    """最小化/最大化/恢复的共用基类（不直接注册）。"""
    _action: str = ""        # minimize / maximize / restore
    _cmd: int = SW_RESTORE   # ShowWindow 命令
    _verb: str = "操作"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self._action,
            description=f"{self._verb}指定窗口（按标题关键词或句柄）。"
                        "hwnd 与 title 二选一，优先 hwnd。",
            parameters={"type": "object", "properties": {
                "hwnd": {"type": "integer", "description": "窗口句柄（与 title 二选一）"},
                "title": {"type": "string", "description": "窗口标题关键词（与 hwnd 二选一）"},
            }, "required": []},
            permission="desktop.control",
            event_type="desktop.control",
        )

    async def execute(self, hwnd: int | None = None, title: str = "") -> str:
        if not _HAS_CTYPES_WIN:
            return _win_error("非 Windows 平台或 ctypes 不可用")
        try:
            h, matched, err = await asyncio.to_thread(resolve_hwnd, hwnd, title or None)
        except Exception as e:  # noqa: BLE001
            return _win_error(f"查找窗口异常: {e}")
        if err:
            return err
        try:
            ok = await asyncio.to_thread(
                ctypes.windll.user32.ShowWindow, h, self._cmd)
        except Exception as e:  # noqa: BLE001
            return _win_error(f"{self._verb}异常: {e}")
        if ok:
            return f"已{self._verb}窗口「{matched}」（句柄 {h}）"
        return _win_error(f"{self._verb}窗口「{matched}」失败")


class MinimizeWindowTool(_WindowShowTool):
    _action = "minimize_window"
    _cmd = SW_MINIMIZE
    _verb = "最小化"


class MaximizeWindowTool(_WindowShowTool):
    _action = "maximize_window"
    _cmd = SW_MAXIMIZE
    _verb = "最大化"


class RestoreWindowTool(_WindowShowTool):
    _action = "restore_window"
    _cmd = SW_RESTORE
    _verb = "恢复"


class CloseWindowTool(Tool):
    """关闭指定窗口（按标题关键词或句柄）。"""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="close_window",
            description="关闭指定窗口（按标题关键词或句柄）。"
                        "通过发送 WM_CLOSE 消息请求窗口正常关闭（非强杀进程）。"
                        "hwnd 与 title 二选一，优先 hwnd。",
            parameters={"type": "object", "properties": {
                "hwnd": {"type": "integer", "description": "窗口句柄（与 title 二选一）"},
                "title": {"type": "string", "description": "窗口标题关键词（与 hwnd 二选一）"},
            }, "required": []},
            permission="desktop.control",
            event_type="desktop.control",
        )

    async def execute(self, hwnd: int | None = None, title: str = "") -> str:
        if not _HAS_CTYPES_WIN:
            return _win_error("非 Windows 平台或 ctypes 不可用")
        try:
            h, matched, err = await asyncio.to_thread(resolve_hwnd, hwnd, title or None)
        except Exception as e:  # noqa: BLE001
            return _win_error(f"查找窗口异常: {e}")
        if err:
            return err
        try:
            ok = await asyncio.to_thread(
                ctypes.windll.user32.PostMessageW, h, WM_CLOSE, 0, 0)
        except Exception as e:  # noqa: BLE001
            return _win_error(f"关闭窗口异常: {e}")
        if ok:
            return f"已向窗口「{matched}」（句柄 {h}）发送关闭消息"
        return _win_error(f"关闭窗口「{matched}」失败")


# ════════════════════════════════════════════════════════
#  键鼠同步原语（让桌面自动化从"盲操作"变"可靠"）
# ════════════════════════════════════════════════════════

class WaitForWindowTool(Tool):
    """等待某标题关键词的窗口出现或消失，带超时轮询。"""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="wait_for_window",
            description="等待标题包含某关键词的窗口出现(appear)或消失(disappear)，带超时。"
                        "轮询间隔 0.3 秒，默认超时 10 秒。"
                        "用于等待应用启动完成、弹窗出现/关闭后再继续操作，避免盲操作。"
                        "返回是否成功及实际等待时长。",
            parameters={"type": "object", "properties": {
                "title": {"type": "string", "description": "窗口标题关键词"},
                "mode": {"type": "string", "enum": ["appear", "disappear"],
                         "default": "appear", "description": "appear=等待出现，disappear=等待消失"},
                "timeout": {"type": "number", "default": 10, "description": "超时秒数"},
                "interval": {"type": "number", "default": 0.3, "description": "轮询间隔秒数"},
            }, "required": ["title"]},
            permission="desktop.control",
            event_type="desktop.control",
        )

    async def execute(self, title: str = "", mode: str = "appear",
                      timeout: float = 10.0, interval: float = 0.3) -> str:
        if not title:
            return "未提供窗口标题关键词"
        if not _HAS_CTYPES_WIN:
            return _win_error("非 Windows 平台或 ctypes 不可用")
        want_appear = mode != "disappear"
        interval = max(0.05, float(interval))
        deadline = asyncio.get_event_loop().time() + float(timeout)
        start = asyncio.get_event_loop().time()
        last_checked = False

        while True:
            try:
                matches = await asyncio.to_thread(find_windows_by_title, title)
            except Exception as e:  # noqa: BLE001
                return _win_error(f"轮询查找窗口异常: {e}")
            if matches is None:
                return _win_error("窗口枚举不可用")
            found = len(matches) > 0
            last_checked = found

            if want_appear and found:
                elapsed = asyncio.get_event_loop().time() - start
                return (f"成功：窗口「{matches[0]['title'][:50]}」已出现，"
                        f"等待 {elapsed:.2f} 秒")
            if (not want_appear) and (not found):
                elapsed = asyncio.get_event_loop().time() - start
                return f"成功：标题包含「{title}」的窗口已消失，等待 {elapsed:.2f} 秒"

            if asyncio.get_event_loop().time() >= deadline:
                elapsed = asyncio.get_event_loop().time() - start
                verb = "出现" if want_appear else "消失"
                state = "未出现" if want_appear else "仍存在"
                return (f"超时：等待 {elapsed:.1f} 秒后，标题包含「{title}」"
                        f"的窗口{state}（未{verb}）")
            await asyncio.sleep(interval)


class WaitForPixelTool(Tool):
    """等待指定坐标像素颜色变为目标值（或发生变化），带超时轮询。"""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="wait_for_pixel",
            description="等待屏幕指定坐标(x,y)的像素颜色变为目标值(target_color，如 #FF0000)"
                        "或发生变化（不传 target_color 则等待颜色变化）。"
                        "默认超时 10 秒，轮询间隔 0.3 秒。"
                        "用于等待按钮变色/加载完成/状态指示灯变化后再操作。"
                        "返回是否成功及实际颜色。",
            parameters={"type": "object", "properties": {
                "x": {"type": "integer", "description": "像素 x 坐标"},
                "y": {"type": "integer", "description": "像素 y 坐标"},
                "target_color": {"type": "string", "description": "目标颜色(#RRGGBB)，不传则等待颜色变化"},
                "timeout": {"type": "number", "default": 10, "description": "超时秒数"},
                "interval": {"type": "number", "default": 0.3, "description": "轮询间隔秒数"},
            }, "required": ["x", "y"]},
            permission="desktop.control",
            event_type="desktop.control",
        )

    async def execute(self, x: int = -1, y: int = -1, target_color: str = "",
                      timeout: float = 10.0, interval: float = 0.3) -> str:
        if x < 0 or y < 0:
            return "未指定像素坐标，请提供 x 与 y"
        if not _HAS_CTYPES_WIN:
            return _win_error("非 Windows 平台或 ctypes 不可用")

        target = _parse_color(target_color) if target_color else None
        if target_color and target is None:
            return f"无法解析目标颜色「{target_color}」，请用 #RRGGBB 格式"

        interval = max(0.05, float(interval))
        loop = asyncio.get_event_loop()
        deadline = loop.time() + float(timeout)
        start = loop.time()

        # 变化模式：记录初始颜色
        initial = await asyncio.to_thread(get_pixel_color, x, y)
        if initial is None:
            return _win_error(f"无法读取坐标({x},{y})的像素（可能越界）")

        if target is not None and initial == target:
            elapsed = loop.time() - start
            return (f"成功：像素({x},{y})颜色已是目标 {_rgb_to_hex(initial)}，"
                    f"等待 {elapsed:.2f} 秒")

        while True:
            await asyncio.sleep(interval)
            try:
                cur = await asyncio.to_thread(get_pixel_color, x, y)
            except Exception as e:  # noqa: BLE001
                return _win_error(f"读取像素异常: {e}")
            if cur is None:
                return _win_error(f"无法读取坐标({x},{y})的像素（可能越界）")

            if target is not None:
                if cur == target:
                    elapsed = loop.time() - start
                    return (f"成功：像素({x},{y})颜色变为 {_rgb_to_hex(cur)}，"
                            f"等待 {elapsed:.2f} 秒")
            else:
                # 变化模式：与初始颜色不同即成功
                if cur != initial:
                    elapsed = loop.time() - start
                    return (f"成功：像素({x},{y})颜色由 {_rgb_to_hex(initial)} "
                            f"变为 {_rgb_to_hex(cur)}，等待 {elapsed:.2f} 秒")

            if loop.time() >= deadline:
                elapsed = loop.time() - start
                if target is not None:
                    return (f"超时：等待 {elapsed:.1f} 秒，像素({x},{y})颜色仍为 "
                            f"{_rgb_to_hex(cur)}（目标 {_rgb_to_hex(target)}）")
                return (f"超时：等待 {elapsed:.1f} 秒，像素({x},{y})颜色未变化"
                        f"（当前 {_rgb_to_hex(cur)}）")


class WaitSecondsTool(Tool):
    """简单等待 N 秒（让 AI 显式声明等待）。"""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="wait_seconds",
            description="等待指定秒数后返回。让 AI 显式声明等待（比盲目连续操作更可靠），"
                        "适用于等待动画/过渡/加载等无法用 wait_for_window/wait_for_pixel 精确判断的场景。",
            parameters={"type": "object", "properties": {
                "seconds": {"type": "number", "default": 1, "description": "等待秒数"},
            }, "required": ["seconds"]},
            permission="desktop.control",
            event_type="desktop.control",
        )

    async def execute(self, seconds: float = 1.0) -> str:
        if seconds <= 0:
            return "等待秒数需大于 0"
        seconds = min(seconds, 300)  # 上限保护，避免 AI 误传超大值
        await asyncio.sleep(seconds)
        return f"已等待 {seconds} 秒"


# ── 注册列表 ───────────────────────────────────────────

WINDOW_TOOLS = [
    ListWindowsTool,
    FocusWindowTool,
    GetActiveWindowTool,
    GetWindowRectTool,
    MinimizeWindowTool,
    MaximizeWindowTool,
    RestoreWindowTool,
    CloseWindowTool,
    WaitForWindowTool,
    WaitForPixelTool,
    WaitSecondsTool,
]

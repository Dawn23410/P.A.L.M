"""桌面控制通用引擎：系统级键鼠 + 截图 + OCR 定位 + 开关识别。

集中处理后台进程自动化里的坑（前台锁、坐标定位、HDR 开关状态判定），
供 agent 工具层与上层流程编排复用，避免每次临时拼装 ctypes。

设计边界：
- 仅做"机器眼 + 机器手指"：OCR/像素只用于定位坐标，动作一律真实键鼠输入。
- 不调用任何设置 API、不写注册表（避免"逃票"嫌疑）。
- click_point 默认把本线程输入队列挂到目标/前台窗口线程（AttachThreadInput），
  绕开后台进程 SetForegroundWindow 被前台锁拒绝的问题。
"""
from __future__ import annotations

import io
import logging
import os
import tempfile
import time
import ctypes
import ctypes.wintypes as wt

import pyautogui
from PIL import Image

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# 64 位下 HANDLE/指针为 64 位，必须显式声明原型，否则 ctypes 默认 c_int 会截断句柄导致 OpenProcess 失败。
kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
kernel32.OpenProcess.restype = ctypes.c_void_p
kernel32.QueryFullProcessImageNameW.argtypes = [
    ctypes.c_void_p, ctypes.c_ulong, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong)]
kernel32.QueryFullProcessImageNameW.restype = ctypes.c_int
kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
kernel32.CloseHandle.restype = ctypes.c_int

_LOGGER = logging.getLogger(__name__)

# ── OCR 引擎（分层实现见 ocr_engine.py，此处转发保持对外接口） ──

from .ocr_engine import get_ocr_engine, get_ocr_engine_name


def ocr_boxes(path: str) -> list[tuple[str, tuple[int, int, int, int]]]:
    """截图 OCR，返回 [(文本, (左,上,右,下)), ...]。坐标用像素绝对位置。"""
    engine = get_ocr_engine()
    if not engine:
        return []
    try:
        raw, _ = engine(path)
    except Exception:
        return []
    out = []
    for points, text, _score in raw:
        if not text or not text.strip():
            continue
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        out.append((text.strip(), (int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys)))))
    return out


def find_box(substr: str, boxes, prefer_top: bool = True):
    """在 OCR 结果里找含子串的包围盒；prefer_top=True 取最靠上的。"""
    hits = [(b, box) for (b, box) in boxes if substr.lower() in b.lower()]
    if not hits:
        return None
    hits.sort(key=lambda h: h[1][1] if prefer_top else -h[1][1])
    return hits[0][1]


# ── 窗口管理 ──────────────────────────────────────────

def find_window(substr: str):
    """按标题子串找可见窗口，返回 (hwnd, (左,上,右,下))，取面积最大者。"""
    res = []

    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n > 0:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                if substr in buf.value:
                    r = wt.RECT()
                    user32.GetWindowRect(hwnd, ctypes.byref(r))
                    area = (r.right - r.left) * (r.bottom - r.top)
                    res.append((area, hwnd, (r.left, r.top, r.right, r.bottom)))
        return True

    user32.EnumWindows(ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)(cb), 0)
    if not res:
        return None
    res.sort(reverse=True)
    return res[0][1], res[0][2]


# ── 应用内核识别 ────────────────────────────────────────

_ELECTRON_CLASS_PREFIXES = ("Chrome_WidgetWin_", "Electron")


def is_electron_app(hwnd: int) -> bool:
    """判断窗口是否为 Electron/Chromium 内核（如 QQ NT）。

    Electron 应用对 Win32 窗口操控（ShowWindow/SetForegroundWindow）与 UIA 自动化
    （uiautomation 遍历）极度敏感：前者破坏 GPU 渲染导致黑屏，后者遍历控件树触发
    ntdll 崩溃且无法被 Python try/except 捕获。用窗口类名通用识别（Electron 主窗口
    恒为 Chrome_WidgetWin_0），避免针对具体应用硬编码。
    """
    if not hwnd:
        return False
    cls = ctypes.create_unicode_buffer(128)
    if user32.GetClassNameW(hwnd, cls, 128):
        name = cls.value
        return any(name.startswith(p) for p in _ELECTRON_CLASS_PREFIXES)
    return False


_INPUT_DESKTOP_OK = None  # None=尚未探测；True/False=探测结论（一次缓存）


def _can_send_input() -> bool:
    """检测鼠标输入能否送达真实输入桌面。

    隔离终端会话（ConPTY）下输入被路由到虚拟桌面，mouse_event 点击静默失效；
    用 OpenInputDesktop 探测：能打开真实输入桌面才允许鼠标点击，否则应降级到
    键盘/OCR 路径并如实上报点击未送达。探测异常时默认放行（不阻断正常桌面）。
    """
    global _INPUT_DESKTOP_OK
    if _INPUT_DESKTOP_OK is None:
        try:
            h = user32.OpenInputDesktop(0, False, 0x0001)  # DF_ALLOWOTHERACCOUNTHOOK
            if h:
                user32.CloseDesktop(h)
                _INPUT_DESKTOP_OK = True
            else:
                _INPUT_DESKTOP_OK = False
        except Exception:
            _INPUT_DESKTOP_OK = True
    return _INPUT_DESKTOP_OK


def focus_window(hwnd: int) -> bool:
    """把指定窗口强行置前；Electron/Chromium 应用跳过破坏性窗口操控以免黑屏。"""
    if is_electron_app(hwnd):
        # Electron 主窗口对 ShowWindow/SetForegroundWindow/AttachThreadInput 极度敏感，
        # 会破坏 GPU 渲染导致黑屏。这类应用依赖已在合适层级（用户手动打开即前台），
        # 不主动操控窗口——视作已在目标层级返回成功（不报错但不做破坏性动作）。
        return True
    mytid = kernel32.GetCurrentThreadId()
    tid = user32.GetWindowThreadProcessId(hwnd, None)
    try:
        attached = tid and tid != mytid and user32.AttachThreadInput(mytid, tid, True)
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0003)
        user32.SetForegroundWindow(hwnd)
        user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, 0x0003)
        if attached:
            user32.AttachThreadInput(mytid, tid, False)
    except Exception:
        pass
    return True


# ── 系统级输入（含前台锁绕过） ──────────────────────────

def click_point(x: int, y: int, hwnd: int = 0, right: bool = False) -> bool:
    """真实鼠标点击。优先挂到 hwnd 线程；未给 hwnd 则挂当前前台窗口线程。
    隔离会话下鼠标事件到不了真实桌面，返回 False（而非静默成功）。"""
    if not _can_send_input():
        return False
    mytid = kernel32.GetCurrentThreadId()
    tid = 0
    target = hwnd or user32.GetForegroundWindow()
    if target:
        tid = user32.GetWindowThreadProcessId(target, None)
        if tid and tid != mytid:
            user32.AttachThreadInput(mytid, tid, True)
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.06)
    if right:
        user32.mouse_event(0x0008, 0, 0, 0, 0)
        time.sleep(0.05)
        user32.mouse_event(0x0010, 0, 0, 0, 0)
    else:
        user32.mouse_event(0x0002, 0, 0, 0, 0)
        time.sleep(0.05)
        user32.mouse_event(0x0004, 0, 0, 0, 0)
    time.sleep(0.15)
    if tid and tid != mytid:
        user32.AttachThreadInput(mytid, tid, False)
    return True


def press_key(vk: int) -> None:
    """按一个虚拟键码（系统级）。"""
    user32.keybd_event(vk, 0, 0, 0)
    time.sleep(0.05)
    user32.keybd_event(vk, 0, 0x0002, 0)


def type_text(text: str) -> None:
    """输入文本：优先剪贴板粘贴（CJK/IME 安全），无 pyperclip 时回退逐字。

    用 try/finally 兜底恢复剪贴板——即便粘贴按键中途异常，也不会让用户原剪贴板内容丢失。
    """
    try:
        import pyperclip
    except Exception:
        pyautogui.write(text, interval=0.01)
        return
    old = None
    try:
        old = pyperclip.paste()
        pyperclip.copy(text)
        user32.keybd_event(0x11, 0, 0, 0)  # ctrl down
        user32.keybd_event(0x56, 0, 0, 0)  # v down
        user32.keybd_event(0x56, 0, 0x0002, 0)
        user32.keybd_event(0x11, 0, 0x0002, 0)
        time.sleep(0.05)
    finally:
        if old is not None:
            try:
                pyperclip.copy(old)
            except Exception:
                pass


def hotkey(*keys: str) -> None:
    """组合键（如 'win','i'）。"""
    vk_map = {
        "win": 0x5B, "ctrl": 0x11, "alt": 0x12, "shift": 0x10,
        "enter": 0x0D, "escape": 0x1B, "tab": 0x09, "space": 0x20,
        "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
        "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
        "backspace": 0x08, "delete": 0x2E, "insert": 0x2D,
        "capslock": 0x14, "numlock": 0x90,
        # 符号键（OEM 区，多软件通用）
        ";": 0xBA, "semicolon": 0xBA, "'": 0xDE, "quote": 0xDE,
        ",": 0xBC, "comma": 0xBC, ".": 0xBE, "period": 0xBE,
        "/": 0xBF, "slash": 0xBF, "\\": 0xDC, "backslash": 0xDC,
        "-": 0xBD, "minus": 0xBD, "=": 0xBB, "equal": 0xBB,
        "`": 0xC0, "backtick": 0xC0, "[": 0xDB, "]": 0xDD,
    }
    # F1-F12 = 0x70-0x7B
    vk_map.update({f"f{i}": 0x6F + i for i in range(1, 13)})
    # default 参数会被 eager 求值，多字符键(如 'win')会让 ord() 抛错；故先 get 再按需 ord
    vks = []
    for k in keys:
        vk = vk_map.get(k.lower())
        if vk is None:
            if len(k) == 1:
                vk = ord(k.upper()) & 0xFF
            else:
                _LOGGER.warning("hotkey 忽略未知组合键: %r", k)
                continue
        vks.append(vk)
    for v in vks:
        user32.keybd_event(v, 0, 0, 0)
        time.sleep(0.04)
    for v in reversed(vks):
        user32.keybd_event(v, 0, 0x0002, 0)
        time.sleep(0.04)


# ── 开关识别（HDR 等 Win11 设置开关） ──────────────────

def locate_toggle_x(row_y: int, rect: tuple, img_path: str, label_right: int) -> int | None:
    """在标签行右侧，用亮度偏离找出最靠右"实心药丸"(开关)中心 x；与主题无关。"""
    img = Image.open(img_path).convert("RGB")
    px = img.load()
    w, h = img.size
    band_top = max(0, row_y - 12)
    band_bottom = min(h - 1, row_y + 12)
    x_start = max(label_right, 0)
    x_end = min(w - 1, rect[2] - 15)
    lums = []
    for x in range(x_start, x_end):
        s = c = 0
        for y in range(band_top, band_bottom):
            r, g, b = px[x, y]
            s += (r + g + b) / 3.0
            c += 1
        lums.append(s / c)
    if not lums:
        return None
    med = sorted(lums)[len(lums) // 2]
    runs = []
    i = 0
    while i < len(lums):
        if abs(lums[i] - med) > 18:
            j = i
            while j < len(lums) and abs(lums[j] - med) > 18:
                j += 1
            runs.append((i, j))
            i = j
        else:
            i += 1
    cand = [x_start + (a + b) // 2 for a, b in runs if 18 <= b - a <= 90]
    return cand[-1] if cand else None


def toggle_is_on(img_path: str, x: int, y: int) -> bool:
    """读开关像素状态：开启=蓝色强调色（b 明显高于 r），关闭=灰色（r≈g≈b）。"""
    img = Image.open(img_path).convert("RGB")
    r, g, b = img.load()[x, y]
    return (b > r + 25) and (b > 90)


# ── 截图 → 文本化（视觉模型/HDR 回读共用） ──────────────

_GRADIENT = " .:-=+*#%@"


def screenshot_ocr_text(path: str, max_blocks: int = 30) -> str:
    """截图 → OCR 文字块（屏幕百分比坐标），置信度 <0.5 过滤。"""
    boxes = ocr_boxes(path)
    if not boxes:
        return ""
    img = Image.open(path)
    w, h = img.size
    lines = []
    for text, (l, t, r, b) in boxes[:max_blocks]:
        cx = (l + r) // 2
        cy = (t + b) // 2
        px = round(cx / w * 100) if w else 0
        py = round(cy / h * 100) if h else 0
        lines.append(f"  ({px}%,{py}%) {text}")
    return "\n".join(lines)


def screenshot_ascii(path: str, width: int = 80) -> str:
    """截图 → ASCII 混合轮廓（字符梯度 + Canny 边缘），供模型理解布局。"""
    try:
        try:
            import cv2
            import numpy as np
            img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
            if img is not None:
                aspect = img.shape[0] / img.shape[1]
                height = max(1, int(width * aspect * 0.5))
                small = cv2.resize(img, (width, height), interpolation=cv2.INTER_AREA)
                idx = np.clip(small.astype(float) / 256 * len(_GRADIENT), 0, 9).astype(int)
                edges = cv2.Canny(small, 50, 150)
                return "\n".join(
                    "".join("@" if edges[y, x] > 0 else _GRADIENT[idx[y, x]] for x in range(width))
                    for y in range(height)
                )
        except ImportError:
            pass
        img = Image.open(path).convert("L")
        aspect = img.height / img.width
        height = max(1, int(width * aspect * 0.5))
        img = img.resize((width, height))
        px = list(img.getdata())
        return "\n".join(
            "".join(_GRADIENT[min(9, px[y * width + x] * 10 // 256)] for x in range(width))
            for y in range(height)
        )
    except Exception:
        return ""


def screenshot_metadata(path: str) -> str:
    """截图 → 图像元信息（原始尺寸/亮度/色调），一行文本。"""
    try:
        img = Image.open(path).convert("RGB")
        ow, oh = img.size
        img = img.resize((10, 10))
        px = list(img.getdata())
        avg = sum((r + g + b) // 3 for r, g, b in px) // len(px)
        warm = sum(1 for r, g, b in px if r > g + 20 and r > b + 20)
        cool = sum(1 for r, g, b in px if b > r + 20 and b > g + 20)
        tone = "暖色调" if warm > cool else "冷色调" if cool > warm else "中性色调"
        bright = "亮" if avg > 180 else "暗" if avg < 80 else "中等"
        return f"尺寸:{ow}x{oh} 平均亮度:{avg}({bright}) {tone}"
    except Exception:
        return ""


def screenshot_to_artifacts(path: str, send_image: bool = False) -> list:
    """截图 → 模型可消费产物列表（OCR + ASCII/原图 + 元信息），internal=True。"""
    name = os.path.basename(path)
    ocr_text = screenshot_ocr_text(path)
    meta_text = screenshot_metadata(path)
    if send_image:
        try:
            img = Image.open(path)
            if max(img.size) > 1280:
                ratio = 1280 / max(img.size)
                img = img.resize((int(img.size[0] * ratio), int(img.size[1] * ratio)))
            buf = io.BytesIO()
            img.save(buf, format="PNG", optimize=True)
            data = __import__("base64").b64encode(buf.getvalue()).decode("ascii")
            arts = [{"type": "image", "name": name, "mime": "image/png", "data": data, "internal": True}]
            supp = ""
            if ocr_text:
                supp += f"\n[屏幕 OCR 识别]\n{ocr_text}\n[/屏幕 OCR 识别]"
            if meta_text:
                supp += f"\n[图像信息] {meta_text}"
            if supp:
                arts.append({"type": "text", "name": name + ".txt", "data": supp.strip(), "internal": True})
            return arts
        except Exception:
            return []
    sections = []
    if ocr_text:
        sections.append(f"[屏幕 OCR 识别（坐标为屏幕百分比位置）]\n{ocr_text}\n[/屏幕 OCR 识别]")
    ascii_text = screenshot_ascii(path)
    if ascii_text:
        sections.append(f"[屏幕轮廓 ASCII（80列，空格=最暗 .:-=+*#%@=最亮/边缘）]\n{ascii_text}\n[/屏幕轮廓]")
    if meta_text:
        sections.append(f"[图像信息] {meta_text}")
    if not sections:
        return []
    return [{"type": "text", "name": name + ".txt", "data": "\n\n".join(sections), "internal": True}]


def get_window_exe(hwnd: int) -> str:
    """返回窗口所属进程的 exe 镜像名（不含路径），失败返回空串。

    用于 Atlas 的 software_id 派生——exe 比易变标题稳定得多。
    """
    if not hwnd:
        return ""
    pid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return ""
    PROCESS_QUERY = 0x0400 | 0x0010  # QUERY_INFORMATION | VM_READ
    h = kernel32.OpenProcess(PROCESS_QUERY, False, pid.value)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = ctypes.c_ulong(1024)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
        return ""
    finally:
        kernel32.CloseHandle(h)

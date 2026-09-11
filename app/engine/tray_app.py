"""P.A.L.M 系统托盘进程（Windows）。

职责：
  - 在 Windows 系统托盘显示 P.A.L.M 图标（与 Web 图标一致）
  - 右键菜单：打开控制台 / 启动后端 / 停止后端 / 退出
  - 负责拉起并监控 engine/web.py（pythonw 无窗口子进程，端口 8080）
  - 双击托盘图标 → 打开 Web 控制台

实现说明：
  - 仅使用标准库 + ctypes（不依赖 pystray/pywin32），保证任意 Python 3.10+ 可用。
  - 托盘图标文件：assets/palm_tray.ico（由 Web favicon.svg 生成，青色网格）。

用法：
  pythonw tray_app.py            # 后台无窗口常驻（推荐）
  python  tray_app.py            # 带控制台（调试）
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import os
import subprocess
import sys
import threading
import webbrowser

try:
    import winreg
except ImportError:  # 非 Windows 环境（如 headless 测试）
    winreg = None

# ---------------------------------------------------------------------------
# 路径与配置
# ---------------------------------------------------------------------------
ENGINE_DIR = os.path.dirname(os.path.abspath(__file__))
ICON_PATH = os.path.join(ENGINE_DIR, "assets", "palm_tray.ico")
WEB_PY = os.path.join(ENGINE_DIR, "web.py")
VPY = os.path.join(ENGINE_DIR, ".venv", "Scripts", "pythonw.exe")
if not os.path.exists(VPY):
    # 回退到系统 pythonw
    VPY = sys.executable.replace("python.exe", "pythonw.exe")

BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 8080
CONSOLE_URL = "http://127.0.0.1:43210"          # 前端 dev server（WebUI.bat 默认）
ADMIN_URL = "http://%s:%d/sandbox_panel.html" % (BACKEND_HOST, BACKEND_PORT)

# 开机自启注册表位置（用户级，无需管理员）
AUTOSTART_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_VALUE = "PALM-Autostart"

# ---------------------------------------------------------------------------
# Windows API 常量
# ---------------------------------------------------------------------------
WM_USER = 0x0400
WM_COMMAND = 0x0111
WM_DESTROY = 0x0002
NIM_ADD = 0x00000000
NIM_MODIFY = 0x00000001
NIM_DELETE = 0x00000002
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004
NIF_INFO = 0x00000010
TRAY_CALLBACK = WM_USER + 1

# 菜单命令
ID_OPEN = 1001
ID_START = 1002
ID_STOP = 1003
ID_AUTOSTART = 1005
ID_EXIT = 1004

# LoadLibrary / GetProcAddress
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
shell32 = ctypes.windll.shell32

# ---------------------------------------------------------------------------
# 结构体
# ---------------------------------------------------------------------------
class NOTIFYICONDATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.wintypes.DWORD),
        ("hWnd", ctypes.wintypes.HWND),
        ("uID", ctypes.wintypes.UINT),
        ("uFlags", ctypes.wintypes.UINT),
        ("uCallbackMessage", ctypes.wintypes.UINT),
        ("hIcon", ctypes.wintypes.HICON),
        ("szTip", ctypes.wintypes.CHAR * 128),
        ("dwState", ctypes.wintypes.DWORD),
        ("dwStateMask", ctypes.wintypes.DWORD),
        ("szInfo", ctypes.wintypes.CHAR * 256),
        ("uVersion", ctypes.wintypes.UINT),
        ("szInfoTitle", ctypes.wintypes.CHAR * 64),
        ("dwInfoFlags", ctypes.wintypes.DWORD),
        ("guidItem", ctypes.c_ubyte * 16),
        ("hBalloonIcon", ctypes.wintypes.HICON),
    ]


# ---------------------------------------------------------------------------
# 后端进程管理
# ---------------------------------------------------------------------------
_backend_proc = None
_backend_lock = threading.Lock()


def start_backend():
    global _backend_proc
    with _backend_lock:
        if _backend_proc is not None and _backend_proc.poll() is None:
            return False  # 已在运行
        try:
            _backend_proc = subprocess.Popen(
                [VPY, WEB_PY, "--host", BACKEND_HOST, "--port", str(BACKEND_PORT)],
                cwd=ENGINE_DIR,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=0x08000000,  # CREATE_NO_WINDOW
            )
            return True
        except Exception:
            _backend_proc = None
            return False


def stop_backend():
    global _backend_proc
    with _backend_lock:
        if _backend_proc is not None:
            try:
                _backend_proc.terminate()
            except Exception:
                pass
            _backend_proc = None


def backend_running():
    with _backend_lock:
        return _backend_proc is not None and _backend_proc.poll() is None


# ---------------------------------------------------------------------------
# 开机自启（用户级注册表，无需管理员）
# ---------------------------------------------------------------------------
def _autostart_cmdline():
    """返回写入注册表的命令行：pythonw tray_app.py"""
    return '"%s" "%s"' % (VPY, os.path.abspath(__file__))


def set_autostart(enable: bool) -> bool:
    """启用/禁用开机自启。返回是否成功。"""
    if winreg is None:
        return False
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, AUTOSTART_KEY, 0,
            winreg.KEY_SET_VALUE)
        if enable:
            winreg.SetValueEx(
                key, AUTOSTART_VALUE, 0, winreg.REG_SZ, _autostart_cmdline())
        else:
            try:
                winreg.DeleteValue(key, AUTOSTART_VALUE)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
        return True
    except OSError:
        return False


def autostart_enabled() -> bool:
    if winreg is None:
        return False
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, AUTOSTART_KEY, 0, winreg.KEY_READ)
        try:
            winreg.QueryValueEx(key, AUTOSTART_VALUE)
            return True
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(key)
    except OSError:
        return False


# ---------------------------------------------------------------------------
# 托盘实现
# ---------------------------------------------------------------------------
def load_icon():
    if os.path.exists(ICON_PATH):
        h = user32.LoadImageA(0, ICON_PATH.encode("mbcs"), 1, 16, 16, 0x00000010)
        if h:
            return h
    # 回退：系统默认应用图标
    return user32.LoadIconA(0, 32512)  # IDI_APPLICATION


def show_balloon(nid, title, text):
    nid.dwInfoFlags = 0x00000001  # NIIF_INFO
    nid.szInfoTitle = title.encode("mbcs")[:63]
    nid.szInfo = text.encode("mbcs")[:255]
    nid.uFlags = NIF_INFO
    shell32.Shell_NotifyIconA(NIM_MODIFY, ctypes.byref(nid))


def wnd_proc(hwnd, msg, wparam, lparam):
    if msg == TRAY_CALLBACK:
        # lparam 低位 = 事件
        event = lparam & 0xFFFF
        if event == 0x0200:  # WM_MOUSEMOVE
            pass
        elif event == 0x0201:  # WM_LBUTTONDOWN (左键单击/双击都触发)
            pass
        elif event == 0x0203:  # WM_LBUTTONDBLCLK
            webbrowser.open(CONSOLE_URL)
        elif event == 0x0204 or event == 0x0205:  # WM_RBUTTONDOWN/UP
            show_context_menu(hwnd)
    elif msg == WM_COMMAND:
        cmd = wparam & 0xFFFF
        handle_menu_cmd(cmd)
    elif msg == WM_DESTROY:
        stop_backend()
        user32.PostQuitMessage(0)
    return user32.DefWindowProcA(hwnd, msg, wparam, lparam)


def show_context_menu(hwnd):
    hmenu = user32.CreatePopupMenu()
    running = backend_running()
    user32.AppendMenuA(hmenu, 0x0000, ID_OPEN, "打开控制台".encode("mbcs"))
    if running:
        user32.AppendMenuA(hmenu, 0x0000, ID_STOP, "停止后端".encode("mbcs"))
    else:
        user32.AppendMenuA(hmenu, 0x0000, ID_START, "启动后端".encode("mbcs"))
    # 开机自启开关（勾选态用 ☑ / ☐ 前缀）
    label = ("☑ 开机自启" if autostart_enabled() else "☐ 开机自启")
    user32.AppendMenuA(hmenu, 0x0000, ID_AUTOSTART, label.encode("mbcs"))
    user32.AppendMenuA(hmenu, 0x0000, ID_EXIT, "退出".encode("mbcs"))

    pt = ctypes.wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    user32.SetForegroundWindow(hwnd)
    user32.TrackPopupMenu(hmenu, 0x0000, pt.x, pt.y, 0, hwnd, None)
    user32.DestroyMenu(hmenu)


def handle_menu_cmd(cmd):
    if cmd == ID_OPEN:
        webbrowser.open(CONSOLE_URL)
    elif cmd == ID_START:
        if start_backend():
            show_tip("P.A.L.M", "后端已启动 (:%d)" % BACKEND_PORT)
        else:
            show_tip("P.A.L.M", "后端已在运行")
    elif cmd == ID_STOP:
        stop_backend()
        show_tip("P.A.L.M", "后端已停止")
    elif cmd == ID_AUTOSTART:
        now_on = not autostart_enabled()
        if set_autostart(now_on):
            show_tip("P.A.L.M",
                     "开机自启已%s" % ("启用" if now_on else "禁用"))
        else:
            show_tip("P.A.L.M", "设置开机自启失败")
    elif cmd == ID_EXIT:
        stop_backend()
        user32.DestroyWindow(wnd_proc.hwnd)


def show_tip(title, text):
    if getattr(wnd_proc, "nid", None) is not None:
        show_balloon(wnd_proc.nid, title, text)


def main():
    # 注册窗口类
    wc = ctypes.wintypes.WNDCLASSEXA()
    wc.cbSize = ctypes.sizeof(ctypes.wintypes.WNDCLASSEXA)
    wc.lpfnWndProc = ctypes.WINFUNCTYPE(
        ctypes.c_long, ctypes.wintypes.HWND, ctypes.wintypes.UINT,
        ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM)(wnd_proc)
    wc.hInstance = kernel32.GetModuleHandleA(None)
    wc.lpszClassName = b"PALMTrayClass"

    if not user32.RegisterClassExA(ctypes.byref(wc)):
        # 可能已经注册（多次运行），忽略
        pass

    hwnd = user32.CreateWindowExA(
        0, b"PALMTrayClass", b"P.A.L.M Tray", 0,
        0, 0, 0, 0, 0, 0, wc.hInstance, None)
    if not hwnd:
        print("创建托盘窗口失败")
        return
    wnd_proc.hwnd = hwnd

    # 托盘图标
    nid = NOTIFYICONDATA()
    nid.cbSize = ctypes.sizeof(NOTIFYICONDATA)
    nid.hWnd = hwnd
    nid.uID = 1
    nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
    nid.uCallbackMessage = TRAY_CALLBACK
    nid.hIcon = load_icon()
    nid.szTip = b"P.A.L.M"
    wnd_proc.nid = nid

    if not shell32.Shell_NotifyIconA(NIM_ADD, ctypes.byref(nid)):
        print("添加托盘图标失败")
        return

    # 自动拉起后端
    if start_backend():
        show_balloon(nid, "P.A.L.M", "已启动，后端运行中 (:%d)" % BACKEND_PORT)

    # 消息循环
    msg = ctypes.wintypes.MSG()
    while user32.GetMessageA(ctypes.byref(msg), 0, 0, 0) != 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageA(ctypes.byref(msg))

    shell32.Shell_NotifyIconA(NIM_DELETE, ctypes.byref(nid))


if __name__ == "__main__":
    main()

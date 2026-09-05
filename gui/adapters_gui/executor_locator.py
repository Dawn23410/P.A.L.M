"""执行器定位模块：定向查找 + 状态读取 + 关窗。

把「按目标控件直接定位」从全树构建中剥离：
- find_control_direct：UIA 定向查找（~10-30ms，替代全树 560-1200ms）
- read_toggle_state：读取开关（ToggleSwitch）当前状态，供 LLM 状态先验（check 动作）
- close_window：关闭窗口（定向找关闭按钮 / Alt+F4 兜底），供 LLM 用完清理（洁癖）

坑（uiautomation fork）：
1. GetFirstChildControl 只取第一个子元素，不使用条件；必须用
   Control(searchFromControl=..., SubName/AutomationId=..., searchDepth=...) 构造 +
   Exists() 判定，条件才生效。
2. 属性键用大写驼峰（SubName=子串匹配、AutomationId=精确）；小写键被忽略。
3. SubName 比 Name（精确）更能容忍 LLM 给参不精确。
"""
from __future__ import annotations

import ctypes
import time

import uiautomation as auto

from .desktop_control import click_point, is_electron_app

user32 = ctypes.windll.user32


def _search_ctrl(hwnd: int, name="", automation_id="", depth: int = 24):
    """构造带条件的定向搜索控件（未命中时 Exists() 为 False）。

    depth 默认 24：SystemSettings 等系统的 ToggleSwitch 常位于树深层（>12），
    12 会漏命中；24 覆盖绝大多数窗口且仍远快于全树构建。
    """
    kw = {"searchFromControl": auto.ControlFromHandle(hwnd),
          "searchDepth": depth, "searchInterval": 0.05}
    if automation_id:
        kw["AutomationId"] = automation_id
    if name:
        kw["SubName"] = name
    return auto.Control(**kw)


def find_control_direct(hwnd: int, name: str = "", automation_id: str = "",
                        control_type: str = "") -> tuple[int, int] | None:
    """定向查找目标控件，返回屏幕点击点 (x, y)；未命中返回 None。

    depth 自适应：先 12 快速查（~84ms，绝大多数浅层控件），
    未命中再 24 深查（~515ms，SystemSettings 等深层 ToggleSwitch 需要）。
    SplitButton（如 Office 字号下拉）点击点偏移到右侧箭头区——点主体不弹下拉，
    这是 Windows SplitButton 通用惯例（箭头在右），非应用硬编码。
    """
    if not hwnd:
        return None
    for depth in (12, 24):
        try:
            ctrl = _search_ctrl(hwnd, name, automation_id, depth=depth)
            # 定向查找限时 2s：Word 等文档类窗口正文深树查找易空转，快速失败转 OCR 兜底
            if not ctrl.Exists(2.0):
                continue
            r = ctrl.BoundingRectangle
            if r.left >= r.right or r.top >= r.bottom:
                continue
            cx = int((r.left + r.right) / 2)
            cy = int((r.top + r.bottom) / 2)
            if "SplitButton" in str(ctrl.ControlType):
                cx = int(r.right - (r.right - r.left) * 0.25)  # 箭头区
            return (cx, cy)
        except Exception:
            continue
    return None


_TOGGLE_PATTERN_ID = 10015  # UIA TogglePattern（uiautomation fork 无 GetTogglePattern，走通用 GetPattern）


def read_toggle_state(hwnd: int, automation_id: str) -> int:
    """读取开关控件状态（TogglePattern.ToggleState）：1=开 0=关 -1=未找到/非开关。"""
    if not hwnd or not automation_id:
        return -1
    for depth in (12, 24):  # depth 自适应：浅层快速、深层兜底
        try:
            ctrl = _search_ctrl(hwnd, automation_id=automation_id, depth=depth)
            if not ctrl.Exists(2.0):  # 同 find_control_direct：限时防深树空转
                continue
            pat = ctrl.GetPattern(_TOGGLE_PATTERN_ID)  # 已返回 TogglePattern 实例
            if pat is None:
                return -1
            return pat.ToggleState
        except Exception:
            continue
    return -1


def _iter_close_candidates(root, name: str, max_depth: int):
    """深度遍历窗口子树，产出名称精确等于 name 的控件（关闭按钮候选）。"""
    stack = [(root, 0)]
    while stack:
        ctrl, depth = stack.pop()
        if depth >= max_depth:
            continue
        try:
            for ch in ctrl.GetChildren():
                if (ch.Name or "") == name:
                    yield ch
                stack.append((ch, depth + 1))
        except Exception:
            continue


def close_window(hwnd: int) -> bool:
    """关闭窗口：关闭按钮 → Alt+F4 → 保存对话框(不保存)，逐步降级并每次复查。"""
    if not hwnd or not user32.IsWindow(hwnd):
        return False
    if is_electron_app(hwnd):
        # Electron 应用跳过 UIA 关闭按钮查找（GetChildren 遍历触发 ntdll），
        # 直接 Alt+F4。窗口操控置前会破坏 Electron 渲染，故仅在目标已为前景窗口时
        # 可靠生效（自动化链中目标通常为前景窗口）。
        try:
            _send_altkey(0x73)
            time.sleep(0.6)
        except Exception:
            pass
        return not user32.IsWindow(hwnd)

    def _send_altkey(vk: int) -> None:
        user32.keybd_event(0x12, 0, 0, 0)
        user32.keybd_event(vk, 0, 0, 0)
        user32.keybd_event(vk, 0, 0x0002, 0)
        user32.keybd_event(0x12, 0, 0x0002, 0)

    # 1) 定向找标题栏关闭按钮：窗口内可能有多个「关闭」（文档浮动按钮 vs 标题栏按钮），
    #    标题栏永远最靠上 → 遍历候选取 top 最小者；且用精确 Name 避免误中「关闭此消息」。
    best = None
    for cond_name in ("关闭", "Close"):
        try:
            root = auto.ControlFromHandle(hwnd)
            for ctrl in _iter_close_candidates(root, cond_name, 4):
                r = ctrl.BoundingRectangle
                if r.left >= r.right or r.top >= r.bottom:
                    continue
                if best is None or r.top < best[1]:
                    best = (ctrl, r.top, r.left, r.right, r.bottom)
        except Exception:
            continue
    if best:
        _, t, l, r_, b = best  # (ctrl, top, left, right, bottom)
        x, y = int((l + r_) / 2), int((t + b) / 2)
        click_point(x, y, hwnd=hwnd)
    time.sleep(0.6)
    if not user32.IsWindow(hwnd):
        return True
    # 2) Alt+F4 兜底
    try:
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.05)
        _send_altkey(0x73)  # f4
        time.sleep(0.6)
        if not user32.IsWindow(hwnd):
            return True
    except Exception:
        return False
    # 2.5) 模态「是否保存」对话框拦截（Alt+F4 触发）：Invoke 对话框内「不保存」按钮
    _dismiss_save_dialog(hwnd)
    time.sleep(0.8)
    if not user32.IsWindow(hwnd):
        return True
    # 3) Alt+N 兜底（非模态场景：键盘焦点在对话框时助记键生效）
    try:
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.05)
        _send_altkey(ord('N'))
        time.sleep(0.6)
    except Exception:
        pass
    return not user32.IsWindow(hwnd)  # 诚实返回：没关掉报失败，不假成功


def _dismiss_save_dialog(hwnd: int) -> None:
    """关窗兜底：进程内若有模态「是否保存」对话框（Office NUIDialog），Invoke 其「不保存」。

    点标题栏 X / Alt+F4 遇到未保存修改会弹模态对话框，此时键盘 Alt+N 发给主窗口被拦截，
    必须直接触发对话框内的「不保存」按钮（UIA InvokePattern，id=10000）。
    """
    import ctypes
    u32 = ctypes.windll.user32
    pid = ctypes.c_ulong()
    u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    dialogs = []

    def _cb(dlg, _l):
        if u32.IsWindowVisible(dlg):
            length = u32.GetWindowTextLengthW(dlg)
            cls = ctypes.create_unicode_buffer(64)
            u32.GetClassNameW(dlg, cls, 64)
            title = ""
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                u32.GetWindowTextW(dlg, buf, length + 1)
                title = buf.value
            p = ctypes.c_ulong()
            u32.GetWindowThreadProcessId(dlg, ctypes.byref(p))
            # 同进程、NUIDialog（Office 模态框）、标题疑似保存类
            if (p.value == pid.value and cls.value == "NUIDialog"
                    and ("保存" in title or title in ("", "Microsoft Word"))):
                dialogs.append(dlg)
        return True
    u32.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(_cb), 0)
    for dlg in dialogs:
        try:
            ctrl = auto.Control(searchFromControl=auto.ControlFromHandle(dlg),
                                SubName="不保存", searchDepth=8, searchInterval=0.05)
            if ctrl.Exists(1.5):
                ctrl.GetPattern(10000).Invoke()  # InvokePattern id；fork 无 GetInvokePattern
        except Exception:
            continue

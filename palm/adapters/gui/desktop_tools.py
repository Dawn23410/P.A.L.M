"""桌面自动化工具（键盘/鼠标/截图/剪贴板/高层 GUI 编排）。

底层系统级输入与 OCR/开关识别统一由 desktop_control 通用引擎提供，
本模块只做工具封装 + 安全路径校验。新增高层工具（focus_window / find_text /
click_text / toggle_setting）让 agent 能像普通人一样编排多步 GUI 操作。
"""
from __future__ import annotations

import logging
import os
import tempfile
import time

from palm._core.tooling import Tool, ToolSpec
from .desktop_control import (
    ocr_boxes,
    find_box,
    find_window,
    focus_window,
    click_point,
    press_key,
    type_text,
    hotkey,
    locate_toggle_x,
    toggle_is_on,
    screenshot_to_artifacts,
)

_LOGGER = logging.getLogger(__name__)

# 截图保存路径白名单根目录：只允许临时目录、存储池、用户桌面
_ALLOWED_SAVE_ROOTS: list[str] = []
try:
    _ALLOWED_SAVE_ROOTS.append(os.path.normcase(os.path.abspath(tempfile.gettempdir())))
except Exception:
    pass
try:
    from palm._core.config import settings as _settings
    _ALLOWED_SAVE_ROOTS.append(os.path.normcase(os.path.abspath(_settings.STORAGE_POOL_DIR)))
except Exception:
    pass
try:
    _ALLOWED_SAVE_ROOTS.append(os.path.normcase(os.path.abspath(os.path.expanduser("~"))))
except Exception:
    pass


def _validate_save_path(path: str) -> str | None:
    """校验截图保存路径是否在白名单目录内；返回安全路径或 None（不合法）。"""
    if not path:
        return None
    abs_path = os.path.normcase(os.path.abspath(path))
    for root in _ALLOWED_SAVE_ROOTS:
        if abs_path.startswith(root):
            return abs_path
    return None


def _save_screenshot(region=None, save_path: str = "") -> str | None:
    """截全屏或区域图，落白名单路径；返回路径或 None。"""
    import pyautogui
    if save_path:
        safe = _validate_save_path(save_path)
        if safe is None:
            return None
    else:
        save_path = os.path.join(tempfile.gettempdir(),
                                 f"palm_screenshot_{os.getpid()}_{int(time.time())}.png")
    img = pyautogui.screenshot(region=region)
    img.save(save_path)
    return save_path


def _filter_by_rect(boxes: list, rect) -> list:
    """只保留中心点落在目标窗口矩形内的 OCR 结果，排除其他窗口（如 WorkBuddy）文字干扰。"""
    if not rect:
        return boxes
    l, t, r, b = rect
    out = []
    for item in boxes:
        btxt, box = item[0], item[1]
        bl, bt, br, bb = box
        cx, cy = (bl + br) // 2, (bt + bb) // 2
        if l <= cx <= r and t <= cy <= b:
            out.append(item)
    return out


# ── 键盘工具 ───────────────────────────────────────────

class TypeTextTool(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="type_text",
            description="在当前焦点位置输入文本（剪贴板粘贴，CJK/IME 安全）",
            parameters={"type": "object",
                        "properties": {"text": {"type": "string", "description": "要输入的文本"}},
                        "required": ["text"]},
            permission="desktop.control",
        )
    async def execute(self, text: str = "") -> str:
        if not text:
            return "未提供要输入的文本"
        try:
            type_text(text)
            return f"⌨️ 已输入 {len(text)} 个字符"
        except Exception as e:
            return f"输入文本失败: {e}"


class PressKeyTool(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="press_key",
            description="按下指定虚拟键（如 enter/escape/tab，也可传键码）",
            parameters={"type": "object",
                        "properties": {"key": {"type": "string", "description": "按键名或键码"}},
                        "required": ["key"]},
            permission="desktop.control",
        )
    async def execute(self, key: str = "") -> str:
        if not key:
            return "未指定按键"
        try:
            if key.isdigit():
                press_key(int(key))
            else:
                import pyautogui as pag
                pag.press(key.lower())
            return f"⌨️ 已按下 [{key}]"
        except Exception as e:
            return f"按键失败: {e}"


class HotkeyTool(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="hotkey",
            description="执行组合键（如 win+i 打开设置，ctrl+c 复制，win+d 显示桌面）",
            parameters={"type": "object",
                        "properties": {"keys": {"type": "array", "items": {"type": "string"},
                                                "description": "按键列表，如 ['win','i']"}},
                        "required": ["keys"]},
            permission="desktop.control",
        )
    async def execute(self, keys: list | None = None) -> str:
        if not keys:
            return "未指定组合键"
        try:
            hotkey(*keys)
            return f"⌨️ 已执行组合键: {'+'.join(keys)}"
        except Exception as e:
            return f"组合键执行失败: {e}"


# ── 鼠标工具 ───────────────────────────────────────────

class GetMousePosTool(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="get_mouse_position",
            description="获取当前鼠标位置坐标（x, y）",
            permission="desktop.control",
        )
    async def execute(self) -> str:
        import pyautogui as pag
        x, y = pag.position()
        return f"🖱 鼠标位置: ({x}, {y})"


class MoveMouseTool(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="move_mouse",
            description="移动鼠标到指定绝对坐标",
            parameters={"type": "object",
                        "properties": {"x": {"type": "integer"}, "y": {"type": "integer"},
                                       "duration": {"type": "number", "default": 0.3}},
                        "required": ["x", "y"]},
            permission="desktop.control",
        )
    async def execute(self, x: int = -1, y: int = -1, duration: float = 0.3) -> str:
        if x < 0 or y < 0:
            return "未指定目标坐标，请提供 x 与 y"
        import pyautogui as pag
        try:
            pag.moveTo(x, y, duration=duration)
            return f"🖱 鼠标已移动到 ({x}, {y})"
        except Exception as e:
            return f"移动鼠标失败: {e}"


class ClickMouseTool(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="click_mouse",
            description="在指定坐标真实点击鼠标；可指定窗口标题以绕开前台锁（后台进程点击命中目标）",
            parameters={"type": "object",
                        "properties": {
                            "x": {"type": "integer", "description": "点击 x 坐标"},
                            "y": {"type": "integer", "description": "点击 y 坐标"},
                            "button": {"type": "string", "enum": ["left", "right", "middle"], "default": "left"},
                            "window_title": {"type": "string", "description": "可选：目标窗口标题子串，命中则把点击挂到该窗口线程"},
                        },
                        "required": ["x", "y"]},
            permission="desktop.control",
        )
    async def execute(self, x: int = -1, y: int = -1, button: str = "left",
                      window_title: str = "") -> str:
        if x < 0 or y < 0:
            return "未指定坐标，请提供 x 与 y"
        try:
            hwnd = find_window(window_title)[0] if window_title else 0
            ok = click_point(x, y, hwnd=hwnd, right=(button == "right"))
            if not ok:
                return (f"⚠️ 点击未在真实桌面生效（隔离会话/无输入桌面），坐标 ({x},{y}) 未送达；"
                        f"请改用键盘/OCR 操作或手动点击")
            return f"🖱 在 ({x},{y}) 点击 {button}" + (f"（目标窗口: {window_title}）" if window_title else "")
        except Exception as e:
            return f"点击失败: {e}"


class ScrollMouseTool(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="scroll_mouse",
            description="滚动鼠标滚轮（正数向上，负数向下）",
            parameters={"type": "object",
                        "properties": {"clicks": {"type": "integer", "description": "滚动格数，正数向上"}},
                        "required": ["clicks"]},
            permission="desktop.control",
        )
    async def execute(self, clicks: int = 0) -> str:
        if clicks == 0:
            return "未指定滚动格数（正数向上，负数向下）"
        import pyautogui as pag
        try:
            pag.scroll(clicks)
            return f"🖱 已滚动 {clicks} 格"
        except Exception as e:
            return f"滚动失败: {e}"


class DragMouseTool(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="drag_mouse",
            description="从当前位置拖拽到指定坐标",
            parameters={"type": "object",
                        "properties": {"x": {"type": "integer"}, "y": {"type": "integer"},
                                       "button": {"type": "string", "enum": ["left", "right", "middle"], "default": "left"},
                                       "duration": {"type": "number", "default": 0.5}},
                        "required": ["x", "y"]},
            permission="desktop.control",
        )
    async def execute(self, x: int = -1, y: int = -1, button: str = "left", duration: float = 0.5) -> str:
        if x < 0 or y < 0:
            return "未指定拖拽目标坐标，请提供 x 与 y"
        import pyautogui as pag
        try:
            pag.dragTo(x, y, button=button, duration=duration)
            return f"🖱 已拖拽到 ({x}, {y})"
        except Exception as e:
            return f"拖拽失败: {e}"


# ── 高层 GUI 编排工具（普通人流程原语） ──────────────────

class FocusWindowTool(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="focus_window",
            description="把指定标题的窗口强行置前（绕前台锁），供后续点击/输入命中该窗口",
            parameters={"type": "object",
                        "properties": {"title": {"type": "string", "description": "窗口标题子串，如 '设置'"}},
                        "required": ["title"]},
            permission="desktop.control",
        )
    async def execute(self, title: str = "") -> str:
        if not title:
            return "未指定窗口标题"
        res = find_window(title)
        if not res:
            return f"未找到标题含 '{title}' 的窗口"
        hwnd, rect = res
        focus_window(hwnd)
        return f"🪟 已置前窗口 '{title}' 区域={rect}"


class FindTextTool(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="find_text",
            description="全屏截图并 OCR，返回含指定文字的所有位置（像素坐标 + 屏幕百分比）。可指定 window_title 把搜索限定在该窗口内，排除其他窗口文字干扰",
            parameters={"type": "object",
                        "properties": {
                            "text": {"type": "string", "description": "要查找的文字子串"},
                            "top_only": {"type": "boolean", "default": True, "description": "只返回最靠上的一个"},
                            "window_title": {"type": "string", "description": "可选：仅在该标题窗口矩形内查找"},
                        },
                        "required": ["text"]},
            permission="desktop.control",
        )
    async def execute(self, text: str = "", top_only: bool = True, window_title: str = "") -> str:
        if not text:
            return "未指定要查找的文字"
        rect = None
        if window_title:
            res = find_window(window_title)
            if res:
                rect = res[1]
        path = _save_screenshot()
        if not path:
            return "截图失败"
        boxes = ocr_boxes(path)
        if rect:
            boxes = _filter_by_rect(boxes, rect)
        hits = [(b, box) for (b, box) in boxes if text.lower() in b.lower()]
        if not hits:
            return f"屏幕未找到文字: {text}"
        hits.sort(key=lambda h: h[1][1])
        out = []
        for b, (l, t, r, btm) in (hits[:1] if top_only else hits):
            out.append(f"  '{b}' 中心=({ (l+r)//2 },{ (t+btm)//2 }) 框=({l},{t},{r},{btm})")
        return f"🔍 找到 {len(hits)} 处'{text}':\n" + "\n".join(out)


class ClickTextTool(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="click_text",
            description="全屏 OCR 找到指定文字，真实点击其中心（模拟人看到文字再点）",
            parameters={"type": "object",
                        "properties": {
                            "text": {"type": "string", "description": "要点击的文字子串"},
                            "button": {"type": "string", "enum": ["left", "right"], "default": "left"},
                            "window_title": {"type": "string", "description": "可选：点击前先把该窗口置前"},
                        },
                        "required": ["text"]},
            permission="desktop.control",
        )
    async def execute(self, text: str = "", button: str = "left", window_title: str = "") -> str:
        if not text:
            return "未指定要点击的文字"
        res = None
        if window_title:
            res = find_window(window_title)
            if res:
                focus_window(res[0])
        rect = res[1] if res else None
        path = _save_screenshot()
        if not path:
            return "截图失败"
        boxes = ocr_boxes(path)
        if rect:
            boxes = _filter_by_rect(boxes, rect)
        box = find_box(text, boxes)
        if not box:
            return f"屏幕未找到可点击的文字: {text}"
        l, t, r, b = box
        cx, cy = (l + r) // 2, (t + b) // 2
        hwnd = find_window(window_title)[0] if window_title else 0
        ok = click_point(cx, cy, hwnd=hwnd, right=(button == "right"))
        if not ok:
            return (f"⚠️ 文字 '{text}' 已定位到 ({cx},{cy}) 但点击未送达真实桌面"
                    f"（隔离会话/无输入桌面）；请改用键盘/OCR 或手动点击")
        return f"🖱 已点击文字 '{text}' 中心 ({cx},{cy})"


class ToggleSettingTool(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="toggle_setting",
            description="在 Windows 设置里把某个开关打开/关闭：OCR 找标签→定位右侧开关→真实点击→像素验证。标签如 '使用 HDR'",
            parameters={"type": "object",
                        "properties": {
                            "label": {"type": "string", "description": "开关旁的标签文字，如 '使用 HDR'"},
                            "target_state": {"type": "string", "enum": ["on", "off"], "default": "on"},
                            "window_title": {"type": "string", "default": "设置", "description": "设置窗口标题子串"},
                        },
                        "required": ["label"]},
            permission="desktop.control",
        )
    async def execute(self, label: str = "", target_state: str = "on", window_title: str = "设置") -> str:
        if not label:
            return "未指定开关标签"
        res = find_window(window_title)
        if not res:
            return f"未找到窗口: {window_title}"
        hwnd, rect = res
        path = _save_screenshot()
        if not path:
            return "截图失败"
        boxes = ocr_boxes(path)
        boxes = _filter_by_rect(boxes, rect)
        lab = find_box(label, boxes)
        if not lab:
            return f"设置页未找到标签: {label}"
        cy = (lab[1] + lab[3]) // 2
        tx = locate_toggle_x(cy, rect, path, lab[2])
        if tx is None:
            tx = rect[2] - 55
        before = toggle_is_on(path, tx, cy)
        want_on = target_state == "on"
        if before == want_on:
            return f"✅ 开关 '{label}' 已是{'开' if want_on else '关'}态，无需操作"
        click_point(tx, cy, hwnd=hwnd)
        time.sleep(2.5)
        path2 = _save_screenshot()
        after = toggle_is_on(path2, tx, cy) if path2 else before
        if after == want_on:
            return f"✅ 已把开关 '{label}' 切换为{'开' if want_on else '关'}"
        return f"⚠️ 点击已发出但状态未变（显示器可能不支持，或开关定位偏移）"


# ── 截图工具 ───────────────────────────────────────────

class TakeScreenshotTool(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="take_screenshot",
            description="截取全屏并保存。默认转 ASCII 文本回传分析，视觉模型可设 send_image=true 发原图",
            parameters={"type": "object",
                        "properties": {
                            "save_path": {"type": "string", "description": "保存路径(.png)，可选"},
                            "send_image": {"type": "boolean", "default": False, "description": "是否发送原图给模型"},
                        },
                        "required": []},
            permission="desktop.control",
        )
    async def execute(self, save_path: str = "", send_image: bool = False) -> str:
        self._last_artifacts = []
        path = _save_screenshot(save_path=save_path)
        if not path:
            return f"保存路径不在允许目录内（仅限临时目录/存储池/用户主目录）：{save_path}" if save_path else "截图失败"
        try:
            self._last_artifacts = screenshot_to_artifacts(path, send_image=send_image)
            mode = "原图" if send_image else "ASCII"
            return f"📸 截图已保存到 {path}（{mode}模式回传模型）"
        except Exception as e:
            return f"截图失败: {e}"


class ScreenshotRegionTool(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="screenshot_region",
            description="截取指定区域。默认转 ASCII 文本回传分析，视觉模型可设 send_image=true 发原图",
            parameters={"type": "object",
                        "properties": {
                            "left": {"type": "integer"}, "top": {"type": "integer"},
                            "width": {"type": "integer"}, "height": {"type": "integer"},
                            "save_path": {"type": "string"}, "send_image": {"type": "boolean", "default": False},
                        },
                        "required": ["left", "top", "width", "height"]},
            permission="desktop.control",
        )
    async def execute(self, left: int = -1, top: int = -1, width: int = -1, height: int = -1,
                      save_path: str = "", send_image: bool = False) -> str:
        self._last_artifacts = []
        if left < 0 or top < 0 or width <= 0 or height <= 0:
            return "未指定完整区域坐标，请提供 left/top/width/height（且宽高为正）"
        path = _save_screenshot(region=(left, top, width, height), save_path=save_path)
        if not path:
            return f"保存路径不在允许目录内：{save_path}" if save_path else "截图失败"
        try:
            self._last_artifacts = screenshot_to_artifacts(path, send_image=send_image)
            mode = "原图" if send_image else "ASCII"
            return f"📸 区域截图已保存到 {path}（{width}x{height}，{mode}模式回传模型）"
        except Exception as e:
            return f"截图失败: {e}"


# ── 剪贴板工具 ─────────────────────────────────────────

class ClipboardWriteTool(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="clipboard_write",
            description="将文本写入系统剪贴板",
            parameters={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
            permission="desktop.control",
        )
    async def execute(self, text: str = "") -> str:
        if not text:
            return "未提供要写入剪贴板的文本"
        try:
            import pyperclip
            pyperclip.copy(text)
        except Exception as e:
            return f"写入剪贴板失败: {e}"
        return f"📋 已写入剪贴板: {text[:50]}{'...' if len(text) > 50 else ''}"


class ClipboardReadTool(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="clipboard_read",
            description="读取系统剪贴板内容",
            permission="desktop.control",
        )
    async def execute(self) -> str:
        try:
            import pyperclip
            text = pyperclip.paste()
        except Exception as e:
            return f"读取剪贴板失败: {e}"
        return f"📋 剪贴板内容:\n{text}" if text else "剪贴板为空"


# ── 注册列表 ───────────────────────────────────────────

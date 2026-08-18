"""直接 UIA 操作工具：程序化驱动控件，坐标模拟兜底。

对应需求「直接操作 uia，兜底是现在的操作方式」：
- 主路径：UI Automation 模式直接驱动控件——InvokePattern 点按钮、ValuePattern 设值、
  SelectionItemPattern 选中选项卡/列表项、TogglePattern 勾选、ExpandCollapsePattern 展开/收起。
  不走鼠标坐标，不受窗口位置/遮挡/缩放影响，比坐标点击稳定得多。
- 兜底路径：控件缺失对应模式或 UIA 定位失败时，自动降级为「现在的操作方式」——
  find_control_direct 取坐标 + click_point / type_text / press_key / hotkey 真实键鼠模拟
  （与 run_automation 同源）。
"""
from __future__ import annotations

import logging
import time

import uiautomation as auto

from palm_sdk.bricks._shared.tooling import Tool, ToolSpec
from .desktop_control import (
    find_window, focus_window, click_point, type_text, press_key, hotkey,
)
from .executor_locator import find_control_direct

_LOGGER = logging.getLogger(__name__)

# UIA 模式 ID（uiautomation fork 无强类型 GetXxxPattern，统一走 GetPattern(id)）
_INVOKE = 10000
_EXPAND_COLLAPSE = 10001
_VALUE = 10002
_SELECTION_ITEM = 10010
_TOGGLE = 10015


def _resolve_hwnd(target) -> int:
    """窗口标题子串或 hwnd → hwnd；空取前台窗口。"""
    if isinstance(target, int) and target:
        return target
    if target:
        found = find_window(str(target))
        if found:
            return found[0]
    try:
        return auto.GetForegroundControl().NativeWindowHandle
    except Exception:
        return 0


def _locate(hwnd: int, name: str, automation_id: str, control_type: str = "") -> object | None:
    """UIA 定向定位控件；未命中或类型不符返回 None。"""
    if not hwnd or (not name and not automation_id):
        return None
    try:
        root = auto.ControlFromHandle(hwnd)
        kw = {"searchFromControl": root, "searchDepth": 24, "searchInterval": 0.05}
        if automation_id:
            kw["AutomationId"] = automation_id
        if name:
            kw["SubName"] = name
        ctrl = auto.Control(**kw)
        if not ctrl.Exists(2.0):
            return None
        if control_type and control_type not in str(ctrl.ControlType):
            return None
        return ctrl
    except Exception as exc:
        _LOGGER.warning("uia 定位失败: %s", exc)
        return None


def _coord_point(hwnd: int, name: str, automation_id: str, control_type: str = ""):
    """坐标兜底：UIA 定向取点击点；无可定位则返回 None。"""
    if not (name or automation_id):
        return None
    return find_control_direct(hwnd, name, automation_id, control_type)


def uia_direct(action: str, ctrl, value: str) -> tuple[bool, str]:
    """程序化驱动控件（模块级，供执行器档1 复用）：Invoke/Value/SelectionItem/Toggle/ExpandCollapse。

    不走鼠标坐标，不受窗口位置/遮挡/缩放影响，比坐标点击稳定得多。控件缺失对应
    模式或抛异常时返回 (False, 原因)，交由调用方降级到坐标模拟。
    """
    label = name_or(ctrl, value)
    try:
        if action == "invoke":
            pat = ctrl.GetPattern(_INVOKE)
            if pat is None:
                return False, "无 InvokePattern"
            pat.Invoke()
            return True, f"已 Invoke「{label}」"
        if action == "set_value":
            pat = ctrl.GetPattern(_VALUE)
            if pat is None:
                return False, "无 ValuePattern"
            pat.SetValue(value)
            return True, f"已设值「{value}」到「{label}」"
        if action == "select":
            pat = ctrl.GetPattern(_SELECTION_ITEM)
            if pat is not None:
                pat.Select()
                return True, f"已选中「{label}」(SelectionItem)"
            if hasattr(ctrl, "Select"):
                ctrl.Select()
                return True, f"已选中「{label}」(Select)"
            return False, "无 SelectionItemPattern"
        if action == "toggle":
            pat = ctrl.GetPattern(_TOGGLE)
            if pat is None:
                return False, "无 TogglePattern"
            pat.Toggle()
            return True, f"已 Toggle「{label}」"
        if action in ("expand", "collapse"):
            pat = ctrl.GetPattern(_EXPAND_COLLAPSE)
            if pat is None:
                return False, "无 ExpandCollapsePattern"
            if action == "expand":
                pat.Expand()
            else:
                pat.Collapse()
            return True, f"已{'展开' if action == 'expand' else '收起'}「{label}」"
    except Exception as exc:
        return False, str(exc)[:80]
    return False, "未知直接动作"


class UiaOperateTool(Tool):
    """直接 UIA 操作（程序化模式优先），坐标模拟兜底。"""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="uia_operate",
            description=(
                "直接操作 UI Automation 控件（程序化驱动，比坐标点击稳定得多）："
                "主路径用 UIA 模式（Invoke 点按钮 / ValuePattern 设值 / SelectionItem 选中选项卡或列表项 / "
                "Toggle 勾选 / ExpandCollapse 展开收起），不经过鼠标坐标；"
                "当控件不支持对应模式或定位失败时，自动兜底为坐标模拟（点击/输入/按键，与 run_automation 同源）。"
                "参数：action 必填(invoke/set_value/select/toggle/expand/collapse/click/type/press/hotkey)；"
                "target=窗口标题子串（空取前台窗口）；name=控件名子串；automation_id=精确 id；"
                "control_type=类型过滤（可选，如 ButtonControl）；value 或 text=设值/输入的文本；"
                "key=press 按键名或键码；keys=hotkey 组合键列表。返回会标注走了「UIA直接」还是「坐标兜底」。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {"type": "string",
                               "enum": ["invoke", "set_value", "select", "toggle",
                                        "expand", "collapse", "click", "type", "press", "hotkey"],
                               "description": "操作类型"},
                    "target": {"type": "string", "description": "窗口标题子串或 hwnd；空取前台"},
                    "name": {"type": "string", "description": "控件名称子串（SubName 模糊匹配）"},
                    "automation_id": {"type": "string", "description": "控件 automation_id（精确匹配，优先级高于 name）"},
                    "control_type": {"type": "string", "description": "控件类型过滤，如 ButtonControl / ComboBoxControl"},
                    "value": {"type": "string", "description": "set_value/type 的文本值"},
                    "text": {"type": "string", "description": "value 的别名（同上）"},
                    "key": {"type": "string", "description": "press 动作：按键名(enter/tab)或键码"},
                    "keys": {"type": "array", "items": {"type": "string"}, "description": "hotkey 组合键列表，如 ['ctrl','s']"},
                },
                "required": ["action"],
            },
            permission="desktop.control",
        )

    async def execute(self, action: str = "", target: str = "", name: str = "",
                      automation_id: str = "", control_type: str = "",
                      value: str = "", text: str = "", key: str = "",
                      keys: list | None = None) -> str:
        if not action:
            return "未指定 action。"
        inp = value if value != "" else text
        hwnd = _resolve_hwnd(target)
        if not hwnd and action not in ("press", "hotkey"):
            return f"找不到窗口: {target or '前台'}"

        # 坐标类动作本身就是「现在的操作方式」兜底路径，直接走坐标
        if action in ("click", "type", "press", "hotkey"):
            return self._coord_only(action, hwnd, name, automation_id, control_type, inp, key, keys)

        # 直接 UIA 优先
        ctrl = _locate(hwnd, name, automation_id, control_type)
        if ctrl is not None:
            ok, msg = self._direct(action, ctrl, inp)
            if ok:
                return f"[UIA直接] {msg}"
            fb = self._coord_fallback(action, hwnd, name, automation_id, control_type, inp)
            return f"[坐标兜底] 直接操作失败({msg})；{fb}"
        return self._coord_fallback(action, hwnd, name, automation_id, control_type, inp)

    # ── 直接 UIA 路径 ──────────────────────────────────
    def _direct(self, action: str, ctrl, value: str) -> tuple[bool, str]:
        # 委托给模块级 uia_direct，执行器档1 复用同一套程序化逻辑，避免重复
        return uia_direct(action, ctrl, value)

    # ── 坐标兜底路径（现在的操作方式）────────────────────
    def _coord_fallback(self, action, hwnd, name, automation_id, control_type, value) -> str:
        pt = _coord_point(hwnd, name, automation_id, control_type)
        if pt is None:
            return "坐标兜底失败：控件未定位"
        x, y = pt
        focus_window(hwnd)
        time.sleep(0.05)
        click_point(x, y, hwnd=hwnd)
        if action == "set_value":
            time.sleep(0.08)
            type_text(value)
            time.sleep(0.05)
            hotkey("enter")
            return f"坐标输入「{value}」成功"
        return "坐标点击成功"

    def _coord_only(self, action, hwnd, name, automation_id, control_type, inp, key, keys) -> str:
        if action == "press":
            if not key:
                return "未指定 key"
            if str(key).isdigit():
                press_key(int(key))
            else:
                import pyautogui as _pag
                _pag.press(str(key).lower())
            return f"已按下 [{key}]"
        if action == "hotkey":
            if not keys:
                return "未指定 keys"
            hotkey(*keys)
            return f"已执行组合键: {'+'.join(keys)}"
        # click / type 需要定位（除非仅对当前焦点 type）
        if action == "click":
            pt = _coord_point(hwnd, name, automation_id, control_type)
            if pt is None:
                return "坐标点击失败：控件未定位"
            x, y = pt
            focus_window(hwnd)
            time.sleep(0.05)
            click_point(x, y, hwnd=hwnd)
            return "坐标点击成功"
        # type：有定位则先聚焦控件再输入，否则直接打当前焦点
        if name or automation_id:
            pt = _coord_point(hwnd, name, automation_id, control_type)
            if pt is not None:
                x, y = pt
                focus_window(hwnd)
                time.sleep(0.05)
                click_point(x, y, hwnd=hwnd)
                time.sleep(0.08)
        if not inp:
            return "未指定输入文本(value/text)"
        type_text(inp)
        return f"已输入 {len(inp)} 字符"


def name_or(ctrl, fallback: str) -> str:
    """控件展示名优先，缺失时用传入值兜底。"""
    try:
        n = ctrl.Name
        if n:
            return n
    except Exception:
        pass
    return fallback or "控件"



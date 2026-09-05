"""执行分级（对应需求⑥点）：节点操控 → OCR+点击预测 → LLM 语义兜底 → VLC 视觉兜底。

- 档1 节点操控：复用 uia_operate 的程序化模式（Invoke/Value/Toggle），优先于坐标点击，
  最稳定（不受窗口位置/遮挡/缩放影响）。仅在控件支持对应模式时启用，否则交由档2/档3/档4。
- 档2 OCR+点击预测：UIA 不可取时的降级。点击预测的「概率区域消歧」在 coord_memory 区域模型
  接入后补充（后续分期）；本期复用执行器现有 OCR 文本盒定位作为档2 基础。
- 档3 LLM 语义兜底：规划阶段文本兜底（automation 砖 _build_llm_planner 复用 agent_provider
  + stream_llm 产出 executor 可消费的步骤）；执行层语义点击兜底已落地（executor 的
  _LlmMixin + llm_click_fallback_enabled，在档2 OCR 失败、档4 VLC 之前插入，对界面文字做
  语义匹配，聊天模型即可承担，不需视觉能力）。
- 档4 VLC 视觉兜底：受「llm_enhance 用户设置」+「视觉模型能力」双门控。聊天模型无视觉能力
  时直接禁用并报错，绝不静默失败（对应需求⑥点末级"聊天模型降级报错"）。
"""
from __future__ import annotations

import logging

from .gui_settings import is_llm_enhance_enabled
from .uia_operate import _locate as _uia_locate, uia_direct

_LOGGER = logging.getLogger(__name__)


def try_click_direct(hwnd: int, name: str, automation_id: str, control_type: str = "") -> tuple[bool, str]:
    """档1 click：用 UIA InvokePattern 程序化触发按钮，不走坐标。"""
    ctrl = _uia_locate(hwnd, name, automation_id, control_type)
    if ctrl is None:
        return False, "uia 未定位到控件"
    ok, msg = uia_direct("invoke", ctrl, "")
    return ok, (f"UIA 直接触发: {msg}" if ok else f"UIA 直接触发失败: {msg}")


def try_setvalue_direct(hwnd: int, name: str, automation_id: str, control_type: str, value: str) -> tuple[bool, str]:
    """档1 type：用 UIA ValuePattern 设值，比坐标聚焦输入稳定。"""
    if not value:
        return False, "无输入值"
    ctrl = _uia_locate(hwnd, name, automation_id, control_type)
    if ctrl is None:
        return False, "uia 未定位到控件"
    ok, msg = uia_direct("set_value", ctrl, value)
    return ok, (f"UIA 直接设值: {msg}" if ok else f"UIA 直接设值失败: {msg}")


def try_toggle_direct(hwnd: int, name: str, automation_id: str, control_type: str = "") -> tuple[bool, str]:
    """档1 toggle：用 UIA TogglePattern 切换开关。"""
    ctrl = _uia_locate(hwnd, name, automation_id, control_type)
    if ctrl is None:
        return False, "uia 未定位到控件"
    ok, msg = uia_direct("toggle", ctrl, "")
    return ok, (f"UIA 直接切换: {msg}" if ok else f"UIA 直接切换失败: {msg}")


def supports_gui_vision() -> bool:
    """档4 能力门控：是否配置了可用的视觉模型。

    本期默认 False（聊天模型无视觉能力），待接入视觉模型时在 settings 增加
    gui_vision_model / 模型 vision 标记后再放行。
    """
    # TODO(后续分期): 探测 settings 的 gui_vision_model 或对话模型的 vision 能力。
    return False


def vlc_fallback_enabled() -> tuple[bool, str]:
    """档4 总开关：llm_enhance 开启 且 视觉模型可用。否则返回 (False, 原因)。"""
    if not is_llm_enhance_enabled():
        return False, "未开启「GUI 允许 LLM 增强」，按设计禁用图片推理兜底。"
    if not supports_gui_vision():
        return False, ("当前模型无视觉能力（聊天模型不支持图片推理），VLC 兜底已禁用。"
                       "请配置视觉模型或改用坐标/OCR 路径。")
    return True, ""


def llm_click_fallback_enabled() -> tuple[bool, str]:
    """档3 LLM 语义点击兜底门控：开启「GUI 允许 LLM 增强」即可（仅需文本模型，不需视觉能力）。

    与档4 VLC 不同，档3 走界面文字（OCR 结果）+ 意图的语义匹配，聊天模型即可承担，
    故不要求 supports_gui_vision。默认未开启「GUI 允许 LLM 增强」时返回 (False, 原因)。
    """
    if not is_llm_enhance_enabled():
        return False, "未开启「GUI 允许 LLM 增强」，按设计禁用 LLM 语义点击兜底。"
    return True, ""

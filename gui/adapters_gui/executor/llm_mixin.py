"""档3 LLM 语义点击兜底：可插拔决策接口（保留接口，未接真实语言模型）。

设计：与 vlc_mixin 对称。档3 用「界面文字（OCR 结果）+ 用户意图」做语义匹配——聊天模型
即可承担（无需视觉能力）；档4 用截图像素做视觉推理（需视觉模型）。把"界面文字+意图→
LLM 选出目标文字→坐标"抽象为 LlmDecider 接口。当前默认 NullLlmDecider（未接入），由
llm_click_fallback_enabled 门控（仅 llm_enhance 设置，不需视觉能力），在 _resolve_fallback
（档2）失败、_vlc_or_fail（档4）之前插入。后续接入文本 LLM 只需实现 LlmDecider 并提供
工厂，执行器主链无需改动。
"""
from abc import ABC, abstractmethod

import ctypes

from .constants import _LOGGER


class LlmDecider(ABC):
    """LLM 语义决策接口：给定步骤、窗口与界面文字，决定点哪、成不成。"""

    @abstractmethod
    def decide(self, step: dict, hwnd: int, ocr_boxes: list, window_title: str = ""
               ) -> tuple[bool, str, tuple[int, int] | None]:
        """返回 (是否成功, 消息, 屏幕坐标)。子类实现真实语义推理。"""
        raise NotImplementedError


class NullLlmDecider(LlmDecider):
    """默认占位：未接入语言模型，明确返回未启用。"""

    def decide(self, step: dict, hwnd: int, ocr_boxes: list, window_title: str = ""
               ) -> tuple[bool, str, tuple[int, int] | None]:
        return False, "LLM 语义点击兜底尚未接入（未开启 LLM 增强或模型不可用）", None


def get_llm_decider() -> LlmDecider:
    """LLM 决策器工厂：当前返回 NullLlmDecider，预留真实文本模型接入点。"""
    return NullLlmDecider()


def _get_window_title(hwnd: int) -> str:
    """取窗口标题（用于喂给 LLM 的界面上下文）。"""
    if not hwnd:
        return ""
    buf = ctypes.create_unicode_buffer(256)
    ctypes.windll.user32.GetWindowTextW(hwnd, buf, 256)
    return buf.value or ""


class _LlmMixin:
    """档3 LLM 语义点击兜底：委托给 LlmDecider 接口（保留接口，默认未放行）。"""

    def _llm_decide_and_click(self, step: dict, hwnd: int) -> tuple[bool, str]:
        """截屏 OCR 取界面文字→LLM 语义匹配目标→click_point。

        受 llm_click_fallback_enabled 门控保护（在 click_mixin._llm_or_fail 调用前已校验），
        默认不会进入；接入文本模型后替换工厂即可。
        """
        try:
            import os
            import tempfile
            import pyautogui
            from ..desktop_control import ocr_boxes, click_point
            shot = os.path.join(tempfile.gettempdir(), "executor_llm.png")
            pyautogui.screenshot(shot)
            boxes = ocr_boxes(shot)
            title = _get_window_title(hwnd)
            ok, msg, point = get_llm_decider().decide(step, hwnd, boxes, title)
            if ok and point:
                clicked = click_point(point[0], point[1], hwnd=hwnd)
                if not clicked:
                    return False, "LLM 决策坐标未送达真实桌面"
                return True, msg
            return ok, msg
        except Exception as exc:
            _LOGGER.warning("LLM 决策执行异常: %s", exc)
            return False, f"LLM 决策异常: {exc}"

"""档4 VLC 视觉兜底：可插拔决策接口（保留接口，未接真实视觉模型）。

设计：把"截图→视觉模型决策点击点"抽象为 VlcDecider 接口。当前默认 NullVlcDecider
（未接入），由 vlc_fallback_enabled 双门控（llm_enhance 设置 + supports_gui_vision 能力）
在外部拦截——默认 False 时根本不会进入到本 mixin。后续接入视觉模型只需实现 VlcDecider
并提供工厂，执行器主链无需改动。
"""
from abc import ABC, abstractmethod

from .constants import _LOGGER


class VlcDecider(ABC):
    """VLC 视觉决策接口：给定步骤与窗口，决定点哪、成不成。"""

    @abstractmethod
    def decide(self, step: dict, hwnd: int, screenshot_path: str) -> tuple[bool, str, tuple[int, int] | None]:
        """返回 (是否成功, 消息, 屏幕坐标)。子类实现真实视觉推理。"""
        raise NotImplementedError


class NullVlcDecider(VlcDecider):
    """默认占位实现：未接入视觉模型，明确返回未启用。"""

    def decide(self, step: dict, hwnd: int, screenshot_path: str) -> tuple[bool, str, tuple[int, int] | None]:
        return False, "VLC 视觉决策尚未接入（视觉模型能力未启用）", None


def get_vlc_decider() -> VlcDecider:
    """VLC 决策器工厂：当前返回 NullVlcDecider，预留真实视觉模型接入点。"""
    return NullVlcDecider()


class _VlcMixin:
    """档4 VLC 视觉兜底：委托给 VlcDecider 接口（保留接口，默认未放行）。"""

    def _vlc_decide_and_click(self, step: dict, hwnd: int) -> tuple[bool, str]:
        """截图→视觉决策器决定点击点→click_point。

        受 vlc_fallback_enabled 双门控保护，默认不会进入；接入视觉模型后替换工厂即可。
        """
        try:
            import tempfile
            import os
            shot = os.path.join(tempfile.gettempdir(), "executor_vlc.png")
            import pyautogui
            pyautogui.screenshot(shot)
            ok, msg, point = get_vlc_decider().decide(step, hwnd, shot)
            if ok and point:
                from .desktop_control import click_point
                clicked = click_point(point[0], point[1], hwnd=hwnd)
                if not clicked:
                    return False, "VLC 决策坐标未送达真实桌面"
                return True, msg
            return ok, msg
        except Exception as exc:
            _LOGGER.warning("VLC 决策执行异常: %s", exc)
            return False, f"VLC 决策异常: {exc}"

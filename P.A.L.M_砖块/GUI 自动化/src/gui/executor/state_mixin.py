"""状态机与鼠标中断检测 mixin（AutomationExecutor 的状态闸门与用户干预识别）。"""
import time

import pyautogui

from .constants import (
    _CANCELLED, _EXECUTING, _IDLE, _MOUSE_INTERRUPT_PX,
    _PAUSE_POLL_SEC, _PAUSED,
)


class _StateMixin:
    """状态机接口与中断检测：区分执行器自身移动与用户主动操作。"""

    def pause(self) -> str:
        with self._lock:
            if self._state == _EXECUTING:
                self._state = _PAUSED
                return "执行器已暂停：当前步骤完成后挂起。"
        return "执行器当前不在执行中，无法暂停。"

    def resume(self) -> str:
        with self._lock:
            if self._state == _PAUSED:
                self._state = _EXECUTING
                return "执行器已恢复执行。"
        return "执行器不在暂停状态，无需恢复。"

    def cancel(self) -> str:
        with self._lock:
            if self._state in (_EXECUTING, _PAUSED):
                self._state = _CANCELLED
                return "执行器已取消。"
        return "执行器当前不在执行中，无法取消。"

    def state(self) -> str:
        with self._lock:
            return self._state

    def _guard_state(self) -> bool:
        """状态闸门：Cancelled 停，Paused 轮询等待恢复。"""
        while True:
            with self._lock:
                state = self._state
            if state == _CANCELLED:
                return False
            if state == _EXECUTING:
                return True
            time.sleep(_PAUSE_POLL_SEC)

    def _note_self_move(self, x: int, y: int) -> None:
        """记录执行器自己移动到的位置（点击前调用），用于屏蔽自身动作。"""
        self._last_mouse = (x, y)

    def _check_interrupt(self) -> bool:
        """检测用户是否移动了鼠标；执行器刚动过或未动过则不算。"""
        try:
            cur = pyautogui.position()
        except Exception:
            return False
        last = self._last_mouse
        if last is None:
            self._last_mouse = (cur.x, cur.y)  # 首步以当前位置为基准
            return False
        return abs(cur.x - last[0]) + abs(cur.y - last[1]) > _MOUSE_INTERRUPT_PX

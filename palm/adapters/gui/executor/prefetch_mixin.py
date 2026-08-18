"""预取 mixin：后台预定位下一步（只定位不点击，无副作用）。"""
import threading

from ..executor_locator import find_control_direct


class _PrefetchMixin:
    """后台预定位：当前步执行完起守护线程定下一步，执行前消费结果。"""

    def _prefetch(self, next_step: dict, target: str) -> None:
        if next_step.get("action", "").lower() != "click":
            return
        hwnd, key, _ = self._resolve_target(next_step)
        if not hwnd:
            return

        def _worker():
            try:
                center = find_control_direct(
                    hwnd, name=next_step.get("name", ""),
                    automation_id=next_step.get("automation_id", ""),
                    control_type=next_step.get("control_type", ""))
                if center:
                    self._prefetch_result = {key: center}
            except Exception:
                pass

        threading.Thread(target=_worker, daemon=True).start()

    def _consume_prefetch(self, key: str) -> tuple[int, int] | None:
        """预取结果按步骤键消费（预取与执行间隔 <1s，窗口变化风险低）。"""
        pf = self._prefetch_result
        if pf:
            return pf.get(key)
        return None

"""执行器核心：AutomationExecutor 组合各 mixin，承载主循环与单步分发。

模块级 _EXECUTOR 单例保留跨工具调用的指纹缓存与状态。对外保持
AutomationExecutor / _EXECUTOR 名称不变（兼容 automation_orchestrator 与 gui/__init__）。
"""
import logging
import threading
import time

from .constants import (
    _DEFAULT_STEP_DELAY, _EXECUTING, _IDLE, _MAX_WAIT_SEC, _LOGGER)
from ..metrics import METRICS, new_run_stats
from .state_mixin import _StateMixin
from .locator_mixin import _LocatorMixin
from .click_mixin import _ClickMixin
from .verify_mixin import _VerifyMixin
from .vlc_mixin import _VlcMixin
from .llm_mixin import _LlmMixin
from .prefetch_mixin import _PrefetchMixin


class AutomationExecutor(
    _StateMixin, _LocatorMixin, _ClickMixin, _VerifyMixin, _VlcMixin, _LlmMixin, _PrefetchMixin
):
    """单步真实执行器：持有窗口指纹缓存、状态机与预取结果。"""

    def __init__(self) -> None:
        self._state = _IDLE
        self._lock = threading.Lock()
        # 运行时缓存：hwnd → {"fp": 窗口指纹, "locations": {step_key: (x, y)}}
        self._cache: dict[int, dict[str, object]] = {}
        self._last_mouse: tuple[int, int] | None = None  # 执行器自身最后移动位置
        self._prefetch_result: dict | None = None  # {step_key: center} 后台预定位结果
        self._last_hwnd = 0  # 最近成功操作的窗口：规划链内窗口标题变化时回退用
        self._timeout = 60  # run 总超时（秒），防 LLM 给大 wait/阻塞卡死
        self._sid_override = None  # 编排器下传的 software_id：统一坐标/转移层 sid

    async def run(self, steps: list[dict], software_id: str | None = None) -> str:
        if not isinstance(steps, list) or not steps:
            return "规划为空：没有可执行的步骤。"
        with self._lock:
            self._state = _EXECUTING
        self._last_mouse = None
        self._sid_override = software_id  # 统一坐标/转移层 sid，使联动度按 software_id 聚合
        self._stats = new_run_stats()
        t_start = time.perf_counter()
        results = []
        total = len(steps)
        timeout = self._timeout
        for idx, step in enumerate(steps, 1):
            action = (step.get("action") or "").lower()
            self._stats["actions"][action] = self._stats["actions"].get(action, 0) + 1
            if time.perf_counter() - t_start > timeout:  # 总超时兜底
                self._stats["timeout_fired"] = True
                results.append(f"⏱ 总超时（>{timeout}s），中止于第{idx}步")
                break
            if not self._guard_state():
                results.append(f"✋ 第{idx}步：执行被取消")
                break
            if self._check_interrupt():
                self._stats["mouse_interrupt"] = True
                with self._lock:
                    self._state = _CANCELLED
                results.append(f"✋ 第{idx}步：检测到鼠标被用户移动，执行已中断")
                break
            ok, msg, stop = self._execute_step(step, idx)
            results.append(f"{'✓' if ok else '✗'} 第{idx}步: {msg}")
            if stop:
                self._stats["stop_if_fired"] += 1
                results.append(f"✓ 目标已达成，提前结束（剩余 {total-idx} 步跳过）")
                break
            if not ok:
                self._stats["failures"].append(f"第{idx}步 {action}: {msg[:80]}")
                break
            # 预取下一步（后台定位，不点击）
            if idx < total:
                self._prefetch(steps[idx], step.get("target", ""))
            delay = step.get("delay", _DEFAULT_STEP_DELAY)
            if delay and delay > 0:
                time.sleep(delay)
        elapsed = time.perf_counter() - t_start
        with self._lock:
            self._state = _IDLE
        self._prefetch_result = None
        self._finalize_stats(total, elapsed, results)
        return self._summarize_run(results, total, elapsed)

    def _summarize_run(self, results: list, total: int, elapsed: float) -> str:
        """收口 run 结果为可读文本（从主循环抽出以满足单函数行数约束）。"""
        status = "完成" if results and all(r.startswith("✓") for r in results) else "中断/失败"
        body = "\n".join(results)
        return (f"执行器状态: {status} | 步骤 {len(results)}/{total} | 总耗时 {elapsed*1000:.0f}ms\n"
                f"平均每步 {elapsed/max(len(results), 1)*1000:.0f}ms\n{body}")

    def _finalize_stats(self, total: int, elapsed: float, results: list) -> None:
        """收口本次 run 的指标并落盘（失败静默，不阻塞执行结果返回）。"""
        s = self._stats
        s["steps_total"] = total
        s["steps_done"] = len(results)
        s["elapsed_ms"] = int(elapsed * 1000)
        done_all = results and all(r.startswith("✓") for r in results)
        s["outcome"] = ("timeout" if s["timeout_fired"] else
                        ("interrupted" if s["mouse_interrupt"] else
                         ("ok" if done_all else "failed")))
        sids = sorted({e.get("software_id", "") for e in self._cache.values() if e.get("software_id")})
        s["software"] = ",".join(sids)
        METRICS.record(s)

    def _execute_step(self, step: dict, idx: int) -> tuple[bool, str, bool]:
        """单步分发：wait/check/close/type|press|hotkey/verify/click → 各处理器。"""
        action = (step.get("action") or "").lower()
        if action == "wait":
            wait_s = min(step.get("timeout", 1.0), _MAX_WAIT_SEC)  # 单步等待限幅，防无限阻塞
            time.sleep(wait_s)
            return True, f"等待 {wait_s}s", False
        if action == "check":
            return self._act_check(step)
        if action == "close":
            return self._act_close(step)
        if action in ("type", "press", "hotkey"):
            return self._act_simple(action, step)
        if action == "verify":
            return self._act_verify(step)
        if action != "click":
            return False, f"不支持的 action={action!r}", False
        return self._run_click(step)


# 模块级单例：跨工具调用保留指纹缓存与状态
_EXECUTOR = AutomationExecutor()

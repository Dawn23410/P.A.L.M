"""调度引擎：守护线程按 tick 扫描到期任务并派发。

派发复用 agent 砖的 run_proactive 能力（经 registry 的 capabilities 取用，零跨砖 import），
由 agent 内部把推送内容经现有 SSE 通道投到会话队列，前端追加为助手气泡。
agent 事件循环首启未就绪时，到期任务退避重试，待循环就绪后补发。
"""
from __future__ import annotations

import logging
import threading
import time

from palm._core.container import registry
from .cron import compute_next_fire
from .store import ScheduleJob, ScheduleStore

_LOG = logging.getLogger(__name__)
_TICK_INTERVAL = 5.0
_FIRE_BACKOFF = 30.0


class SchedulerEngine:
    """单例调度引擎：自带守护线程，按 tick 触发到期任务。"""

    def __init__(self, store: ScheduleStore | None = None) -> None:
        self._store = store or ScheduleStore()
        self._thread: threading.Thread | None = None
        self._stop = False
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop = False
            self._thread = threading.Thread(target=self._tick_loop, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop = True

    @staticmethod
    def _agent_run_proactive():
        # 主动推送入口已收编至 evolution 砖（原属 agent），经 capabilities 零互导取用。
        # evolution 暴露 evolution_api 门面（包对象），run_proactive 是其属性而非独立能力键。
        evolution = container.get("evolution")
        if not evolution:
            return None
        api = (getattr(evolution, "capabilities", {}) or {}).get("evolution_api")
        return getattr(api, "run_proactive", None) if api is not None else None

    def _tick_loop(self) -> None:
        while not self._stop:
            time.sleep(_TICK_INTERVAL)
            try:
                self._scan_and_fire()
            except Exception:  # noqa: BLE001
                _LOG.exception("调度引擎扫描异常（继续）")

    def _scan_and_fire(self) -> None:
        now = time.time()
        jobs = self._store.list_jobs()
        run_proactive = self._agent_run_proactive()
        for job in jobs:
            if not job.enabled or job.next_run <= 0:
                self._recompute_if_needed(job, now)
                continue
            if job.next_run > now:
                continue
            if run_proactive is None:
                # agent 能力缺失（极端情况），下个 tick 再试。
                continue
            self._fire(job, run_proactive, now)

    def _recompute_if_needed(self, job: ScheduleJob, now: float) -> None:
        # 首次或重置后计算 next_run；一次性已过期则停用，避免反复扫描。
        if job.next_run > 0 or not job.enabled:
            return
        nxt = compute_next_fire(job.schedule_type, job.schedule_value, now, job.last_run)
        if nxt is None:
            self._store.update_job(job.id, enabled=False, next_run=0.0)
        else:
            self._store.update_job(job.id, next_run=nxt)

    def _fire(self, job: ScheduleJob, run_proactive, now: float) -> None:
        try:
            run_proactive(job.conversation_id, job.character_id, job.model, job.brief)
        except Exception:  # noqa: BLE001
            _LOG.exception("调度任务 %s 派发失败（退避 %.0fs 重试）", job.id, _FIRE_BACKOFF)
            self._store.update_job(job.id, next_run=now + _FIRE_BACKOFF)
            return
        last_run = now
        if job.schedule_type == "once":
            self._store.update_job(job.id, enabled=False, last_run=last_run, next_run=0.0)
            return
        nxt = compute_next_fire(job.schedule_type, job.schedule_value, now, last_run)
        self._store.update_job(job.id, last_run=last_run, next_run=nxt or 0.0)


engine = SchedulerEngine()
engine.start()
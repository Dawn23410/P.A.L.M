"""可观测性（主板组件）：每砖遥测汇聚。

轻量、进程内、零外部依赖：每砖记录调用计数/延迟/成功率/最近错误，喂给
BIOS 健康报告与前端「主板图」实时健康灯。纯记录基础设施，调用方按需
record()，不强制改动任何能力调用点（避免侵入式埋点）。

设计：TelemetrySink 全局单例 + per-brick 滑动窗口。老数据按容量上限
滚动丢弃，常驻内存可控。
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field

# 每砖保留的最近样本数（延迟/错误窗口）
_SAMPLE_MAX = 100


@dataclass
class _BrickMeter:
    calls: int = 0
    fails: int = 0
    ok_latency_sum: float = 0.0
    last_error: str | None = None
    last_error_ts: float = 0.0
    latencies: deque = field(default_factory=lambda: deque(maxlen=_SAMPLE_MAX))
    errors: deque = field(default_factory=lambda: deque(maxlen=_SAMPLE_MAX))


class TelemetrySink:
    """每砖遥测汇聚器（线程安全）。"""

    def __init__(self) -> None:
        self._meters: dict[str, _BrickMeter] = {}
        self._lock = threading.RLock()

    def record(self, brick: str, *, ok: bool, latency: float = 0.0,
               error: str | None = None) -> None:
        with self._lock:
            m = self._meters.setdefault(brick, _BrickMeter())
        m.calls += 1
        if ok:
            m.ok_latency_sum += latency
            m.latencies.append(latency)
        else:
            m.fails += 1
            if error:
                m.last_error = error
                m.last_error_ts = time.time()
                m.errors.append({"ts": m.last_error_ts, "error": error})

    def get(self, brick: str) -> dict:
        with self._lock:
            m = self._meters.get(brick)
            if not m:
                return {"calls": 0, "fails": 0, "success_rate": None,
                        "avg_latency": None, "last_error": None}
            rate = (m.calls - m.fails) / m.calls if m.calls else None
            avg = (m.ok_latency_sum / max(1, m.calls - m.fails)) if (m.calls - m.fails) else None
        return {
            "calls": m.calls,
            "fails": m.fails,
            "success_rate": rate,
            "avg_latency": avg,
            "last_error": m.last_error,
        }

    def snapshot(self) -> dict[str, dict]:
        return {name: self.get(name) for name in self._meters}


_sink = TelemetrySink()


def get_sink() -> TelemetrySink:
    """全局遥测汇聚器（单例）。"""
    return _sink

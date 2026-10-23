"""进程内开销监控：轻量计数器 +（可选）psutil 系统指标。

- 记录：uptime / req_count / error_count / last_ms / avg_ms /
  per-provider（count, errors, last_ms, avg_ms, completion_tokens 累计）/ 最近 20 次请求。
- run_chat 每次请求埋点一次；线程安全（锁保护）。
- system 字段：psutil 可用时报 RSS/CPU，未安装则为 null（零硬依赖，按需
  `pip install psutil` 即可点亮）。
"""
from __future__ import annotations

import threading
import time

_START = time.time()
_lock = threading.Lock()
_total = {"count": 0, "errors": 0, "last_ms": None, "sum_ms": 0.0}
_providers: dict[str, dict] = {}
_recent: list[dict] = []  # 最近 20 次请求

try:
    import psutil  # type: ignore

    _ps = psutil.Process()
except Exception:
    _ps = None


def record_request(provider: str, ms: float, ok: bool,
                   completion_tokens: int | None = None) -> None:
    """埋点：一次 provider 请求（成功或失败）。"""
    with _lock:
        _total["count"] += 1
        if not ok:
            _total["errors"] += 1
        _total["last_ms"] = round(ms, 1)
        _total["sum_ms"] += ms
        p = _providers.setdefault(
            provider, {"count": 0, "errors": 0, "last_ms": None,
                       "sum_ms": 0.0, "completion_tokens": 0})
        p["count"] += 1
        if not ok:
            p["errors"] += 1
        p["last_ms"] = round(ms, 1)
        p["sum_ms"] += ms
        if completion_tokens:
            p["completion_tokens"] += completion_tokens
        _recent.append({"provider": provider, "ms": round(ms, 1), "ok": ok,
                        "completion_tokens": completion_tokens,
                        "ts": round(time.time(), 3)})
        del _recent[:-20]


def snapshot() -> dict:
    """当前开销快照（/metrics 端点返回值）。"""
    with _lock:
        n = _total["count"]
        data = {
            "uptime_s": round(time.time() - _START, 1),
            "req_count": n,
            "error_count": _total["errors"],
            "last_ms": _total["last_ms"],
            "avg_ms": round(_total["sum_ms"] / n, 1) if n else None,
            "providers": {
                k: {**v,
                    "avg_ms": round(v["sum_ms"] / v["count"], 1) if v["count"] else None}
                for k, v in _providers.items()
            },
            "recent": list(_recent),
        }
    if _ps is not None:
        try:
            data["system"] = {
                "rss_mb": round(_ps.memory_info().rss / 1048576, 1),
                "cpu_percent": _ps.cpu_percent(interval=None),
            }
        except Exception:
            data["system"] = None
    else:
        data["system"] = None
    return data

"""基准测试共享内核：计时、统计、结果聚合、论文级报告器。

纯标准库实现，零外部依赖，可在离线 .venv 直接运行。
"""
from __future__ import annotations

import json
import math
import statistics
import time
import traceback
from dataclasses import dataclass, field, asdict
from typing import Callable, Optional


# ----------------------------------------------------------------------------
# 统计工具
# ----------------------------------------------------------------------------
def _percentile(sorted_vals: list[float], p: float) -> float:
    """线性插值分位数（与 numpy 默认方法一致）。"""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    k = (len(sorted_vals) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return float(sorted_vals[int(k)])
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


@dataclass
class LatencyStat:
    n: int = 0
    min_ms: float = 0.0
    p50_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0
    max_ms: float = 0.0
    mean_ms: float = 0.0

    @classmethod
    def from_samples(cls, samples_ms: list[float]) -> "LatencyStat":
        if not samples_ms:
            return cls()
        s = sorted(samples_ms)
        return cls(
            n=len(s),
            min_ms=s[0],
            p50_ms=_percentile(s, 50),
            p95_ms=_percentile(s, 95),
            p99_ms=_percentile(s, 99),
            max_ms=s[-1],
            mean_ms=statistics.fmean(s),
        )

    def as_dict(self) -> dict:
        return asdict(self)


# ----------------------------------------------------------------------------
# 单测结果
# ----------------------------------------------------------------------------
@dataclass
class CaseResult:
    kernel: str
    suite: str
    name: str
    dimension: str          # correctness | degradation | boundary | latency | idempotency
    status: str             # PASS | FAIL | SKIP | XFAIL
    detail: str = ""
    root_cause: str = ""    # SKIP/FAIL 时记录根因（论文级可追溯）
    latency: Optional[LatencyStat] = None
    metrics: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        d = asdict(self)
        if self.latency is not None:
            d["latency"] = self.latency.as_dict()
        return d


# ----------------------------------------------------------------------------
# 基准收集器（替代 unittest.TestResult，自定义论文级聚合）
# ----------------------------------------------------------------------------
class BenchCollector:
    def __init__(self, kernel: str):
        self.kernel = kernel
        self.results: list[CaseResult] = []

    def record(self, cr: CaseResult):
        self.results.append(cr)

    # 便捷构造器 --------------------------------------------------------------
    def _mk(self, suite, name, dimension, status, detail="", root_cause="",
            latency=None, metrics=None) -> CaseResult:
        return CaseResult(
            kernel=self.kernel, suite=suite, name=name, dimension=dimension,
            status=status, detail=detail, root_cause=root_cause,
            latency=latency, metrics=metrics or {},
        )

    def pass_(self, suite, name, dimension, detail="", latency=None, metrics=None):
        self.record(self._mk(suite, name, dimension, "PASS", detail, "", latency, metrics))

    def fail(self, suite, name, dimension, detail, root_cause=""):
        self.record(self._mk(suite, name, dimension, "FAIL", detail, root_cause))

    def skip(self, suite, name, dimension, root_cause):
        self.record(self._mk(suite, name, dimension, "SKIP", "", root_cause))

    def xfail(self, suite, name, dimension, detail, root_cause=""):
        self.record(self._mk(suite, name, dimension, "XFAIL", detail, root_cause))

    def measure(self, fn: Callable[[], None], n: int = 31) -> LatencyStat:
        """重复执行 fn 计时，返回 LatencyStat（毫秒）。"""
        samples: list[float] = []
        for _ in range(n):
            t0 = time.perf_counter()
            fn()
            t1 = time.perf_counter()
            samples.append((t1 - t0) * 1000.0)
        return LatencyStat.from_samples(samples)


# ----------------------------------------------------------------------------
# 注册表：kernel -> 基准函数
# ----------------------------------------------------------------------------
_REGISTRY: dict[str, Callable[[BenchCollector], None]] = {}


def benchmark(kernel: str):
    def deco(fn: Callable[[BenchCollector], None]):
        _REGISTRY[kernel] = fn
        return fn
    return deco


def all_kernels() -> list[str]:
    return list(_REGISTRY.keys())


# ----------------------------------------------------------------------------
# 报告器
# ----------------------------------------------------------------------------
def render_text(report: dict) -> str:
    L = []
    L.append("=" * 78)
    L.append("P.A.L.M MICROKERNEL BENCHMARK SUITE — COMMERCIAL-GRADE REPORT")
    L.append(f"generated: {report['generated']}   python: {report['python']}")
    L.append(f"environment: {report['environment']}")
    L.append("=" * 78)
    for kr in report["kernels"]:
        L.append("")
        L.append(f"## [{kr['kernel']}]  {kr['summary']}")
        L.append(f"    importable={kr['importable']}  "
                 f"cases={kr['counts']['total']}  "
                 f"PASS={kr['counts']['PASS']}  FAIL={kr['counts']['FAIL']}  "
                 f"SKIP={kr['counts']['SKIP']}  XFAIL={kr['counts']['XFAIL']}")
        for c in kr["cases"]:
            tag = {"PASS": "✓", "FAIL": "✗", "SKIP": "○", "XFAIL": "⚠"}.get(c["status"], "?")
            base = f"    {tag} {c['dimension']:<11} {c['name']}"
            if c.get("detail"):
                base += f"  — {c['detail']}"
            if c.get("latency"):
                lt = c["latency"]
                base += (f"  [lat n={lt['n']} p50={lt['p50_ms']:.3f}ms "
                         f"p95={lt['p95_ms']:.3f}ms max={lt['max_ms']:.3f}ms]")
            L.append(base)
            if c["status"] in ("FAIL", "SKIP") and c.get("root_cause"):
                L.append(f"        root_cause: {c['root_cause']}")
    L.append("")
    L.append("=" * 78)
    s = report["summary"]
    L.append(f"TOTAL kernels={s['kernels']}  cases={s['total']}  "
             f"PASS={s['PASS']}  FAIL={s['FAIL']}  SKIP={s['SKIP']}  XFAIL={s['XFAIL']}")
    L.append(f"Import-broken kernels: {', '.join(report['broken_kernels']) or 'none'}")
    L.append("=" * 78)
    return "\n".join(L)


def build_summary(kernel_reports: list[dict]) -> dict:
    agg = {"kernels": 0, "total": 0, "PASS": 0, "FAIL": 0, "SKIP": 0, "XFAIL": 0}
    for kr in kernel_reports:
        agg["kernels"] += 1
        for k in ("total", "PASS", "FAIL", "SKIP", "XFAIL"):
            agg[k] += kr["counts"][k]
    return agg

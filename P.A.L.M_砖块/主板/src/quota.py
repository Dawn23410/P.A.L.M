"""资源配额治理（主板组件）：总线级总量校验 + 子进程砖真实用量软度量。

主板隐喻：「每块砖声明自己吃多少 CPU/内存/IO」，总线控制器（BusController）据此
做总量校验——声明超额即告警（软强制，不强行 cgroup，因为进程内砖共享主进程）。
隔离子进程（ipc://）的砖可经 psutil 读到真实 rss/cpu，进程内砖共享主进程故只
能展示声明值。

psutil 为可选依赖：缺失时用量字段降级为 None，校验逻辑不受影响（纯声明式）。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

_LOGGER = logging.getLogger(__name__)


@dataclass
class BusCap:
    """总线资源总帽（软上限）。cpu_cores/mem_mb 为 0 表示不限制（跳过校验）。"""
    cpu_cores: float = 0.0
    mem_mb: int = 0
    io_total: int = 0


@dataclass
class Usage:
    """单砖真实用量（best-effort，仅隔离子进程可读）。"""
    cpu_pct: float | None = None
    rss_mb: float | None = None
    measured: bool = False


def measure_subprocess(proc) -> Usage:
    """读取子进程真实用量（psutil 可选）。拿不到返回未度量。"""
    if proc is None or proc.poll() is not None:
        return Usage(measured=False)
    try:
        import psutil  # type: ignore
    except Exception:  # noqa: BLE001  psutil 未安装 → 跳过真实度量
        return Usage(measured=False)
    try:
        p = psutil.Process(proc.pid)
        rss = p.memory_info().rss / (1024 * 1024)
        cpu = p.cpu_percent(interval=0.1)
        return Usage(cpu_pct=cpu, rss_mb=rss, measured=True)
    except Exception as exc:  # noqa: BLE001  子进程已退出/权限不足
        _LOGGER.debug("子进程用量度量失败: %s", exc)
        return Usage(measured=False)


class QuotaValidator:
    """总线配额校验器：聚合该总线所有砖的声明配额，对照总线总帽。"""

    def __init__(self, cap: BusCap | None = None) -> None:
        self.cap = cap or BusCap()

    def validate(self, declared: list) -> list[str]:
        """declared: list[ResourceQuota]。返回超限告警文本列表（空=合规）。"""
        warns: list[str] = []
        if self.cap.cpu_cores <= 0 and self.cap.mem_mb <= 0 and self.cap.io_total <= 0:
            return warns  # 总线未设帽 → 不校验
        total_cpu = sum(q.cpu_cores for q in declared)
        total_mem = sum(q.mem_mb for q in declared)
        total_io = sum(q.io_weight for q in declared)
        if self.cap.cpu_cores > 0 and total_cpu > self.cap.cpu_cores:
            warns.append(f"CPU 声明总和 {total_cpu} 核超出总线帽 {self.cap.cpu_cores} 核")
        if self.cap.mem_mb > 0 and total_mem > self.cap.mem_mb:
            warns.append(f"内存声明总和 {total_mem}MB 超出总线帽 {self.cap.mem_mb}MB")
        if self.cap.io_total > 0 and total_io > self.cap.io_total:
            warns.append(f"IO 权重总和 {total_io} 超出总线帽 {self.cap.io_total}")
        return warns

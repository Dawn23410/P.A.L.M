"""性能开销芯片：单芯片自采样的「仅产出」监控 IC。

两种采集目标，由构造参数选择，互不干扰：
- 进程级（默认）：绑 PID / 进程对象，采该进程的 CPU% / RSS / VMS / 磁盘 IO / 可选进程级显存（按 PID 经 NVML 精确匹配，而非整机显存）。
- 整机级（system=True）：采系统 CPU% / 内存%(used,total) / 磁盘 IO 速率 / 整机显存。
- 进程级 VRAM 估算（vram_estimate，默认开）：Windows(WDDM) 下无法按 PID 细分显存，
  改用整机显存滚动窗口的瞬峰归因——取「瞬峰值 - 平均正常值」作为本进程估算占用。

每枚芯片自带 1s 守护线程，写入有界环形缓冲；对外仅无参只读口 latest() / history()。
无控制路由、无全局协调，开数百枚亦仅各自一次廉价读取 + 一次 append。

依赖：psutil（必需，软引用以免 palm_sdk 整体不可导入）；pynvml（可选，仅显存）。
"""
from __future__ import annotations

import os
import threading
import time
from collections import deque
from typing import Any, Optional

try:
    import psutil
except ImportError:  # psutil 缺失时模块仍可导入，实例化再报错
    psutil = None

try:
    import pynvml
except ImportError:
    pynvml = None


def _open_nvml() -> Any:
    """尝试初始化 NVML 并返回 device0 句柄；不可用则返回 None（优雅降级）。"""
    if pynvml is None:
        return None
    try:
        pynvml.nvmlInit()
        return pynvml.nvmlDeviceGetHandleByIndex(0)
    except Exception:  # noqa: BLE001  无 GPU / 驱动未就绪均降级
        return None


def _vram_baseline_peak(values: list) -> tuple[float, float]:
    """从滚动窗口估算 VRAM 基线(平均正常值)与瞬峰。

    正常子集 = 低于窗口中位数的样本（排除瞬态尖峰），基线为其均值；
    瞬峰 = 窗口最大值。进程级显存估算 = 瞬峰值 - 平均正常值。
    """
    vals = sorted(values)
    n = len(vals)
    if n == 0:
        return 0.0, 0.0
    median = vals[n // 2]
    normal = [v for v in vals if v <= median]
    baseline = sum(normal) / len(normal) if normal else vals[0]
    peak = vals[-1]
    return baseline, peak


class PerfChip:
    """性能开销芯片：单芯片自采样、仅产出、无参采集、1s 固定节拍。"""

    def __init__(self, pid: Optional[int] = None, *, name: str = "perf",
                 history: int = 60, interval: float = 1.0,
                 system: bool = False, estimate_vram: bool = True) -> None:
        if psutil is None:
            raise RuntimeError("PerfChip 需要 psutil：pip install psutil")
        self.name = name
        self.system = system
        self.interval = interval
        self._buffer: deque = deque(maxlen=history)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._nvml = _open_nvml()
        # 进程级 VRAM 估算：仅进程模式启用（整机模式已有精确整机显存，无需估算）。
        self._estimate_vram = estimate_vram and not system
        # 整机显存滚动窗口，用于瞬峰检测与基线计算。
        self._vram_window: deque = deque(maxlen=history)
        if system:
            self.pid = None
            psutil.cpu_percent()            # 系统 CPU 首次调用为 0，仅用于 priming
            self._disk_prev = psutil.disk_io_counters()
            self._disk_ts = time.time()
        else:
            self.pid = os.getpid() if pid is None else int(pid)
            self._proc = psutil.Process(self.pid)
            self._proc.cpu_percent()        # 首次调用为 0，仅用于 priming
            try:                            # 磁盘 IO 计数：部分平台不支持则降级
                self._io_prev = self._proc.io_counters()
                self._io_ts = time.time()
            except Exception:  # noqa: BLE001
                self._io_prev = None
                self._io_ts = time.time()
        threading.Thread(target=self._loop, daemon=True).start()

    @classmethod
    def system_chip(cls, *, name: str = "system", history: int = 60,
                    interval: float = 1.0) -> "PerfChip":
        """整机采集便捷构造：系统 CPU/内存/磁盘/显存。"""
        return cls(system=True, name=name, history=history, interval=interval)

    # ---- 采样线程 ----

    def _loop(self) -> None:
        while not self._stop.is_set():
            sample = self._sample()
            with self._lock:
                self._buffer.append(sample)
            self._stop.wait(self.interval)

    def _sample(self) -> dict:
        return self._sample_system() if self.system else self._sample_process()

    def _sample_process(self) -> dict:
        """采一帧：进程 CPU% / RSS / VMS / 磁盘 IO 速率 / 可选显存。"""
        now = time.time()
        sample: dict[str, Any] = {"ts": now, "scope": "process", "pid": self.pid}
        try:
            sample["cpu_percent"] = self._proc.cpu_percent()
            mem = self._proc.memory_info()
            sample["rss"] = mem.rss
            sample["vms"] = mem.vms
        except Exception:  # noqa: BLE001  进程可能已退出
            sample["cpu_percent"] = None
            sample["rss"] = None
            sample["vms"] = None
        sample["io_read_rate"] = None
        sample["io_write_rate"] = None
        if self._io_prev is not None:
            try:
                cur = self._proc.io_counters()
                dt = now - self._io_ts
                if dt > 0:
                    sample["io_read_rate"] = (cur.read_bytes - self._io_prev.read_bytes) / dt
                    sample["io_write_rate"] = (cur.write_bytes - self._io_prev.write_bytes) / dt
                self._io_prev = cur
                self._io_ts = now
            except Exception:  # noqa: BLE001
                self._io_prev = None
        sample["vram_used"] = None
        sample["vram_total"] = None
        sample["vram_device_used"] = None
        sample["vram_estimate"] = None
        # 进程级显存：经 NVML 按 PID 精确匹配该进程在各 GPU 上的占用，而非整机显存。
        # GPU 砖（GSV/CosyVoice）需要的是自身占用，整机显存会混入其他进程误导判断。
        # 注意：Windows(WDDM) 驱动下 nvmlProcessInfo.usedGpuMemory 恒为 0，进程级显存
        # 仅 Linux 可靠；Windows 上此段拿不到细分值，由下方 vram_estimate 兜底。
        if self._nvml is not None:
            try:
                used = 0
                matched = False
                for i in range(pynvml.nvmlDeviceGetCount()):
                    handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                    procs = pynvml.nvmlDeviceGetComputeRunningProcesses(handle)
                    procs += pynvml.nvmlDeviceGetGraphicsRunningProcesses(handle)
                    seen = set()
                    for proc in procs:
                        if proc.pid == self.pid and proc.pid not in seen:
                            seen.add(proc.pid)
                            mem = getattr(proc, "usedGpuMemory", None)
                            if mem:
                                used += mem
                            matched = True
                info = pynvml.nvmlDeviceGetMemoryInfo(self._nvml)
                sample["vram_total"] = info.total
                if matched:
                    sample["vram_used"] = used
                # 进程级 VRAM 估算（Windows 兜底）：以整机显存滚动窗口做瞬峰归因。
                # 先把整机显存用量记入窗口，再取「瞬峰值 - 平均正常值」作为本进程估算占用。
                if self._estimate_vram:
                    sample["vram_device_used"] = info.used
                    self._vram_window.append(info.used)
                    if len(self._vram_window) >= 3:
                        baseline, peak = _vram_baseline_peak(list(self._vram_window))
                        sample["vram_estimate"] = max(0, peak - baseline)
            except Exception:  # noqa: BLE001
                pass
        return sample

    def _sample_system(self) -> dict:
        """采一帧：系统 CPU% / 内存%(used,total) / 磁盘 IO 速率 / 可选显存。"""
        now = time.time()
        sample: dict[str, Any] = {"ts": now, "scope": "system"}
        sample["cpu_percent"] = psutil.cpu_percent()
        vm = psutil.virtual_memory()
        sample["mem_percent"] = vm.percent
        sample["mem_used"] = vm.used
        sample["mem_total"] = vm.total
        sample["io_read_rate"] = None
        sample["io_write_rate"] = None
        cur = psutil.disk_io_counters()
        if cur is not None and self._disk_prev is not None:
            dt = now - self._disk_ts
            if dt > 0:
                sample["io_read_rate"] = (cur.read_bytes - self._disk_prev.read_bytes) / dt
                sample["io_write_rate"] = (cur.write_bytes - self._disk_prev.write_bytes) / dt
        self._disk_prev = cur
        self._disk_ts = now
        sample["vram_used"] = None
        sample["vram_total"] = None
        if self._nvml is not None:
            try:
                info = pynvml.nvmlDeviceGetMemoryInfo(self._nvml)
                sample["vram_used"] = info.used
                sample["vram_total"] = info.total
            except Exception:  # noqa: BLE001
                pass
        return sample

    # ---- 只读产出口（无参） ----

    def latest(self) -> Optional[dict]:
        with self._lock:
            return self._buffer[-1] if self._buffer else None

    def history(self) -> list[dict]:
        with self._lock:
            return list(self._buffer)

    def count(self) -> int:
        with self._lock:
            return len(self._buffer)

    def stop(self) -> None:
        self._stop.set()

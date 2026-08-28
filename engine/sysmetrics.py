"""P.A.L.M · 系统指标采集（纯标准库，Windows 优先，Linux 兜底）。

仅依赖标准库 + ctypes，不引入 psutil / pywin32 / wmi，保证 engine/.venv
(Python 3.10) 可直接 import。

对外接口：
  collect_metrics() -> dict   结构匹配前端 PerfSnapshot
  collect_modules(sandbox_enabled: bool) -> list[dict]

采集策略：
  - CPU 使用率 / 网络速率需要前后两次采样的差值，因此模块加载时启动一个
    daemon 后台线程每 1.0s 采样一次，结果缓存到模块级变量。
  - collect_metrics() 直接读缓存，HTTP 请求零阻塞、零 sleep。
  - 任何 ctypes / 平台调用失败都降级为 N/O（与前端占位一致），绝不抛异常。
"""

from __future__ import annotations

import os
import platform
import threading
import time

# ---------------------------------------------------------------------------
# 跨平台探测
# ---------------------------------------------------------------------------
_IS_WIN = os.name == "nt"

# 模块级缓存（后台采样线程写入，collect_metrics 读取）
_cache = {
    "cpu_usage": 0.0,
    "net_rx_mbps": 0.0,   # 下行 (接收)
    "net_tx_mbps": 0.0,   # 上行 (发送)
    "cpu_model": "N/O",
    "cpu_base_freq": "N/O",
    "cpu_current_freq": "N/O",
    "mem_total": 0,
    "mem_available": 0,
    "mem_usage": 0,
    "mem_speed": 0,
    "gpus": [{"model": "N/O", "usage": 0}],
    "disks": [],
}
_cache_lock = threading.Lock()


def _na() -> dict:
    """完全降级时的指标（无 ctypes / 未知平台）。"""
    return {
        "cpu": {"model": "N/O", "baseFreq": "N/O", "currentFreq": "N/O",
                "usage": 0, "temperature": 0},
        "memory": {"speed": 0, "total": 0, "available": 0, "usage": 0},
        "gpus": [{"model": "N/O", "usage": 0}],
        "network": {"uploadSpeed": 0, "downloadSpeed": 0},
        "disks": [{"mount": "N/O", "total": 0, "used": 0}],
    }


# ===========================================================================
# Windows 实现（ctypes）
# ===========================================================================
def _collect_windows():
    import ctypes
    import ctypes.wintypes

    k32 = ctypes.windll.kernel32

    # ---- CPU 型号 / 基础频率（注册表，只读一次） ----
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
        try:
            model = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
        except OSError:
            model = "N/O"
        try:
            mhz = winreg.QueryValueEx(key, "~MHz")[0]
            base_freq = "%.2f GHz" % (mhz / 1000.0)
        except OSError:
            base_freq = "N/O"
        winreg.CloseKey(key)
    except Exception:
        model, base_freq = "N/O", "N/O"
    current_freq = base_freq  # 无标准库接口拿实时频率，近似基础频率

    # ---- 内存 ----
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_uint),
            ("dwMemoryLoad", ctypes.c_uint),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    mem = MEMORYSTATUSEX()
    mem.dwLength = ctypes.sizeof(mem)
    mem_total = mem_avail = mem_usage = mem_speed = 0
    try:
        if k32.GlobalMemoryStatusEx(ctypes.byref(mem)):
            mem_total = mem.ullTotalPhys
            mem_avail = mem.ullAvailPhys
            mem_usage = mem.dwMemoryLoad
    except Exception:
        pass

    # ---- 磁盘（仅固定盘） ----
    disks = []
    try:
        mask = k32.GetLogicalDrives()
        free = ctypes.c_ulonglong()
        total = ctypes.c_ulonglong()
        totfree = ctypes.c_ulonglong()
        for i in range(26):
            if not (mask & (1 << i)):
                continue
            letter = chr(ord("A") + i)
            drive = letter + ":\\"
            try:
                dtype = k32.GetDriveTypeW(ctypes.c_wchar_p(drive))
            except Exception:
                dtype = 0
            if dtype != 3:  # DRIVE_FIXED
                continue
            try:
                if k32.GetDiskFreeSpaceExW(
                        ctypes.c_wchar_p(drive),
                        ctypes.byref(free), ctypes.byref(total),
                        ctypes.byref(totfree)):
                    t = total.value
                    used = t - totfree.value
                    if t > 0:
                        disks.append({"mount": letter + ":", "total": t,
                                      "used": used})
            except Exception:
                continue
    except Exception:
        pass

    # ---- GPU（best-effort：注册表 Display 类驱动名） ----
    gpus = []
    try:
        import winreg
        base = (r"SYSTEM\CurrentControlSet\Control\Class"
                r"\{4d36e968-e325-11ce-bfc1-08002be10318}")
        for idx in range(10):
            sub = "%s\\%04d" % (base, idx)
            try:
                gk = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, sub)
                try:
                    name = winreg.QueryValueEx(gk, "DriverDesc")[0].strip()
                except OSError:
                    name = None
                winreg.CloseKey(gk)
                if name:
                    gpus.append({"model": name, "usage": 0})
            except OSError:
                continue
    except Exception:
        pass
    if not gpus:
        gpus = [{"model": "N/O", "usage": 0}]

    return {
        "cpu_model": model,
        "cpu_base_freq": base_freq,
        "cpu_current_freq": current_freq,
        "mem_total": mem_total,
        "mem_available": mem_avail,
        "mem_usage": mem_usage,
        "mem_speed": mem_speed,
        "gpus": gpus,
        "disks": disks,
    }


# ---- CPU 使用率 / 网络速率：需要前后采样差值（后台线程） ----
_win_state = {
    "prev_idle": None, "prev_sys": None, "prev_ts": None,
    "prev_in": None, "prev_out": None,
}


def _win_sample_once():
    import ctypes
    k32 = ctypes.windll.kernel32
    iphlp = ctypes.windll.iphlpapi

    # CPU 时间
    idle = ctypes.wintypes.FILETIME()
    kernel = ctypes.wintypes.FILETIME()
    user = ctypes.wintypes.FILETIME()
    try:
        k32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel),
                           ctypes.byref(user))
        idle_ns = (idle.dwHighDateTime << 32) | idle.dwLowDateTime
        # kernel 时间已包含 idle
        sys_ns = ((kernel.dwHighDateTime << 32) | kernel.dwLowDateTime) + \
                 ((user.dwHighDateTime << 32) | user.dwLowDateTime)
    except Exception:
        idle_ns = sys_ns = None

    # 网络累计字节（所有 Up 接口）
    in_oct = out_oct = 0
    try:
        size = ctypes.c_uint(0)
        iphlp.GetIfTable(None, ctypes.byref(size), 0)
        buf = ctypes.create_string_buffer(size.value)
        if iphlp.GetIfTable(buf, ctypes.byref(size), 0) == 0:
            import struct
            num = struct.unpack_from("<I", buf)[0]
            row_size = 1160  # sizeof(MIB_IFROW)
            for i in range(num):
                row = buf[4 + i * row_size: 4 + (i + 1) * row_size]
                oper = struct.unpack_from("<I", row, 544)[0]
                if oper != 1:  # IfOperStatusUp
                    continue
                in_oct += struct.unpack_from("<Q", row, 552)[0]
                out_oct += struct.unpack_from("<Q", row, 600)[0]
    except Exception:
        in_oct = out_oct = 0

    now = time.time()

    # CPU 使用率
    cpu_usage = _win_state.get("cpu_usage", 0.0)
    if _win_state["prev_idle"] is not None and idle_ns is not None and \
            sys_ns > _win_state["prev_sys"]:
        idle_d = idle_ns - _win_state["prev_idle"]
        sys_d = sys_ns - _win_state["prev_sys"]
        cpu_usage = max(0.0, min(100.0, (1.0 - idle_d / sys_d) * 100.0))
    _win_state["prev_idle"] = idle_ns
    _win_state["prev_sys"] = sys_ns

    # 网络速率 (MB/s)
    rx = tx = 0.0
    if _win_state["prev_in"] is not None and \
            _win_state["prev_ts"] is not None:
        dt = now - _win_state["prev_ts"]
        if dt > 0:
            rx = max(0.0, (in_oct - _win_state["prev_in"]) / 1e6 / dt)
            tx = max(0.0, (out_oct - _win_state["prev_out"]) / 1e6 / dt)
    _win_state["prev_in"] = in_oct
    _win_state["prev_out"] = out_oct
    _win_state["prev_ts"] = now

    return cpu_usage, rx, tx


# ===========================================================================
# Linux / 其它：/proc 兜底（尽力而为）
# ===========================================================================
def _collect_linux():
    info = {
        "cpu_model": "N/O", "cpu_base_freq": "N/O",
        "cpu_current_freq": "N/O",
        "mem_total": 0, "mem_available": 0, "mem_usage": 0, "mem_speed": 0,
        "gpus": [{"model": "N/O", "usage": 0}], "disks": [],
    }
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.lower().startswith("model name"):
                    info["cpu_model"] = line.split(":", 1)[1].strip()
                    break
    except Exception:
        pass
    try:
        with open("/proc/meminfo") as f:
            m = {}
            for line in f:
                k, _, v = line.partition(":")
                m[k.strip()] = int(v.split()[0]) * 1024  # KB -> bytes
            info["mem_total"] = m.get("MemTotal", 0)
            info["mem_available"] = m.get("MemAvailable", m.get("MemFree", 0))
            if info["mem_total"]:
                info["mem_usage"] = round(
                    (info["mem_total"] - info["mem_available"]) /
                    info["mem_total"] * 100.0, 1)
    except Exception:
        pass
    try:
        import shutil
        for mp, total, used, free in shutil.disk_usage_walk("/") if False else []:
            pass
    except Exception:
        pass
    # 磁盘：简单列举根与常见挂载
    for mp in ["/", "/home", "/data"]:
        try:
            st = os.statvfs(mp)
            total = st.f_blocks * st.f_frsize
            free = st.f_bfree * st.f_frsize
            if total > 0:
                info["disks"].append(
                    {"mount": mp, "total": total, "used": total - free})
        except Exception:
            continue
    return info


_linux_state = {"prev_idle": 0, "prev_total": 0, "prev_in": None,
                "prev_out": None, "prev_ts": None}


def _linux_sample_once():
    cpu_usage = 0.0
    try:
        with open("/proc/stat") as f:
            parts = f.readline().split()
        nums = [int(x) for x in parts[1:]]
        idle = nums[3]
        total = sum(nums)
        if _linux_state["prev_total"]:
            d_idle = idle - _linux_state["prev_idle"]
            d_total = total - _linux_state["prev_total"]
            if d_total > 0:
                cpu_usage = max(0.0, min(100.0,
                                 (1.0 - d_idle / d_total) * 100.0))
        _linux_state["prev_idle"] = idle
        _linux_state["prev_total"] = total
    except Exception:
        pass
    rx = tx = 0.0
    try:
        in_oct = out_oct = 0
        with open("/proc/net/dev") as f:
            for line in f.readlines()[2:]:
                cols = line.split(":", 1)[1].split()
                in_oct += int(cols[0])
                out_oct += int(cols[8])
        now = time.time()
        if _linux_state["prev_in"] is not None and \
                _linux_state["prev_ts"] is not None:
            dt = now - _linux_state["prev_ts"]
            if dt > 0:
                rx = max(0.0, (in_oct - _linux_state["prev_in"]) / 1e6 / dt)
                tx = max(0.0, (out_oct - _linux_state["prev_out"]) / 1e6 / dt)
        _linux_state["prev_in"] = in_oct
        _linux_state["prev_out"] = out_oct
        _linux_state["prev_ts"] = now
    except Exception:
        pass
    return cpu_usage, rx, tx


# ===========================================================================
# 后台采样线程
# ===========================================================================
def _sample_loop():
    while True:
        try:
            if _IS_WIN:
                cpu_usage, rx, tx = _win_sample_once()
            else:
                cpu_usage, rx, tx = _linux_sample_once()
            with _cache_lock:
                _cache["cpu_usage"] = round(cpu_usage, 1)
                _cache["net_rx_mbps"] = round(rx, 2)
                _cache["net_tx_mbps"] = round(tx, 2)
        except Exception:
            pass
        time.sleep(1.0)


def _init_static():
    """只读一次、不随时间变化的字段（型号/内存总量等）。"""
    try:
        if _IS_WIN:
            static = _collect_windows()
        else:
            static = _collect_linux()
        with _cache_lock:
            for k, v in static.items():
                _cache[k] = v
    except Exception:
        pass


# ===========================================================================
# 对外接口
# ===========================================================================
def collect_metrics() -> dict:
    with _cache_lock:
        c = dict(_cache)
    return {
        "cpu": {
            "model": c["cpu_model"],
            "baseFreq": c["cpu_base_freq"],
            "currentFreq": c["cpu_current_freq"],
            "usage": c["cpu_usage"],
            "temperature": 0,  # Windows 无标准库温度接口
        },
        "memory": {
            "speed": c["mem_speed"],
            "total": c["mem_total"],
            "available": c["mem_available"],
            "usage": c["mem_usage"],
        },
        "gpus": c["gpus"],
        "network": {
            "uploadSpeed": c["net_tx_mbps"],
            "downloadSpeed": c["net_rx_mbps"],
        },
        "disks": c["disks"],
    }


def collect_modules(sandbox_enabled: bool = False) -> list:
    """返回 P.A.L.M 引擎组件状态数组（前端 useModuleStatus 期望 ModuleEntry[]）。

    仅报告 web.py 引擎真实掌握的状态；其它桌面端组件（asr/tts/agent 等）
    未接入引擎心跳，诚实标为 offline。
    """
    modules = [
        {"id": "engine", "name": "P.A.L.M 引擎", "status": "online",
         "description": "后端 web.py 运行中 (:%d)" % 8080},
        {"id": "console-api", "name": "控制台 API", "status": "online",
         "description": "/api/metrics 与 /api/modules 已上线"},
        {"id": "sandbox", "name": "代码沙箱",
         "status": "online" if sandbox_enabled else "offline",
         "description": "沙箱隔离" if sandbox_enabled else
         "未启用 (启动时加 --sandbox)"},
        {"id": "net-filter", "name": "网络拦截",
         "status": "online" if sandbox_enabled else "offline",
         "description": "网络访问控制" if sandbox_enabled else "未启用"},
        {"id": "honeypot", "name": "蜜罐审计",
         "status": "online" if sandbox_enabled else "offline",
         "description": "诱捕与审计" if sandbox_enabled else "未启用"},
        {"id": "agent", "name": "Agent", "status": "offline",
         "description": "未接入引擎心跳"},
        {"id": "asr", "name": "语音识别", "status": "offline",
         "description": "未接入引擎心跳"},
        {"id": "tts", "name": "语音播报", "status": "offline",
         "description": "未接入引擎心跳"},
        {"id": "dashboard", "name": "仪表盘", "status": "offline",
         "description": "未接入引擎心跳"},
        {"id": "wallpaper", "name": "壁纸引擎", "status": "offline",
         "description": "未接入引擎心跳"},
        {"id": "dock", "name": "Dock 栏", "status": "offline",
         "description": "未接入引擎心跳"},
    ]
    return modules


# ---------------------------------------------------------------------------
# 模块加载即初始化：静态字段 + 启动采样线程
# ---------------------------------------------------------------------------
try:
    _init_static()
    _t = threading.Thread(target=_sample_loop, daemon=True)
    _t.start()
except Exception:
    pass

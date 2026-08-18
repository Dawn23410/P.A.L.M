"""后端统一采集层：后台线程按间隔读系统指标，写入线程安全快照。

设计要点：
- 只采一次、前端按刷新频率取快照，避免每窗重复 syscall。
- 支持两种取数方式：① 轮询 snapshot()（PALM.onTick）；② 订阅 subscribe()（PALM.on），
  仅当 provider 值变化时才推送，节省逐窗 evaluate_js 开销。
- 无模拟数据：psutil/soundcard 缺失时对应 provider 返回 None，前端显示 N/O。
- 音频采集走独立线程（~30fps），系统指标走主循环（0.5s），各自频率一致。
"""

import ctypes.util
import datetime
import json
import logging
import os
import socket
import threading
import time

from palm_sdk.net import get  # 天气等外网请求统一经网卡门面

# --- soundcard 兼容补丁 ---
# 某些 Python 发行版（如 TRAE 内置）的 ctypes.util.find_library 无法按名找到系统 DLL，
# 但全路径加载可行。此处补丁使 find_library 回退到 System32 全路径。
_orig_find = ctypes.util.find_library


def _patched_find(name):
    result = _orig_find(name)
    if result:
        return result
    sysroot = os.environ.get("SystemRoot", r"C:\Windows")
    candidate = os.path.join(sysroot, "System32", name + ".dll")
    return candidate if os.path.exists(candidate) else None


ctypes.util.find_library = _patched_find

LOG = logging.getLogger("palm.providers")

# 音频频率映射常量
_AUDIO_BARS = 24
_AUDIO_SAMPLE_RATE = 44100
_AUDIO_FFT_SIZE = 1024
_AUDIO_FPS = 30  # 音频采集帧率


class Providers:
    """系统指标提供器：后台线程周期性采集，对外给快照或订阅推送。"""

    def __init__(self):
        self._snapshot = {}
        self._lock = threading.RLock()
        self._running = False
        self._active = False
        self._psutil = self._load_psutil()
        self._soundcard = self._load_soundcard()
        self._numpy = self._load_numpy()
        self._subscribers = {}
        self._sub_lock = threading.Lock()
        # 天气缓存 + 可配置化（环境变量 WEATHER_LAT/LON/CITY 覆盖默认北京）
        self._weather_cache = None
        self._weather_last_fetch = 0.0
        self._weather_refresh = 600  # 10 分钟刷新一次
        self._weather_config = {
            "lat": float(os.environ.get("WEATHER_LAT", "39.9042")),
            "lon": float(os.environ.get("WEATHER_LON", "116.4074")),
            "city": os.environ.get("WEATHER_CITY", "北京"),
        }
        # 音频采集状态
        self._audio_recorder = None
        self._audio_running = False
        self._audio_started = False  # 按需启动标记

    def set_active(self, active):
        self._active = bool(active)

    @staticmethod
    def _load_psutil():
        try:
            import psutil
            return psutil
        except Exception:
            return None

    @staticmethod
    def _load_soundcard():
        try:
            import soundcard as sc
            return sc
        except Exception:
            return None

    @staticmethod
    def _load_numpy():
        try:
            import numpy as np
            return np
        except Exception:
            return None

    def start(self):
        if self._running:
            return
        self._running = True
        threading.Thread(target=self._collect_loop, daemon=True).start()
        # 音频线程按需启动：仅当有组件订阅 audio 时才拉起，降低空闲 CPU 开销

    def stop(self):
        self._running = False
        self._stop_audio()

    # ---------- 快照与订阅 ----------
    def snapshot(self, name="*"):
        with self._lock:
            if name == "*":
                return json.loads(json.dumps(self._snapshot, default=str))
            value = self._snapshot.get(name)
            return json.loads(json.dumps(value, default=str)) if value is not None else None

    def subscribe(self, provider, callback):
        with self._sub_lock:
            self._subscribers.setdefault(provider, []).append(callback)
        # 音频按需启动：首个 audio 订阅者出现时拉起音频采集线程
        if provider == "audio" and not self._audio_started:
            self._start_audio()
        return lambda: self._unsubscribe(provider, callback)

    def _unsubscribe(self, provider, callback):
        with self._sub_lock:
            lst = self._subscribers.get(provider, [])
            if callback in lst:
                lst.remove(callback)
            # 音频按需停止：最后一个 audio 订阅者离开后停止音频采集
            if provider == "audio" and not lst and self._audio_started:
                self._stop_audio()

    def _notify(self, provider, value):
        payload = json.dumps(value, default=str)
        with self._sub_lock:
            subs = list(self._subscribers.get(provider, []))
        for cb in subs:
            try:
                cb(payload)
            except Exception as exc:
                LOG.debug("订阅回调异常（%s）: %s", provider, exc)

    # ---------- 主采集循环（系统指标，0.5s） ----------
    def _collect_loop(self):
        while self._running:
            if not self._active:
                for _ in range(10):
                    if self._active or not self._running:
                        break
                    time.sleep(0.5)
                continue
            try:
                snap = self._collect_once()
            except Exception as exc:
                LOG.warning("系统指标采集异常（跳过本轮）: %s", exc)
                time.sleep(0.5)
                continue
            changed = {}
            for key, value in snap.items():
                if key not in self._snapshot or self._snapshot[key] != value:
                    changed[key] = value
            # 合并：保留音频线程写入的 audio 字段
            if "audio" in self._snapshot:
                snap["audio"] = self._snapshot["audio"]
            with self._lock:
                self._snapshot = snap
            for key, value in changed.items():
                self._notify(key, value)
            time.sleep(0.5)

    def _collect_once(self):
        now = datetime.datetime.now()
        snap = {
            "time": {
                "hour": now.hour,
                "minute": now.minute,
                "second": now.second,
                "date": now.strftime("%Y-%m-%d"),
                "weekday": now.strftime("%A"),
            },
            "system": {"platform": "Windows", "hostname": socket.gethostname()},
        }
        if self._psutil:
            snap.update(self._collect_real())
        # psutil 缺失时不添加系统指标，前端显示 N/O

        # 天气：带缓存，不超过 _weather_refresh 间隔才发 API 请求
        snap["weather"] = self._collect_weather()

        return snap

    def _collect_real(self):
        p = self._psutil
        battery = p.sensors_battery()
        return {
            "cpu": {"usage": p.cpu_percent(interval=None)},
            "memory": self._gb_dict(p.virtual_memory()),
            "disk": self._gb_dict(p.disk_usage("/")),
            "network": {
                "sent_mb": p.net_io_counters().bytes_sent // (1024 ** 2),
                "recv_mb": p.net_io_counters().bytes_recv // (1024 ** 2),
            },
            "battery": {
                "percent": battery.percent if battery else 100,
                "plugged": battery.power_plugged if battery else True,
            },
        }

    @staticmethod
    def _gb_dict(usage):
        return {
            "percent": usage.percent,
            "used_gb": usage.used // (1024 ** 3),
            "total_gb": usage.total // (1024 ** 3),
        }

    # ---------- 天气采集（带缓存） ----------
    def _collect_weather(self):
        now = time.time()
        if self._weather_cache and (now - self._weather_last_fetch) < self._weather_refresh:
            return self._weather_cache
        # 需要刷新
        try:
            cfg = self._weather_config
            url = (
                "https://api.open-meteo.com/v1/forecast?"
                f"latitude={cfg['lat']}&longitude={cfg['lon']}"
                "&current=temperature_2m,relative_humidity_2m,apparent_temperature,"
                "weather_code,wind_speed_10m&timezone=auto"
            )
            # 经网卡门面转发（外网 GET，默认拒绝未授权主机）。
            resp = get(url, timeout=5)
            resp.raise_for_status()
            j = resp.json()
            c = j.get("current")
            if not c:
                return self._weather_cache  # API 返回异常，保留旧缓存
            data = {
                "t": c.get("temperature_2m"),
                "hum": c.get("relative_humidity_2m"),
                "feels": c.get("apparent_temperature"),
                "code": c.get("weather_code"),
                "wind": c.get("wind_speed_10m"),
                "city": cfg["city"],
            }
            self._weather_cache = data
            self._weather_last_fetch = now
            return data
        except Exception as exc:
            LOG.warning("天气采集失败：%s", exc)
            return self._weather_cache  # 网络失败保留旧缓存，无缓存则 None

    # ---------- 音频采集（独立线程，~30fps） ----------
    def _start_audio(self):
        if not self._soundcard or not self._numpy:
            LOG.info("soundcard/numpy 不可用，音频 provider 返回 None")
            return
        try:
            speaker = self._soundcard.default_speaker()
            mic = self._soundcard.get_microphone(
                id=str(speaker.name), include_loopback=True)
            self._audio_recorder = mic.recorder(samplerate=_AUDIO_SAMPLE_RATE)
            self._audio_recorder.__enter__()
            self._audio_running = True
            self._audio_started = True
            threading.Thread(target=self._audio_loop, daemon=True).start()
            LOG.info("音频采集已启动（扬声器回环：%s）", speaker.name)
        except Exception as exc:
            LOG.warning("音频采集启动失败：%s", exc)
            self._soundcard = None

    def _stop_audio(self):
        self._audio_running = False
        self._audio_started = False
        if self._audio_recorder:
            try:
                self._audio_recorder.__exit__(None, None, None)
            except Exception:
                pass
            self._audio_recorder = None

    def _audio_loop(self):
        np = self._numpy
        interval = 1.0 / _AUDIO_FPS
        while self._audio_running and self._running:
            if not self._active:
                time.sleep(0.5)
                continue
            try:
                data = self._audio_recorder.record(numframes=_AUDIO_FFT_SIZE)
                bars = self._compute_audio_bars(np, data)
                level = int(max(bars)) if bars else 0
                audio_data = {"bars": bars, "level": level}
                with self._lock:
                    self._snapshot["audio"] = audio_data
                self._notify("audio", audio_data)
            except Exception as exc:
                LOG.warning("音频采集异常: %s", exc)
            time.sleep(interval)

    @staticmethod
    def _compute_audio_bars(np, data):
        """24 根对数频率条（20Hz~20kHz），值域 0~100。"""
        # 取左声道（或单声道）
        samples = data[:, 0] if data.ndim > 1 else data
        fft = np.abs(np.fft.rfft(samples))
        fft_len = len(fft)
        bars = []
        for i in range(_AUDIO_BARS):
            # 对数频率映射：20 * 1000^(i/24) ~ 20 * 1000^((i+1)/24)
            f_low = 20.0 * (1000.0 ** (i / _AUDIO_BARS))
            f_high = 20.0 * (1000.0 ** ((i + 1) / _AUDIO_BARS))
            bin_low = max(1, int(f_low * _AUDIO_FFT_SIZE / _AUDIO_SAMPLE_RATE))
            bin_high = max(bin_low + 1, int(f_high * _AUDIO_FFT_SIZE / _AUDIO_SAMPLE_RATE))
            if bin_high > fft_len:
                bin_high = fft_len
            if bin_low >= fft_len:
                bars.append(0)
                continue
            val = float(np.max(fft[bin_low:bin_high]))
            # 归一化：FFT 满幅 = fft_size/2 = 512，加增益 2.0 提高灵敏度
            normalized = min(100, int(val * 200 / _AUDIO_FFT_SIZE))
            bars.append(normalized)
        return bars

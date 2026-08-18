"""看门狗（主板组件）：CPU 主循环心跳监控，卡死检测降级。

对应主板隐喻的 watchdog：主循环（agent 会话）周期性 touch 心跳，
后台检查任务发现超时 → 广播 watchdog.timeout 事件 + 标记 degraded，
供 monitor/BIOS 报告与前端提示。超时只告警降级，不杀进程（主进程即 AI 宿主）。
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable

from .eventbus import WATCHDOG_TIMEOUT, emit as bus_emit

_LOGGER = logging.getLogger(__name__)

# 心跳超时阈值（秒）：超过即判定卡死
_DEFAULT_TIMEOUT = 60.0
# 检查周期（秒）
_CHECK_INTERVAL = 5.0

_heartbeats: dict[str, float] = {}
_states: dict[str, str] = {}          # name -> "alive" / "stalled"
_on_timeout: list[Callable[[str], None]] = []


def register_heartbeat(name: str, timeout: float = _DEFAULT_TIMEOUT) -> None:
    """注册心跳项（启动会话时调用一次）。"""
    _heartbeats[name] = time.time()
    _states[name] = "alive"


def touch(name: str) -> None:
    """心跳打点（主循环每步调用）。未注册项自动注册。"""
    _heartbeats[name] = time.time()
    _states[name] = "alive"


def state(name: str) -> str:
    """查询心跳状态（alive / stalled / unknown）。"""
    if name not in _states:
        return "unknown"
    return _states[name]


def on_timeout(callback: Callable[[str], None]) -> None:
    """注册超时回调（告警/降级处理）。"""
    _on_timeout.append(callback)


async def _check_loop(timeout: float, interval: float) -> None:
    while True:
        await asyncio.sleep(interval)
        now = time.time()
        for name, last in list(_heartbeats.items()):
            if now - last > timeout and _states.get(name) != "stalled":
                _states[name] = "stalled"
                _LOGGER.warning("看门狗：%s 心跳超时（%.0fs 无打点），判定卡死", name, timeout)
                try:
                    bus_emit(WATCHDOG_TIMEOUT, {"name": name, "stalled_for": round(now - last, 1)})
                except Exception:  # noqa: BLE001
                    pass
                for cb in list(_on_timeout):
                    try:
                        cb(name)
                    except Exception:  # noqa: BLE001
                        pass


def start(timeout: float = _DEFAULT_TIMEOUT, interval: float = _CHECK_INTERVAL) -> None:
    """启动看门狗后台任务（应用启动时调用一次）。"""
    try:
        task = asyncio.get_running_loop().create_task(_check_loop(timeout, interval))
        task.set_name("watchdog")
    except RuntimeError:
        _LOGGER.warning("看门狗需在事件循环内启动（uvicorn 环境）；未启动则无卡死检测")

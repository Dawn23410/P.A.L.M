"""砖块传输层（管理芯片的「通讯信道」）：地址即隔离边界。

把「每块砖一个管理芯片 + 可自定义请求地址」工程化为三种传输，同一份砖代码
改 manifest 的 endpoint 即可在「进程内（开发/轻量）」与「隔离（生产/重负载）」
之间切换——正是 LangBot 三进程模型「同代码零配置本地 vs 容器」的核心。

- InProcTransport：进程内直接调用（默认，零开销），覆盖绝大多数内置纯 Python 砖。
- SubprocessTransport：独立子进程 + 本地 socket（提炼自 tts_sovits 的
  launcher.py + client.py），把重 ML/不安全运行时隔离在独立进程，绝不塞进主进程。
- RemoteTransport：tcp://host:port 或 ws:// 远端进程（跨容器/跨机）。

endpoint 约定解析：
  inproc://            -> InProcTransport
  ipc://               -> SubprocessTransport（本机子进程）
  tcp://host:port      -> RemoteTransport
  ws://host:port       -> RemoteTransport
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable

# 经网卡门面出网：localhost 回环由网卡放行，远端按策略裁决（默认拒绝）。
# 主板不持有任何 httpx/requests/urllib 原语——网卡即沙箱拦截器。
from palm_sdk.net import arequest, request

_LOGGER = logging.getLogger(__name__)


def transport_for(endpoint: str) -> type["Transport"]:
    """按 endpoint 协议选择传输实现。"""
    if endpoint.startswith("tcp://") or endpoint.startswith("ws://"):
        return RemoteTransport
    if endpoint.startswith("ipc://"):
        return SubprocessTransport
    return InProcTransport  # inproc:// 及未知协议一律进程内兜底


class Transport(ABC):
    """传输基类：管理芯片与砖逻辑之间的信道。"""

    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint

    @abstractmethod
    async def start(self) -> None:
        """拉起信道（如有子进程/连接）。"""

    @abstractmethod
    async def stop(self) -> None:
        """停止信道并释放资源。"""

    async def dispose(self) -> None:
        """默认等同 stop；派生类可重载做更彻底清理。"""
        await self.stop()

    @abstractmethod
    async def health(self) -> bool:
        """连通性/就绪探测。"""

    @abstractmethod
    async def call(self, method: str, payload: dict) -> Any:
        """调用砖能力 method（路由段），payload 为参数；返回结果。"""

    def usage(self):  # noqa: D401
        """真实用量（best-effort）；基类默认 None，子进程砖可覆盖。"""
        return None


class InProcTransport(Transport):
    """进程内传输：直接调用本地处理器，零序列化/零 IPC 开销。"""

    def __init__(self, endpoint: str, handlers: dict[str, Callable] | None = None) -> None:
        super().__init__(endpoint)
        self.handlers: dict[str, Callable] = handlers or {}

    def register(self, method: str, fn: Callable) -> None:
        self.handlers[method] = fn

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def health(self) -> bool:
        return True

    async def call(self, method: str, payload: dict) -> Any:
        fn = self.handlers.get(method)
        if fn is None:
            raise KeyError(f"inproc 未注册方法 {method}")
        result = fn(**payload)
        if asyncio.iscoroutine(result):
            return await result
        return result


@dataclass
class SubprocessSpec:
    """子进程运行时规格（由砖的 manifest/配置构造）。"""
    cmd_builder: Callable[[int], list[str]]   # port -> 启动命令
    port: int
    cwd: str | None = None                     # 工作目录（相对路径加载模型的运行时须设）
    health_path: str = "/"                     # 就绪探测路径
    readiness_timeout: int = 240               # 就绪等待上限（秒）
    log_path: str | None = None                # stdout/stderr 落盘（排查用）


class SubprocessTransport(Transport):
    """子进程传输（提炼自 tts_sovits launcher.py + client.py）。

    把重运行时隔离在独立进程：start() 拉起、health() 探测连通性、
    stop() 先礼貌退出再强杀、call() 经 HTTP 转发到本地端口。fail-closed：
    不可达直接抛错，不把连接失败伪装成成功。
    """

    def __init__(self, endpoint: str, spec: SubprocessSpec) -> None:
        super().__init__(endpoint)
        self.spec = spec
        self._proc: subprocess.Popen | None = None

    async def start(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            return
        cmd = self.spec.cmd_builder(self.spec.port)
        log_fh = None
        if self.spec.log_path:
            log_fh = open(self.spec.log_path, "a", encoding="utf-8", errors="replace")
        # cwd 关键：GSV api.py 用相对路径加载模型/依赖，必须在其源码根目录拉起。
        self._proc = subprocess.Popen(cmd, cwd=self.spec.cwd, stdout=log_fh, stderr=log_fh)
        await self._probe_ready(self.spec.readiness_timeout)

    async def _probe_ready(self, timeout: int) -> bool:
        url = f"http://127.0.0.1:{self.spec.port}{self.spec.health_path}"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                await arequest("GET", url, timeout=3.0)
            except Exception:  # noqa: BLE001  不可达则重试，直到超时
                await asyncio.sleep(2)
                continue
            return True
        _LOGGER.warning("子进程就绪探测超时（%ss）：%s", timeout, url)
        return False

    async def health(self) -> bool:
        url = f"http://127.0.0.1:{self.spec.port}{self.spec.health_path}"
        try:
            await arequest("GET", url, timeout=5.0)
            return True
        except Exception:  # noqa: BLE001  探测失败即视为不健康
            return False

    async def call(self, method: str, payload: dict) -> Any:
        url = f"http://127.0.0.1:{self.spec.port}{method}"
        try:
            resp = await arequest("POST", url, json=payload, timeout=120.0)
        except Exception as exc:
            raise RuntimeError(f"子进程 {self.endpoint} 不可达：{exc}") from exc
        if resp.status_code == 200:
            return resp.content
        raise RuntimeError(f"子进程 {self.endpoint} 返回 {resp.status_code}：{resp.text[:300]}")

    async def stop(self) -> None:
        if self._proc is None:
            return
        port = self.spec.port
        try:
            # 礼貌请求子进程退出；未实现退出接口则忽略，强杀兜底。
            request("GET", f"http://127.0.0.1:{port}/control",
                    params={"command": "exit"}, timeout=5.0)
        except Exception:  # noqa: BLE001  上游未实现退出接口也强杀兜底
            pass
        if self._proc.poll() is None:
            self._proc.terminate()
        self._proc = None

    def usage(self):
        """子进程真实用量（psutil 可选）。"""
        from .quota import measure_subprocess
        return measure_subprocess(self._proc)


class RemoteTransport(Transport):
    """远端传输：tcp://host:port 或 ws://host:port（http 转发语义）。

    跨容器/跨机部署砖块时使用；本地个人 AI 一般不走此路径（开销与延迟）。
    """

    def __init__(self, endpoint: str) -> None:
        super().__init__(endpoint)
        # 归一：tcp://host:port -> http://host:port；ws://host:port -> http://host:port
        self.base_url = endpoint.replace("tcp://", "http://").replace("ws://", "http://").rstrip("/")

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def health(self) -> bool:
        try:
            await arequest("GET", self.base_url + "/", timeout=5.0)
            return True
        except Exception:  # noqa: BLE001  探测失败即视为不健康
            return False

    async def call(self, method: str, payload: dict) -> Any:
        url = self.base_url + method
        try:
            resp = await arequest("POST", url, json=payload, timeout=120.0)
        except Exception as exc:
            raise RuntimeError(f"远端 {self.endpoint} 不可达：{exc}") from exc
        if resp.status_code == 200:
            return resp.content
        raise RuntimeError(f"远端 {self.endpoint} 返回 {resp.status_code}：{resp.text[:300]}")

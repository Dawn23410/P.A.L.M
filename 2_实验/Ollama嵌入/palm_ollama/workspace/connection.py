"""Ollama 连接探测：多主机 socket 探测规避 IPv4/IPv6 解析差异。

从 brick.py 抽出，因其为独立关注点（连接可达性判断），与路由处理解耦。
"""
from __future__ import annotations

import logging
import socket
from typing import Optional
from urllib.parse import urlparse

from ._net import request  # 主工程在场走门面，独立部署标准库直连


_LOGGER = logging.getLogger(__name__)


def _hosts_for(base_url: str) -> tuple[str, int, list[str]]:
    """解析 base_url，返回 (host, port, 待探测主机列表)。

    针对 localhost / 127.0.0.1 / ::1 做 IPv4 与 IPv6 互探测，规避最常见故障：
    Ollama 默认只监听 127.0.0.1，而 `localhost` 常被解析到 ::1（IPv6），
    直接 GET localhost:11434 会因连不上 ::1 而误报「未运行」。
    """
    p = urlparse(base_url)
    host = p.hostname or "localhost"
    port = p.port or 11434
    if host == "localhost":
        hosts = ["127.0.0.1", "::1", "localhost"]
    elif host == "127.0.0.1":
        hosts = ["127.0.0.1", "::1"]
    elif host in ("::1", "[::1]"):
        hosts = ["::1", "127.0.0.1"]
    else:
        hosts = [host]
    return host, port, hosts


def _is_tcp_up(host: str, port: int, timeout: float = 1.5) -> bool:
    """用标准库 socket 探测端口是否可达。

    不依赖 httpx，因此即使后端环境未安装 httpx，也能正确判断 Ollama 是否在监听。
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _ollama_running(base_url: str) -> tuple[bool, Optional[str], Optional[str]]:
    """返回 (running, version, error)。

    优先用 socket 端口探测（最稳）；端口通后再经网卡门面确认是 Ollama 并取版本
    （localhost 回环由网卡放行）。多主机探测规避 IPv4/IPv6 解析差异。
    """
    _, port, hosts = _hosts_for(base_url)
    error: Optional[str] = None
    version: Optional[str] = None
    for h in hosts:
        if not _is_tcp_up(h, port):
            continue
        # 端口已通：确认是 Ollama 并取版本。
        url = f"http://[{h}]:{port}" if ":" in h else f"http://{h}:{port}"
        try:
            r = request("GET", url + "/", timeout=3.0)
            if r.status_code == 200:
                try:
                    rv = request("GET", url + "/api/version", timeout=3.0)
                    if rv.status_code == 200:
                        version = rv.json().get("version")
                except Exception as exc:
                    _LOGGER.debug("Ollama 版本获取失败: %s", exc)
                return True, version, None
        except Exception as e:  # 调用异常（理论上端口已通，这里兜底）
            error = str(e)
            return True, None, error
    return False, None, error

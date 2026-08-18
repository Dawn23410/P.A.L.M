"""STT 引擎 HTTP 客户端：主进程经此调用独立子进程引擎的 REST 端点。

引擎连不上时统一抛 SttClientError（带中文提示），由 brick.py 捕获后降级返回，
不让引擎故障波及主进程其他功能。
"""
from __future__ import annotations

import httpx

_STT_TIMEOUT = 10.0


class SttClientError(RuntimeError):
    """引擎不可达或返回业务错误。"""


def _post(url: str, path: str, payload: dict | None = None) -> dict:
    if not url:
        raise SttClientError("STT 引擎未配置（STT_API_URL 为空）")
    try:
        resp = httpx.post(url.rstrip("/") + path, json=payload, timeout=_STT_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as exc:
        raise SttClientError(f"STT 引擎请求失败: {exc}") from exc


def fetch_status(upstream_url: str) -> dict | None:
    """探测引擎状态；不可达或尚未配置 URL 时返回 None（不抛错，供状态展示优雅降级）。"""
    if not upstream_url:
        return None
    try:
        resp = httpx.get(upstream_url.rstrip("/") + "/status", timeout=3)
        if resp.status_code != 200:
            return None
        return resp.json()
    except httpx.HTTPError:
        return None


def start_listening(upstream_url: str) -> dict:
    return _post(upstream_url, "/start")


def stop_listening(upstream_url: str) -> dict:
    return _post(upstream_url, "/stop")


def update_keywords(upstream_url: str, keywords: list[str]) -> dict:
    # 引擎端 /keywords 只实现 do_PUT，用 POST 会被 404。
    try:
        resp = httpx.put(
            upstream_url.rstrip("/") + "/keywords",
            json={"keywords": keywords}, timeout=_STT_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as exc:
        raise SttClientError(f"STT 引擎请求失败: {exc}") from exc


def fetch_events(upstream_url: str, after: int) -> list[dict]:
    try:
        resp = httpx.get(
            upstream_url.rstrip("/") + "/events", params={"after": after}, timeout=5
        )
        resp.raise_for_status()
        return resp.json().get("events", [])
    except httpx.HTTPError as exc:
        raise SttClientError(f"STT 事件拉取失败: {exc}") from exc

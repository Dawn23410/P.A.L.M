"""声纹引擎 HTTP 客户端：主进程经此调用独立子进程引擎的 REST 端点。

引擎连不上时统一抛 SpeakerClientError，由 brick.py 捕获后降级返回，
不让引擎故障波及主进程其他功能（与 stt client 一致）。
"""
from __future__ import annotations

import base64
import httpx

_TIMEOUT = 10.0


class SpeakerClientError(RuntimeError):
    """引擎不可达或返回业务错误。"""


def _post(url: str, path: str, payload: dict | None = None) -> dict:
    try:
        resp = httpx.post(url.rstrip("/") + path, json=payload, timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as exc:
        raise SpeakerClientError(f"声纹引擎请求失败: {exc}") from exc


def fetch_status(upstream_url: str) -> dict | None:
    try:
        resp = httpx.get(upstream_url.rstrip("/") + "/status", timeout=3)
        if resp.status_code != 200:
            return None
        return resp.json()
    except httpx.HTTPError:
        return None


def list_speakers(upstream_url: str) -> list[dict]:
    try:
        resp = httpx.get(upstream_url.rstrip("/") + "/list", timeout=_TIMEOUT)
        resp.raise_for_status()
        return resp.json().get("speakers", [])
    except httpx.HTTPError as exc:
        raise SpeakerClientError(f"声纹引擎请求失败: {exc}") from exc


def enroll(upstream_url: str, name: str, wav_path: str) -> dict:
    with open(wav_path, "rb") as fh:
        wav_b64 = base64.b64encode(fh.read()).decode("ascii")
    return _post(upstream_url, "/enroll", {"name": name, "wav_b64": wav_b64})


def identify(upstream_url: str, wav_path: str) -> dict:
    with open(wav_path, "rb") as fh:
        wav_b64 = base64.b64encode(fh.read()).decode("ascii")
    return _post(upstream_url, "/identify", {"wav_b64": wav_b64})


def verify(upstream_url: str, name: str, wav_path: str) -> dict:
    with open(wav_path, "rb") as fh:
        wav_b64 = base64.b64encode(fh.read()).decode("ascii")
    return _post(upstream_url, "/verify", {"name": name, "wav_b64": wav_b64})


def remove(upstream_url: str, name: str) -> dict:
    return _post(upstream_url, "/remove", {"name": name})


def flush_identify(upstream_url: str) -> dict:
    return _post(upstream_url, "/flush_identify", {})

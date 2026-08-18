"""GPT-SoVITS 上游 HTTP 客户端（薄代理，不持有任何模型状态）。

只负责把合成请求转发给已运行的 api.py / api_v2.py 服务，并在不可达时抛出
明确错误，供砖块优雅降级（不把连接失败伪装成成功）。
"""
from __future__ import annotations

import httpx


class TtsClientError(Exception):
    """上游 GPT-SoVITS 服务不可达或返回错误。"""


async def synthesize_speech(payload: dict, upstream_url: str, route: str, timeout: int = 120) -> bytes:
    url = f"{upstream_url.rstrip('/')}{route}"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload)
    except httpx.HTTPError as exc:
        raise TtsClientError(f"GPT-SoVITS 服务不可达（{upstream_url}）：{exc}") from exc
    if resp.status_code == 200:
        return resp.content
    # 上游错误时返回的是 JSON，把原因透出给调用方。
    raise TtsClientError(f"GPT-SoVITS 返回错误 {resp.status_code}：{resp.text[:300]}")


async def check_upstream_health(upstream_url: str, timeout: int = 5) -> bool:
    # 未配置上游（独立态）直接判不可达，避免 None.rstrip 崩溃。
    if not upstream_url:
        return False
    # 仅探测连通性：上游即使因缺参数返回 400，也算“可达”，由合成时再报错。
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            await client.get(upstream_url.rstrip("/") + "/")
        return True
    except httpx.HTTPError:
        return False


async def synthesize_speech_stream(payload: dict, upstream_url: str, route: str,
                                   timeout: int = 300):
    """流式合成：逐块产出上游音频 chunk（api.py -sm normal 的分块 wav）。

    首块含 wav header，后续块为 PCM 数据——调用方（StreamingResponse 透传 /
    语音专线逐句播放）可边收边播，首段延迟 = 上游第一块合成时间而非整段。
    上游不可达/返回错误时抛 TtsClientError（fail-closed，不伪装成功）。
    """
    url = f"{upstream_url.rstrip('/')}{route}"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", url, json=payload) as resp:
                if resp.status_code != 200:
                    body = (await resp.aread()).decode("utf-8", "ignore")[:300]
                    raise TtsClientError(f"GPT-SoVITS 返回错误 {resp.status_code}：{body}")
                async for chunk in resp.aiter_bytes():
                    if chunk:
                        yield chunk
    except httpx.HTTPError as exc:
        raise TtsClientError(f"GPT-SoVITS 服务不可达（{upstream_url}）：{exc}") from exc

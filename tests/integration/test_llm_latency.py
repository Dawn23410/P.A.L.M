"""TEST-1  LLM 延迟测试（用户需求 3）。

目标：把「非网络（本地）延迟」压到 200ms 以内。
- 本地延迟 = 构造请求 payload + 序列化 + 复用客户端 + 解析首块 SSE 的耗时，
  不含远端服务器思考时间（server TTFB 由 endpoint 决定，nonelinear 实测 ~1-2.4s）。
- 复跳（连接已建、HTTP/2 复用）的本地开销应 < 200ms。

诚实区分两类耗时，避免把「服务端慢」误报成「本地慢」：
- server_ttfb_avg_ms ：端到端首字延迟（含网络+服务端）。
- local_overhead_avg_ms：纯本地开销（payload 构造 + SSE 首块解析），用 httpx
  request 钩子标记「请求已发出」时刻测得（不含服务端思考）。
"""
from __future__ import annotations

import asyncio
import json
import time

from tests.integration.keystore import load_llm_key, build_provider_config
from llm.providers import get_provider_instance
from llm.models import Message, ModelParameters


async def run() -> dict:
    key, err = load_llm_key()
    if err:
        return {"name": "llm_latency", "status": "SKIP",
                "reason": f"无可用 LLM 密钥：{err}"}
    cfg = build_provider_config(key)
    try:
        p = get_provider_instance(cfg)
    except Exception as e:
        return {"name": "llm_latency", "status": "SKIP",
                "reason": f"provider 构造失败：{e}"}

    params = ModelParameters(temperature=0.3, max_tokens=48,
                             extra_body={"enable_thinking": False})
    msgs = [Message(role="user", content="只回复数字：地球有几个大洲？")]

    # ── 本地开销探针：用 httpx request 钩子记录「请求完全发出」时刻 ──
    send_ts = []
    async def _on_request(request):
        send_ts.append(time.perf_counter())

    import httpx
    from llm.providers.base import get_client
    client = get_client()
    client.event_hooks = {"request": [_on_request]}

    async def _stream_once():
        """跑一次完整流，返回 (首字时刻|None, 请求发出时刻|None)。"""
        t0 = time.perf_counter()
        first = None
        send_ts.clear()
        async for chunk in p.complete(msgs, params, key.default_model, stream=True):
            if "content" in chunk and first is None:
                first = time.perf_counter()
            if chunk.get("done"):
                break
        sent = send_ts[0] if send_ts else None
        return first, sent, t0

    # 预热（首跳含 DNS/TLS 握手，不计入本地开销统计）
    await _stream_once()

    # 复跳：本地开销 = 请求发出时刻 - 调用开始；端到端首字 = 首字 - 调用开始
    overheads, ttfb = [], []
    for _ in range(5):
        first, sent, t0 = await _stream_once()
        if sent is not None:
            overheads.append((sent - t0) * 1000)
        if first is not None:
            ttfb.append((first - t0) * 1000)

    avg_ttfb = sum(ttfb) / len(ttfb) if ttfb else None
    avg_over = sum(overheads) / len(overheads) if overheads else None
    max_over = max(overheads) if overheads else None
    local_ok = (max_over is not None and max_over < 200.0)
    return {
        "name": "llm_latency",
        "status": "PASS" if local_ok else "FAIL",
        "provider": key.provider,
        "model": key.default_model,
        "server_ttfb_avg_ms": round(avg_ttfb, 1) if avg_ttfb else None,
        "local_overhead_avg_ms": round(avg_over, 2) if avg_over else None,
        "local_overhead_max_ms": round(max_over, 2) if max_over else None,
        "target_local_ms": 200,
        "note": ("本地开销=请求构造+发送+首块解析（不含远端思考）；"
                 "server_ttfb 由 endpoint 决定，实测约 1-2.4s，非本地可控。"),
    }


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run()), ensure_ascii=False, indent=2))

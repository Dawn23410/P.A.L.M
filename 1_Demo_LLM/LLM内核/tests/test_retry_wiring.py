"""异常分类 + 重试策略「真的接在 provider 上」的端到端证明（MockTransport，无网络）。

覆盖：
  - 传输层失败按策略重试：默认档重试 1 次即恢复；max_attempts=1 不重试直接抛
  - 429 → RateLimitError（可重试标记），且不触发降级
  - 已产出内容后中断 → StreamInterruptedError（绝不重试，防重复生成）
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from palm_llm.errors import RateLimitError, StreamInterruptedError, TransportError
from palm_llm.models import Message, ModelParameters, ProviderConfig
from palm_llm.providers import openai_compat as oc
from palm_llm.retry import RetryPolicy

SSE_OK = (
    b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'
    b'data: {"usage":{"completion_tokens":1}}\n\n'
    b'data: [DONE]\n\n'
)


def _cfg(retry=None) -> ProviderConfig:
    return ProviderConfig(name="t", type="openai_compat",
                          base_url="http://example.invalid/v1", api_key="k",
                          retry=retry)


class _Flaky:
    """前 `fail_times` 次抛连接错误（模拟死连接），之后回放成功响应。"""

    def __init__(self, fail_times: int, ok: httpx.Response):
        self.fail_times = fail_times
        self.ok = ok
        self.calls = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise httpx.ConnectError("connection reset")
        return self.ok


class _BoomStream(httpx.AsyncByteStream):
    """先吐一个正文分片，再中途断流（模拟“已产出后中断”）。"""

    async def __aiter__(self):
        yield b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'
        raise httpx.ReadError("mid-stream reset")

    async def aclose(self) -> None:
        pass


class RetryWiringTest(unittest.IsolatedAsyncioTestCase):
    def _patch(self, handler):
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self._orig = oc.get_client
        oc.get_client = lambda: client
        return handler

    def tearDown(self):
        if hasattr(self, "_orig"):
            oc.get_client = self._orig

    async def _collect(self, cfg, **kw):
        prov = oc.OpenAICompatProvider(cfg)
        out = []
        async for ev in prov.complete([Message(role="user", content="hi")],
                                      ModelParameters(), model="m", **kw):
            out.append(ev)
        return out

    async def test_default_policy_retries_once_then_recovers(self):
        """默认（低延迟档，max_attempts=2）：一次死连接后换连接重试即成功。"""
        h = self._patch(_Flaky(1, httpx.Response(200, content=SSE_OK)))
        events = await self._collect(_cfg())
        self.assertEqual(h.calls, 2)                       # 首次失败 + 重试 1 次
        self.assertIn({"content": "hi"}, events)

    async def test_attempts_one_disables_retry(self):
        """max_attempts=1：完全不重试，直接把传输错误按类型抛出。"""
        h = self._patch(_Flaky(1, httpx.Response(200, content=SSE_OK)))
        with self.assertRaises(TransportError) as ctx:
            await self._collect(_cfg(retry=RetryPolicy(max_attempts=1)))
        self.assertEqual(h.calls, 1)
        self.assertTrue(ctx.exception.retryable)

    async def test_stable_policy_allows_more_attempts(self):
        """max_attempts=3：连挂两次仍能恢复（封顶次数来自策略，而非硬编码 2）。"""
        h = self._patch(_Flaky(2, httpx.Response(200, content=SSE_OK)))
        events = await self._collect(_cfg(retry=RetryPolicy(max_attempts=3, base_delay=0.0)))
        self.assertEqual(h.calls, 3)
        self.assertIn({"content": "hi"}, events)

    async def test_429_is_rate_limited_and_not_retried_by_transport(self):
        """429 → RateLimitError（retryable），且传输层不重试、不降级。"""
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(429, json={"error": {"message": "concurrency too high"}})

        self._patch(handler)
        with self.assertRaises(RateLimitError) as ctx:
            await self._collect(_cfg())
        self.assertTrue(ctx.exception.retryable)
        self.assertEqual(ctx.exception.status, 429)
        self.assertEqual(calls["n"], 1)

    async def test_interrupted_after_output_is_not_retried(self):
        """已产出内容后断流 → StreamInterruptedError，绝不重试（防重复计费）。"""
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(200, stream=_BoomStream())

        self._patch(handler)
        with self.assertRaises(StreamInterruptedError) as ctx:
            await self._collect(_cfg(retry=RetryPolicy(max_attempts=3, base_delay=0.0)))
        self.assertFalse(ctx.exception.retryable)
        self.assertEqual(calls["n"], 1)                    # 中断不重试

    async def test_nonstream_failover_retries(self):
        """非流式也要按策略换连接重试（此前漏做：死连接会直接失败而非重试）。"""
        body = {"choices": [{"message": {"content": "hi"}}],
                "usage": {"completion_tokens": 1}}
        h = self._patch(_Flaky(1, httpx.Response(200, json=body)))
        out = await self._collect(_cfg(), stream=False)
        self.assertEqual(h.calls, 2)                       # 首次失败 + 重试 1 次
        self.assertTrue(any("done" in ev for ev in out))

    async def test_nonstream_no_failover_when_disabled(self):
        """max_attempts=1：非流式同样不重试，直接抛出可重试的传输错误。"""
        body = {"choices": [{"message": {"content": "hi"}}], "usage": {}}
        h = self._patch(_Flaky(1, httpx.Response(200, json=body)))
        with self.assertRaises(TransportError):
            await self._collect(_cfg(retry=RetryPolicy(max_attempts=1)), stream=False)
        self.assertEqual(h.calls, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)

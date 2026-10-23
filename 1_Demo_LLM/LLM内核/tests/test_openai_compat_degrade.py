"""通用通道 → 降级通道 的用例（httpx.MockTransport，无需真实网络与 API Key）。

覆盖：
  - 纯逻辑：基础字段白名单、消息降级、可降级错误判定
  - 端到端：完整格式 400 → 自动降级 → 成功；两次都失败 → 抛异常；401 不降级
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from palm_llm.models import Message, ModelParameters, ProviderConfig
from palm_llm.providers import openai_compat as oc

SSE_OK = (
    b'data: {"choices":[{"delta":{"reasoning_content":"think"}}]}\n\n'
    b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'
    b'data: {"choices":[{"delta":{"content":" there"}}]}\n\n'
    b'data: {"usage":{"completion_tokens":2}}\n\n'
    b'data: [DONE]\n\n'
)


class _Recorder:
    """按序回放响应，并记录每次实际收到的请求体。"""

    def __init__(self, *responses: httpx.Response):
        self._responses = list(responses)
        self.payloads: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.payloads.append(json.loads(request.content))
        if not self._responses:
            raise AssertionError("收到了超出预期的请求")
        return self._responses.pop(0)


def _cfg() -> ProviderConfig:
    return ProviderConfig(name="t", type="openai_compat",
                          base_url="http://example.invalid/v1", api_key="k")


def _bad(status: int) -> httpx.Response:
    return httpx.Response(status, json={"error": {"message": "rejected"}})


class DegradeLogicTest(unittest.TestCase):
    def test_downgrade_keeps_only_basic_keys(self):
        payload = {
            "model": "m", "messages": [], "stream": True,
            "temperature": 0.7, "top_p": 1.0, "max_tokens": 8192,
            "reasoning_effort": "high", "tools": [], "stream_options": {},
        }
        out = oc._downgrade(payload)
        self.assertEqual(set(out), set(oc.BASIC_KEYS))

    def test_downgrade_drops_thinking_and_tools(self):
        payload = {"model": "m", "messages": [], "stream": True,
                   "thinking": {"type": "disabled"}, "tool_choice": "auto"}
        out = oc._downgrade(payload)
        self.assertNotIn("thinking", out)
        self.assertNotIn("tool_choice", out)

    def test_plain_messages_flattens_multimodal_blocks(self):
        msgs = [{"role": "user", "content": [{"type": "text", "text": "看图"},
                                             {"type": "image_url",
                                              "image_url": {"url": "data:image/png;base64,x"}}]}]
        self.assertEqual(oc._plain_messages(msgs), [{"role": "user", "content": "看图"}])

    def test_plain_messages_drops_tool_turns(self):
        msgs = [
            {"role": "user", "content": "天气"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "1"}]},
            {"role": "tool", "content": "晴", "tool_call_id": "1"},
        ]
        self.assertEqual(oc._plain_messages(msgs), [{"role": "user", "content": "天气"}])

    def test_degradable_status_set(self):
        for status in (400, 404, 415, 422):
            self.assertTrue(oc._degradable(oc._HttpStatus(status, "x")))
        for status in (401, 403, 429, 500, 503):
            self.assertFalse(oc._degradable(oc._HttpStatus(status, "x")))

    def test_transport_error_is_not_degradable(self):
        self.assertFalse(oc._degradable(httpx.ConnectError("boom")))


class DegradeEndToEndTest(unittest.IsolatedAsyncioTestCase):
    def _patch(self, *responses):
        rec = _Recorder(*responses)
        client = httpx.AsyncClient(transport=httpx.MockTransport(rec))
        self._orig = oc.get_client
        oc.get_client = lambda: client
        return rec

    def tearDown(self):
        if hasattr(self, "_orig"):
            oc.get_client = self._orig

    async def _collect(self, params, stream=True):
        prov = oc.OpenAICompatProvider(_cfg())
        out = []
        async for ev in prov.complete([Message(role="user", content="你好")],
                                      params, model="m", stream=stream):
            out.append(ev)
        return out

    async def test_degrades_to_basic_fields_on_400(self):
        rec = self._patch(_bad(400), httpx.Response(200, content=SSE_OK))
        params = ModelParameters(extra_body={"reasoning_effort": "high"})
        events = await self._collect(params)

        self.assertEqual(len(rec.payloads), 2)
        self.assertIn("reasoning_effort", rec.payloads[0])      # 第一跳给全量
        self.assertNotIn("reasoning_effort", rec.payloads[1])   # 第二跳降级
        self.assertEqual(set(rec.payloads[1]), set(oc.BASIC_KEYS))
        self.assertIn({"reasoning": "think"}, events)
        self.assertIn({"content": "hi"}, events)
        self.assertEqual(events[-1]["usage"], {"completion_tokens": 2})

    async def test_raises_when_degraded_also_fails(self):
        rec = self._patch(_bad(400), _bad(400))
        params = ModelParameters(extra_body={"thinking": {"type": "enabled"}})
        with self.assertRaises(RuntimeError) as ctx:
            await self._collect(params)
        self.assertEqual(len(rec.payloads), 2)                  # 只降级一次
        self.assertIn("已降级", str(ctx.exception))

    async def test_no_degrade_on_401(self):
        rec = self._patch(_bad(401))
        with self.assertRaises(RuntimeError) as ctx:
            await self._collect(ModelParameters())
        self.assertEqual(len(rec.payloads), 1)                  # 鉴权错误不降级
        self.assertNotIn("已降级", str(ctx.exception))

    async def test_plain_request_degrades_too(self):
        body = json.dumps({"choices": [{"message": {"content": "ok"}}],
                           "usage": {"completion_tokens": 1}}).encode()
        rec = self._patch(_bad(422), httpx.Response(200, content=body))
        events = await self._collect(ModelParameters(extra_body={"enable_thinking": True}),
                                     stream=False)
        self.assertEqual(len(rec.payloads), 2)
        self.assertIn({"content": "ok"}, events)

    async def test_done_event_carries_normalized_stats(self):
        """done 帧必须带 stats（回传拆分器归一结果），同时 usage 原样保留。"""
        body = (
            b'data: {"id":"cmpl-1","model":"m","choices":[{"delta":{"reasoning_content":"t"}}]}\n\n'
            b'data: {"choices":[{"delta":{"content":"hello"}}]}\n\n'
            b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
            b'data: {"usage":{"prompt_tokens":10,"completion_tokens":2,'
            b'"prompt_tokens_details":{"cached_tokens":8}}}\n\n'
            b'data: [DONE]\n\n')
        self._patch(httpx.Response(200, content=body))
        events = await self._collect(ModelParameters())
        done = events[-1]
        self.assertEqual(done["usage"]["completion_tokens"], 2)   # 原始字段照旧
        stats = done["stats"]
        self.assertEqual(stats["input_tokens"], 2)                # 10-8，缓存被拆出来
        self.assertEqual(stats["cache_read_tokens"], 8)
        self.assertEqual(stats["output_tokens"], 2)
        self.assertEqual(stats["finish_reason"], "stop")
        self.assertEqual(stats["reasoning_text"], "t")
        self.assertEqual(stats["content_text"], "hello")
        self.assertEqual(stats["extra"]["response_id"], "cmpl-1")


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Anthropic 原生通道用例（httpx.MockTransport，无需真实网络与 Key）。

覆盖：
  - 载荷形状：system 外提、max_tokens 必填、tools → input_schema、tool_choice 映射
  - 思考配置：adaptive 锁死、adaptive 模型不带 budget_tokens、老模型补 budget、省略采样参数
  - 消息转换：role="tool" → user+tool_result、连续同角色合并、图片 → base64 块
  - 流式：块级事件 → 内核事件、思考签名留存、工具参数分片拼接
  - 非流式与错误体解包
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from palm_llm.models import Message, ModelParameters, ProviderConfig, Tool
from palm_llm.providers import anthropic as ap

DATA_URI = "data:image/png;base64,QUJD"


def _sse(*events: dict) -> bytes:
    """按 SSE 格式拼包（用 JSON 拼而非字节字面量 —— 中文没法写进 bytes literal）。"""
    return "".join(f"data: {json.dumps(e, ensure_ascii=False)}\n\n"
                   for e in events).encode("utf-8")


SSE_TEXT = _sse(
    {"type": "message_start",
     "message": {"id": "msg_1", "model": "claude-opus-4-8",
                 "usage": {"input_tokens": 25, "cache_read_input_tokens": 900,
                           "cache_creation_input_tokens": 0, "output_tokens": 1}}},
    {"type": "content_block_start", "index": 0,
     "content_block": {"type": "thinking", "thinking": ""}},
    {"type": "content_block_delta", "index": 0,
     "delta": {"type": "thinking_delta", "thinking": "先想"}},
    {"type": "content_block_delta", "index": 0,
     "delta": {"type": "signature_delta", "signature": "SIG1"}},
    {"type": "content_block_stop", "index": 0},
    {"type": "content_block_start", "index": 1,
     "content_block": {"type": "text", "text": ""}},
    {"type": "content_block_delta", "index": 1,
     "delta": {"type": "text_delta", "text": "你好"}},
    {"type": "message_delta",
     "delta": {"stop_reason": "end_turn", "stop_sequence": None},
     "usage": {"output_tokens": 42}},
    {"type": "message_stop"},
)

SSE_TOOL = _sse(
    {"type": "message_start",
     "message": {"id": "msg_2", "model": "claude-opus-4-8",
                 "usage": {"input_tokens": 10, "output_tokens": 1}}},
    {"type": "content_block_start", "index": 0,
     "content_block": {"type": "tool_use", "id": "toolu_9",
                       "name": "get_weather", "input": {}}},
    {"type": "content_block_delta", "index": 0,
     "delta": {"type": "input_json_delta", "partial_json": '{"city":'}},
    {"type": "content_block_delta", "index": 0,
     "delta": {"type": "input_json_delta", "partial_json": '"上海"}'}},
    {"type": "content_block_stop", "index": 0},
    {"type": "message_delta", "delta": {"stop_reason": "tool_use"},
     "usage": {"output_tokens": 18}},
    {"type": "message_stop"},
)


def _cfg(model_type: str = "anthropic") -> ProviderConfig:
    return ProviderConfig(name="claude", type=model_type,
                          base_url="https://api.anthropic.com", api_key="sk-ant")


class _Recorder:
    def __init__(self, *responses: httpx.Response):
        self._responses = list(responses)
        self.payloads: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.payloads.append(json.loads(request.content))
        if not self._responses:
            raise AssertionError("收到了超出预期的请求")
        return self._responses.pop(0)


class PayloadShapeTest(unittest.IsolatedAsyncioTestCase):
    def _patch(self, *responses):
        rec = _Recorder(*responses)
        client = httpx.AsyncClient(transport=httpx.MockTransport(rec))
        self._orig = ap.get_client
        ap.get_client = lambda: client
        return rec

    def tearDown(self):
        if hasattr(self, "_orig"):
            ap.get_client = self._orig

    async def _payload(self, messages, params, model="claude-opus-4-8"):
        prov = ap.AnthropicProvider(_cfg())
        return await prov._build_payload(messages, params, model, True)

    async def test_system_is_hoisted_and_max_tokens_present(self):
        body = await self._payload(
            [Message(role="system", content="你是助手"),
             Message(role="user", content="嗨")],
            ModelParameters(max_tokens=4096))
        self.assertEqual(body["system"], "你是助手")          # 顶层，不在 messages 里
        self.assertEqual(body["max_tokens"], 4096)
        self.assertEqual([m["role"] for m in body["messages"]], ["user"])
        self.assertNotIn("system", [m["role"] for m in body["messages"]])

    async def test_adaptive_model_gets_adaptive_without_budget(self):
        """Opus4.7+ 必须 adaptive，且带 budget_tokens 会 400。"""
        body = await self._payload([Message(role="user", content="hi")],
                                   ModelParameters(max_tokens=8192))
        self.assertEqual(body["thinking"], {"type": "adaptive"})
        self.assertNotIn("budget_tokens", body["thinking"])
        self.assertNotIn("temperature", body)     # 思考模式下采样参数一律省略
        self.assertNotIn("top_p", body)

    async def test_adaptive_model_accepts_effort(self):
        body = await self._payload([Message(role="user", content="hi")],
                                   ModelParameters(extra_body={"reasoning_effort": "xhigh"}))
        self.assertEqual(body["thinking"]["output_config"]["effort"], "xhigh")

    async def test_legacy_model_fills_budget_tokens(self):
        """老代模型走 enabled，必须补 budget_tokens，且要小于 max_tokens。"""
        body = await self._payload([Message(role="user", content="hi")],
                                   ModelParameters(max_tokens=4096,
                                                   extra_body={"thinking": True}),
                                   model="claude-sonnet-4-5-20250929")
        self.assertEqual(body["thinking"]["type"], "enabled")
        self.assertLess(body["thinking"]["budget_tokens"], 4096)

    async def test_plain_model_keeps_sampling_params(self):
        body = await self._payload([Message(role="user", content="hi")],
                                   ModelParameters(temperature=0.3, top_p=0.8),
                                   model="claude-haiku-4-5")
        self.assertEqual(body["temperature"], 0.3)
        self.assertEqual(body["top_p"], 0.8)

    async def test_tools_use_input_schema(self):
        body = await self._payload(
            [Message(role="user", content="天气")],
            ModelParameters(tools=[Tool(name="get_weather", description="查天气",
                                        parameters={"type": "object"})],
                            tool_choice="required"))
        self.assertEqual(body["tools"][0]["name"], "get_weather")
        self.assertIn("input_schema", body["tools"][0])
        self.assertNotIn("parameters", body["tools"][0])
        self.assertEqual(body["tool_choice"], {"type": "any"})   # 原生没有 required

    async def test_tool_result_becomes_user_block(self):
        body = await self._payload(
            [Message(role="user", content="天气"),
             Message(role="assistant", content="", tool_calls=[
                 {"id": "toolu_1", "type": "function",
                  "function": {"name": "get_weather", "arguments": '{"city":"上海"}'}}]),
             Message(role="tool", content="晴", tool_call_id="toolu_1")],
            ModelParameters())
        roles = [m["role"] for m in body["messages"]]
        self.assertEqual(roles, ["user", "assistant", "user"])
        self.assertEqual(body["messages"][1]["content"][0]["type"], "tool_use")
        self.assertEqual(body["messages"][1]["content"][0]["input"], {"city": "上海"})
        self.assertEqual(body["messages"][2]["content"][0]["type"], "tool_result")

    async def test_consecutive_same_role_is_merged(self):
        """Anthropic 要求严格交替，连续同角色必须合并。"""
        body = await self._payload(
            [Message(role="tool", content="A", tool_call_id="1"),
             Message(role="tool", content="B", tool_call_id="2")],
            ModelParameters())
        self.assertEqual(len(body["messages"]), 1)
        self.assertEqual(len(body["messages"][0]["content"]), 2)

    async def test_image_becomes_base64_block(self):
        body = await self._payload([Message(role="user", content="看图", images=[DATA_URI])],
                                   ModelParameters())
        blocks = body["messages"][0]["content"]
        self.assertEqual(blocks[1]["type"], "image")
        self.assertEqual(blocks[1]["source"]["media_type"], "image/png")
        self.assertEqual(blocks[1]["source"]["data"], "QUJD")

    async def test_url_is_not_rewritten(self):
        prov = ap.AnthropicProvider(_cfg())
        self.assertEqual(prov._url(), "https://api.anthropic.com/v1/messages")
        prov.cfg.base_url = "https://api.anthropic.com/v1"
        self.assertEqual(prov._url(), "https://api.anthropic.com/v1/messages")
        prov.cfg.base_url = "https://api.anthropic.com/v1/messages"
        self.assertEqual(prov._url(), "https://api.anthropic.com/v1/messages")

    async def test_headers_use_api_key_and_version(self):
        prov = ap.AnthropicProvider(_cfg())
        headers = prov._headers()
        self.assertEqual(headers["x-api-key"], "sk-ant")
        self.assertEqual(headers["anthropic-version"], "2023-06-01")
        self.assertNotIn("Authorization", headers)


class StreamTest(unittest.IsolatedAsyncioTestCase):
    def _patch(self, *responses):
        rec = _Recorder(*responses)
        client = httpx.AsyncClient(transport=httpx.MockTransport(rec))
        self._orig = ap.get_client
        ap.get_client = lambda: client
        return rec

    def tearDown(self):
        if hasattr(self, "_orig"):
            ap.get_client = self._orig

    async def _collect(self, *responses, stream=True, params=None, model="claude-opus-4-8"):
        self._patch(*responses)
        prov = ap.AnthropicProvider(_cfg())
        out = []
        async for ev in prov.complete([Message(role="user", content="你好")],
                                      params or ModelParameters(), model=model,
                                      stream=stream):
            out.append(ev)
        return out

    async def test_stream_maps_blocks_to_events(self):
        events = await self._collect(httpx.Response(200, content=SSE_TEXT))
        self.assertEqual([e.get("reasoning") for e in events if "reasoning" in e], ["先想"])
        self.assertEqual([e.get("content") for e in events if "content" in e], ["你好"])
        done = events[-1]
        self.assertTrue(done["done"])
        self.assertEqual(done["usage"]["output_tokens"], 42)
        # 缓存命中是原生字段，stats 里必须能读到
        self.assertEqual(done["stats"]["cache_read_tokens"], 900)
        self.assertEqual(done["stats"]["input_tokens"], 25)
        self.assertEqual(done["stats"]["output_tokens"], 42)
        self.assertEqual(done["stats"]["total_tokens"], 967)     # 25+900+0+42
        self.assertEqual(done["stats"]["finish_reason"], "stop")  # end_turn → stop
        self.assertEqual(done["stats"]["extra"]["thinking_signature"], "SIG1")
        self.assertEqual(done["stats"]["content_text"], "你好")
        self.assertGreater(done["stats"]["ttft_ms"], 0)

    async def test_stream_accumulates_tool_arguments(self):
        events = await self._collect(httpx.Response(200, content=SSE_TOOL))
        deltas = [e["tool_call_delta"] for e in events if "tool_call_delta" in e]
        self.assertEqual(deltas[0]["name"], "get_weather")       # 拿到名字即下发
        calls = [e for e in events if "tool_calls" in e][0]["tool_calls"]
        self.assertEqual(json.loads(calls[0]["function"]["arguments"]), {"city": "上海"})
        self.assertEqual(events[-1]["stats"]["finish_reason"], "tool_calls")

    async def test_non_stream_parses_content_blocks(self):
        body = json.dumps({
            "id": "msg_3", "type": "message", "model": "claude-opus-4-8",
            "content": [{"type": "thinking", "thinking": "琢磨", "signature": "SIGX"},
                        {"type": "text", "text": "答案"},
                        {"type": "tool_use", "id": "toolu_7", "name": "f",
                         "input": {"a": 1}}],
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 5, "output_tokens": 9,
                      "cache_read_input_tokens": 3},
        }).encode()
        events = await self._collect(httpx.Response(200, content=body), stream=False)
        self.assertIn({"reasoning": "琢磨"}, events)
        self.assertIn({"content": "答案"}, events)
        calls = [e for e in events if "tool_calls" in e][0]["tool_calls"]
        self.assertEqual(calls[0]["function"]["arguments"], '{"a": 1}')
        stats = events[-1]["stats"]
        self.assertEqual(stats["total_tokens"], 17)   # 5+3+9
        # 非流式必须先喂计时器再结算，否则 chunks / 全文累加是 0
        self.assertEqual(stats["chunks"], 2)          # 思考帧 + 正文帧（工具帧不计）
        self.assertEqual(stats["reasoning_text"], "琢磨")
        self.assertEqual(stats["content_text"], "答案")

    async def test_error_body_is_unwrapped(self):
        err = json.dumps({"type": "error",
                          "error": {"type": "invalid_request_error",
                                    "message": "budget_tokens is not supported"}}).encode()
        with self.assertRaises(RuntimeError) as ctx:
            await self._collect(httpx.Response(400, content=err))
        text = str(ctx.exception)
        self.assertIn("budget_tokens is not supported", text)
        self.assertIn("invalid_request_error", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)

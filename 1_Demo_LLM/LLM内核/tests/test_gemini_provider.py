"""GeminiProvider 原生通道用例（httpx.MockTransport，无需真实网络与 API Key）。

覆盖：
  - 端点/鉴权：base_url 归一、`models/` 前缀、`alt=sse`、`x-goog-api-key`
  - 载荷形状：角色只有 user/model、systemInstruction 外提、contents.parts、工具声明、
    工具结果用 functionResponse、generationConfig
  - 思考配置：3 系列 thinkingLevel / 2.5 系列 thinkingBudget **互斥**、档位夹取、未知模型不下发
  - 流式：SSE **无 [DONE]**、thought→reasoning、functionCall→tool_calls、收尾帧
  - 非流式：usageMetadata 归一、finishReason 映射
  - 多模态：inlineData
  - 思考块回传：thoughtSignature → native_blocks → 原样复活（仅本轮带 tools 时）
  - 文本工具调用降级在 Gemini 通道上的接入
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from palm_llm.models import Message, ModelParameters, ProviderConfig, Tool
from palm_llm.providers import gemini as gm
from palm_llm.providers.gemini import GeminiProvider
from palm_llm.providers.profiles_data import PROFILES

GEMINI_RULE = PROFILES["gemini"].model_rules


def _cfg(base_url: str = "https://generativelanguage.googleapis.com") -> ProviderConfig:
    return ProviderConfig(name="g", type="gemini", base_url=base_url, api_key="k")


def _prov(base_url: str = "https://generativelanguage.googleapis.com") -> GeminiProvider:
    return GeminiProvider(_cfg(base_url))


def _sse(*chunks: dict) -> bytes:
    return b"".join((f"data: {json.dumps(c, ensure_ascii=False)}\n\n").encode("utf-8")
                    for c in chunks)


def _tool_decl() -> list[dict]:
    return [Tool(name="get_weather", description="查天气",
                 parameters={"type": "object", "properties": {"city": {"type": "string"}}})]


class _Recorder:
    def __init__(self, *responses: httpx.Response):
        self._responses = list(responses)
        self.payloads: list[dict] = []
        self.urls: list[str] = []
        self.headers: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.payloads.append(json.loads(request.content))
        self.urls.append(str(request.url))
        self.headers.append(dict(request.headers))
        if not self._responses:
            raise AssertionError("收到了超出预期的请求")
        return self._responses.pop(0)


class GeminiWireTest(unittest.TestCase):
    """纯逻辑：端点、鉴权、载荷形状。"""

    def test_root_and_url_normalization(self):
        for base in ("https://generativelanguage.googleapis.com",
                     "https://generativelanguage.googleapis.com/",
                     "https://generativelanguage.googleapis.com/v1beta",
                     "https://generativelanguage.googleapis.com/v1"):
            p = _prov(base)
            self.assertEqual(
                p._url(False, "gemini-2.5-flash"),
                "https://generativelanguage.googleapis.com/v1beta/models/"
                "gemini-2.5-flash:generateContent", base)
        # 流式必须显式要 SSE（默认是分块 JSON 数组，不是 SSE）
        self.assertTrue(_prov()._url(True, "gemini-2.5-flash").endswith("?alt=sse"))
        # 模型名可带 models/ 前缀
        self.assertIn("/models/gemini-2.5-flash:",
                      _prov()._url(False, "models/gemini-2.5-flash"))

    def test_auth_is_goog_api_key(self):
        h = _prov()._headers()
        self.assertIn("x-goog-api-key", h)
        self.assertNotIn("Authorization", h)

    def test_roles_and_system_hoisted(self):
        import asyncio

        async def run():
            return await _prov()._build_payload(
                [Message(role="system", content="你是助手"),
                 Message(role="user", content="你好"),
                 Message(role="assistant", content="在")],
                ModelParameters(), "gemini-2.5-flash", True, {})
        payload = asyncio.run(run())
        # system 必须外提：原生没有 system 角色
        self.assertEqual(payload["systemInstruction"], {"parts": [{"text": "你是助手"}]})
        roles = [c["role"] for c in payload["contents"]]
        self.assertEqual(roles, ["user", "model"])       # 没有 assistant，也没有 system

    def test_tool_result_becomes_function_response(self):
        import asyncio
        payload = asyncio.run(_prov()._build_payload(
            [Message(role="tool", content="晴", tool_call_id="fc_0", name="get_weather")],
            ModelParameters(), "m", True, {}))
        part = payload["contents"][0]["parts"][0]
        self.assertEqual(part["functionResponse"]["name"], "get_weather")
        self.assertEqual(part["functionResponse"]["response"], {"result": "晴"})
        # 我们自己补的合成 id 不能回传（服务端认不出来）
        self.assertNotIn("id", part["functionResponse"])
        self.assertEqual(payload["contents"][0]["role"], "user")

    def test_real_tool_call_id_is_passed_back(self):
        import asyncio
        payload = asyncio.run(_prov()._build_payload(
            [Message(role="tool", content="ok", tool_call_id="real_id_1", name="f")],
            ModelParameters(), "m", True, {}))
        self.assertEqual(
            payload["contents"][0]["parts"][0]["functionResponse"]["id"], "real_id_1")

    def test_tool_error_is_marked(self):
        import asyncio
        payload = asyncio.run(_prov()._build_payload(
            [Message(role="tool", content="超时", tool_call_id="x", name="f", tool_error=True)],
            ModelParameters(), "m", True, {}))
        body = payload["contents"][0]["parts"][0]["functionResponse"]
        self.assertTrue(body["response"]["error"])

    def test_assistant_tool_call_args_are_object(self):
        import asyncio
        payload = asyncio.run(_prov()._build_payload(
            [Message(role="assistant", content="", tool_calls=[
                {"id": "fc_0", "type": "function",
                 "function": {"name": "get_weather", "arguments": '{"city": "北京"}'}}])],
            ModelParameters(), "m", True, {}))
        call = payload["contents"][0]["parts"][0]["functionCall"]
        self.assertEqual(call["args"], {"city": "北京"})     # 对象，不是字符串
        self.assertNotIn("id", call)

    def test_tools_and_tool_config(self):
        import asyncio
        payload = asyncio.run(_prov()._build_payload(
            [Message(role="user", content="hi")],
            ModelParameters(tools=_tool_decl(), tool_choice="required"),
            "m", True, {}))
        decl = payload["tools"][0]["functionDeclarations"][0]
        self.assertEqual(decl["name"], "get_weather")
        self.assertIn("parameters", decl)
        self.assertEqual(payload["toolConfig"]["functionCallingConfig"]["mode"], "ANY")

    def test_named_forced_tool_uses_allowed_names(self):
        import asyncio
        payload = asyncio.run(_prov()._build_payload(
            [Message(role="user", content="hi")],
            ModelParameters(tools=_tool_decl(),
                            tool_choice={"type": "function", "function": {"name": "f"}}),
            "m", True, {}))
        cfg = payload["toolConfig"]["functionCallingConfig"]
        self.assertEqual(cfg["mode"], "ANY")
        self.assertEqual(cfg["allowedFunctionNames"], ["f"])

    def test_candidate_count_never_sent(self):
        """官方已在 Gemini 3 起移除 candidateCount，发了会 400。"""
        import asyncio
        payload = asyncio.run(_prov()._build_payload(
            [Message(role="user", content="hi")],
            ModelParameters(extra_body={"candidate_count": 2}), "m", True, {}))
        self.assertNotIn("candidateCount", payload["generationConfig"])
        self.assertNotIn("candidateCount", payload)

    def test_multimodal_inline_data(self):
        import asyncio
        msg = Message(role="user", content="看图",
                      images=["data:image/png;base64,AAAA"])
        payload = asyncio.run(_prov()._build_payload([msg], ModelParameters(), "m", True, {}))
        parts = payload["contents"][0]["parts"]
        self.assertEqual(parts[0], {"text": "看图"})
        self.assertEqual(parts[1],
                         {"inlineData": {"mimeType": "image/png", "data": "AAAA"}})


class GeminiThinkingTest(unittest.TestCase):
    """两套思考 API 的互斥与夹取。"""

    def _cfg_payload(self, model, extra, notes=None):
        import asyncio
        rule = None
        for r in sorted(GEMINI_RULE, key=lambda r: -r.priority):
            import re
            if re.fullmatch(r.pattern, model.lower()):
                rule, _ = r, None
                break
        return gm._thinking_config(rule, dict(extra), notes if notes is not None else {})

    def test_gemini3_uses_level(self):
        cfg = self._cfg_payload("gemini-3.5-flash", {"reasoning_effort": "medium"})
        self.assertEqual(cfg["thinkingLevel"], "medium")
        self.assertNotIn("thinkingBudget", cfg)
        self.assertTrue(cfg["includeThoughts"])

    def test_gemini25_uses_budget(self):
        cfg = self._cfg_payload("gemini-2.5-flash", {"reasoning_effort": "low"})
        self.assertIn("thinkingBudget", cfg)
        self.assertNotIn("thinkingLevel", cfg)

    def test_two_apis_never_both_sent(self):
        for model in ("gemini-3.5-flash", "gemini-1.5-pro"):
            cfg = self._cfg_payload(model, {"reasoning_effort": "high"})
            if cfg is None:
                continue
            keys = set(cfg)
            self.assertFalse({"thinkingLevel", "thinkingBudget"} <= keys, model)

    def test_unknown_model_sends_no_thinking_config(self):
        """规则没命中就不下发：猜错哪一套是必然 400，不发只是少个功能。"""
        self.assertIsNone(self._cfg_payload("gemini-1.5-pro", {"reasoning_effort": "high"}))

    def test_minimal_clamps_to_low_not_high(self):
        """3.1 Pro 不支持 minimal → 应取最近档 low，而不是通用逻辑的"最高档"。"""
        notes: dict = {}
        cfg = self._cfg_payload("gemini-3.1-pro-preview",
                                {"reasoning_effort": "minimal"}, notes)
        self.assertEqual(cfg["thinkingLevel"], "low")

    def test_always_on_model_off_request_becomes_minimal(self):
        notes: dict = {}
        cfg = self._cfg_payload("gemini-3.1-pro-preview", {"thinking": False}, notes)
        self.assertEqual(cfg["thinkingLevel"], "minimal")
        self.assertIn("thinking_forced", notes)

    def test_25_off_uses_zero_budget(self):
        cfg = self._cfg_payload("gemini-2.5-flash", {"thinking": False})
        self.assertEqual(cfg["thinkingBudget"], 0)
        self.assertNotIn("includeThoughts", cfg)      # 关着就别要摘要

    def test_explicit_budget_passthrough(self):
        cfg = self._cfg_payload("gemini-2.5-flash", {"thinking_budget": 4096})
        self.assertEqual(cfg["thinkingBudget"], 4096)

    def test_judgment_budget_is_recorded(self):
        """中间档不是官方口径 → 必须记账，不能让它看起来像官方值。"""
        notes: dict = {}
        self._cfg_payload("gemini-2.5-flash", {"reasoning_effort": "high"}, notes)
        self.assertIn("thinking_budget_guess", notes)

    def test_include_thoughts_can_be_turned_off(self):
        cfg = self._cfg_payload("gemini-3.5-flash",
                                {"reasoning_effort": "low", "include_thoughts": False})
        self.assertIs(cfg["includeThoughts"], False)

    def test_parallel_tool_calls_recorded_not_sent(self):
        import asyncio
        notes: dict = {}
        payload = asyncio.run(_prov()._build_payload(
            [Message(role="user", content="hi")],
            ModelParameters(tools=_tool_decl(), parallel_tool_calls=False),
            "gemini-2.5-flash", True, notes))
        self.assertNotIn("parallel_tool_calls", payload)
        self.assertIn("parallel_tool_calls_ignored", notes)


class GeminiStreamTest(unittest.IsolatedAsyncioTestCase):
    def _patch(self, *responses):
        rec = _Recorder(*responses)
        client = httpx.AsyncClient(transport=httpx.MockTransport(rec))
        self._orig = gm.get_client
        gm.get_client = lambda: client
        return rec

    def tearDown(self):
        if hasattr(self, "_orig"):
            gm.get_client = self._orig

    async def _collect(self, params, model="gemini-2.5-flash", stream=True):
        out = []
        async for ev in _prov().complete([Message(role="user", content="你好")],
                                        params, model, stream=stream):
            out.append(ev)
        return out

    async def test_streaming_thought_is_attributed_as_reasoning(self):
        """thought 标志的 part 必须进 reasoning 通道，不能混进正文。"""
        body = _sse(
            {"candidates": [{"content": {"role": "model", "parts": [
                {"text": "想一下…", "thought": True}]}}]},
            {"candidates": [{"content": {"role": "model", "parts": [{"text": "你好"}]}}]},
            {"candidates": [{"content": {"role": "model", "parts": [{"text": "！"}]},
                             "finishReason": "STOP"}],
             "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 3,
                               "thoughtsTokenCount": 7, "totalTokenCount": 20}},
        )
        self._patch(httpx.Response(200, content=body))
        events = await self._collect(ModelParameters())

        self.assertEqual("".join(e["reasoning"] for e in events if "reasoning" in e), "想一下…")
        self.assertEqual("".join(e["content"] for e in events if "content" in e), "你好！")
        stats = events[-1]["stats"]
        self.assertEqual(stats["finish_reason"], "stop")
        self.assertEqual(stats["reasoning_tokens"], 7)
        self.assertEqual(stats["input_tokens"], 10)
        self.assertEqual(stats["output_tokens"], 3)

    async def test_no_done_sentinel_still_finishes(self):
        """原生没有 [DONE]：连接关闭即收尾，不能因此丢掉 done 帧。"""
        self._patch(httpx.Response(200, content=_sse(
            {"candidates": [{"content": {"parts": [{"text": "hi"}]},
                             "finishReason": "STOP"}]})))
        events = await self._collect(ModelParameters())
        self.assertTrue(events[-1]["done"])

    async def test_function_call_emits_delta_and_full_call(self):
        self._patch(httpx.Response(200, content=_sse(
            {"candidates": [{"content": {"parts": [
                {"functionCall": {"name": "get_weather", "args": {"city": "北京"}}}]},
                "finishReason": "STOP"}]})))
        events = await self._collect(ModelParameters(tools=_tool_decl()))

        deltas = [e["tool_call_delta"] for e in events if "tool_call_delta" in e]
        self.assertEqual(deltas[0]["name"], "get_weather")
        calls = [c for e in events if "tool_calls" in e for c in e["tool_calls"]]
        self.assertEqual(len(calls), 1)
        self.assertEqual(json.loads(calls[0]["function"]["arguments"]), {"city": "北京"})
        # 有函数调用时应报 tool_calls，否则按 finish_reason 分支的调用方不会执行工具
        self.assertEqual(events[-1]["stats"]["finish_reason"], "tool_calls")
        self.assertEqual(events[-1]["stats"]["extra"]["finish_reason_vendor"], "STOP")

    async def test_blocked_prompt_becomes_content_filter(self):
        self._patch(httpx.Response(200, content=_sse(
            {"promptFeedback": {"blockReason": "SAFETY"}})))
        events = await self._collect(ModelParameters())
        stats = events[-1]["stats"]
        self.assertEqual(stats["finish_reason"], "content_filter")
        self.assertEqual(stats["extra"]["block_reason"], "SAFETY")

    async def test_nonstream_usage_and_finish_reason(self):
        body = json.dumps({
            "candidates": [{"content": {"parts": [{"text": "ok"}]}, "finishReason": "MAX_TOKENS"}],
            "usageMetadata": {"promptTokenCount": 100, "cachedContentTokenCount": 60,
                              "candidatesTokenCount": 5, "totalTokenCount": 105},
        }).encode()
        self._patch(httpx.Response(200, content=body))
        events = await self._collect(ModelParameters(), stream=False)
        stats = events[-1]["stats"]
        self.assertEqual(stats["finish_reason"], "length")
        self.assertEqual(stats["cache_read_tokens"], 60)
        self.assertEqual(stats["input_tokens"], 40)      # promptTokenCount 含缓存，要减
        self.assertEqual(stats["output_tokens"], 5)

    async def test_http_error_is_unpacked(self):
        bad = json.dumps({"error": {"code": 400, "status": "INVALID_ARGUMENT",
                                    "message": "thinking_level not supported"}}).encode()
        self._patch(httpx.Response(400, content=bad))
        with self.assertRaises(RuntimeError) as ctx:
            await self._collect(ModelParameters())
        self.assertIn("INVALID_ARGUMENT", str(ctx.exception))
        self.assertIn("thinking_level not supported", str(ctx.exception))

    async def test_text_tool_call_fallback_is_wired(self):
        """端点不实现原生 function calling 时，正文里的调用也要被抠出来。"""
        marker = '<tool_call>{"name":"get_weather","arguments":{"city":"北京"}}</tool_call>'
        body = _sse({"candidates": [{"content": {"parts": [{"text": "好的 "}]}}]},
                    {"candidates": [{"content": {"parts": [{"text": marker}]},
                                     "finishReason": "STOP"}]})
        self._patch(httpx.Response(200, content=body))
        events = await self._collect(ModelParameters(tools=_tool_decl()))
        calls = [c for e in events if "tool_calls" in e for c in e["tool_calls"]]
        self.assertEqual(json.loads(calls[0]["function"]["arguments"]), {"city": "北京"})
        self.assertEqual(events[-1]["stats"]["extra"]["text_tool_calls"], 1)


class GeminiReasoningEchoTest(unittest.TestCase):
    """thoughtSignature 必须原样往返（官方：函数调用的签名是必需项）。"""

    def test_signature_captured_into_native_blocks(self):
        st = gm.new_state()
        gm.events_from({"candidates": [{"content": {"parts": [
            {"text": "推理", "thought": True, "thoughtSignature": "SIG-1"},
            {"text": "答案"}]}, "finishReason": "STOP"}]}, st, "g")
        from palm_llm.providers.telemetry import Meter
        done = gm.finish_events(st, Meter(model="m"))[-1]
        stored = json.loads(done["stats"]["extra"]["native_blocks"])
        self.assertEqual(stored, [{"text": "推理", "thought": True, "thoughtSignature": "SIG-1"}])

    def test_echo_revives_parts_only_with_tools(self):
        import asyncio
        raw = json.dumps([{"text": "推理", "thought": True, "thoughtSignature": "SIG-1"}])
        msg = Message(role="assistant", content="答案", reasoning_echo=raw)

        with_tools = asyncio.run(_prov()._build_payload(
            [msg], ModelParameters(tools=_tool_decl()), "gemini-2.5-flash", True, {}))
        self.assertEqual(with_tools["contents"][0]["parts"],
                         [{"text": "推理", "thought": True, "thoughtSignature": "SIG-1"}])

        without = asyncio.run(_prov()._build_payload(
            [msg], ModelParameters(), "gemini-2.5-flash", True, {}))
        self.assertEqual(without["contents"][0]["parts"], [{"text": "答案"}])

    def test_no_signature_means_no_credential(self):
        """纯文本响应不该产生 native_blocks（否则每轮 stats 无谓膨胀）。"""
        st = gm.new_state()
        gm.events_from({"candidates": [{"content": {"parts": [{"text": "hi"}]},
                                        "finishReason": "STOP"}]}, st, "g")
        from palm_llm.providers.telemetry import Meter
        done = gm.finish_events(st, Meter(model="m"))[-1]
        self.assertNotIn("native_blocks", done["stats"]["extra"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

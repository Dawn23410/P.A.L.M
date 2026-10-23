"""思考块回传契约用例（跨通道）。

覆盖：
  - 契约分级：DeepSeek V4 必需、legacy reasoner 必须剥离、Kimi K3 必需、K2.5 不回传
  - OpenAI 兼容通道：按 Profile 决定是否把上一轮思考写进 reasoning_content
  - Anthropic 通道：响应方向产出回传凭据（native_blocks）、请求方向原样复活、
    且只在本轮带 tools 时才回传
  - 服务端历史回放：工具轮次与思考凭据不得在组装时丢失
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
from palm_llm.providers.anthropic_wire import (
    finish_events,
    new_state,
    on_event,
    to_native_messages,
)
from palm_llm.providers.base import to_chat_message
from palm_llm.providers.profiles import resolve_model, resolve_provider
from palm_llm.providers.telemetry import Meter


def _echo_of(base: str, model: str) -> bool:
    """走真实链路取该端点+模型组合生效的 echo 契约。"""
    profile, _ = resolve_model(resolve_provider(base, "openai_compat"), model)
    return profile.needs_reasoning_echo


class EchoContractTest(unittest.TestCase):
    """契约分级：同厂商不同代际可能相反，必须模型级可覆盖。"""

    def test_deepseek_v4_echoes(self):
        self.assertTrue(_echo_of("https://api.deepseek.com", "deepseek-v4-flash"))
        self.assertTrue(_echo_of("https://api.deepseek.com", "deepseek-v4-pro"))

    def test_legacy_reasoner_must_strip(self):
        """legacy reasoner 入参带 reasoning_content 直接 400 → 契约必须为否。"""
        self.assertFalse(_echo_of("https://api.deepseek.com", "deepseek-reasoner"))

    def test_kimi_k3_echoes_but_k25_does_not(self):
        self.assertTrue(_echo_of("https://api.moonshot.cn", "kimi-k3"))
        self.assertTrue(_echo_of("https://api.moonshot.cn", "kimi-k2.6"))
        self.assertFalse(_echo_of("https://api.moonshot.cn", "kimi-k2.5"))   # 无保留式思考

    def test_generic_defaults_to_safe(self):
        """默认不发：误发会让"必须剥离"的厂商静默 400，漏发则报错明确。"""
        self.assertFalse(_echo_of("http://unknown.example/v1", "some-model"))


class ChatMessageTest(unittest.TestCase):
    def test_reasoning_kept_when_echoing(self):
        m = Message(role="assistant", content="答", reasoning="想过")
        self.assertEqual(to_chat_message(m, True)["reasoning_content"], "想过")

    def test_reasoning_dropped_by_default(self):
        m = Message(role="assistant", content="答", reasoning="想过")
        self.assertNotIn("reasoning_content", to_chat_message(m))

    def test_user_message_never_echoes(self):
        """推理块只属于 assistant 轮次，塞回用户轮次是构造非法请求。"""
        m = Message(role="user", content="问", reasoning="想过")
        self.assertNotIn("reasoning_content", to_chat_message(m, True))


class OpenAIPayloadTest(unittest.IsolatedAsyncioTestCase):
    """经真实 complete() 链路，验证出站 payload 里的 reasoning_content 有无。"""

    def _patch(self):
        seen: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(json.loads(request.content))
            return httpx.Response(
                200, content=b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
                             b'data: [DONE]\n\n')

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self._orig = oc.get_client
        oc.get_client = lambda: client
        return seen

    def tearDown(self):
        if hasattr(self, "_orig"):
            oc.get_client = self._orig

    async def _send(self, base: str, model: str):
        seen = self._patch()
        cfg = ProviderConfig(name="t", type="openai_compat", base_url=base, api_key="k")
        msgs = [Message(role="user", content="问"),
                Message(role="assistant", content="答", reasoning="上一轮的思考")]
        async for _ in oc.OpenAICompatProvider(cfg).complete(msgs, ModelParameters(), model):
            pass
        return seen[0]["messages"][1]

    async def test_deepseek_receives_prior_reasoning(self):
        assistant = await self._send("https://api.deepseek.com", "deepseek-v4-flash")
        self.assertEqual(assistant["reasoning_content"], "上一轮的思考")

    async def test_legacy_reasoner_strips_reasoning(self):
        assistant = await self._send("https://api.deepseek.com", "deepseek-reasoner")
        self.assertNotIn("reasoning_content", assistant)

    async def test_generic_endpoint_strips_reasoning(self):
        assistant = await self._send("http://unknown.example/v1", "some-model")
        self.assertNotIn("reasoning_content", assistant)


SSE_THINKING = [
    {"type": "message_start",
     "message": {"id": "msg_1", "model": "claude-opus-4-8",
                 "usage": {"input_tokens": 25, "output_tokens": 1}}},
    {"type": "content_block_start", "index": 0,
     "content_block": {"type": "thinking", "thinking": ""}},
    {"type": "content_block_delta", "index": 0,
     "delta": {"type": "thinking_delta", "thinking": "先想"}},
    {"type": "content_block_delta", "index": 0,
     "delta": {"type": "signature_delta", "signature": "SIG1"}},
    {"type": "content_block_stop", "index": 0},
    {"type": "content_block_start", "index": 1,
     "content_block": {"type": "tool_use", "id": "toolu_9", "name": "get_weather",
                       "input": {}}},
    {"type": "content_block_delta", "index": 1,
     "delta": {"type": "input_json_delta", "partial_json": '{"city":"上海"}'}},
    {"type": "content_block_stop", "index": 1},
    {"type": "message_delta", "delta": {"stop_reason": "tool_use"},
     "usage": {"output_tokens": 18}},
    {"type": "message_stop"},
]

SSE_TEXT_ONLY = [
    {"type": "message_start",
     "message": {"id": "msg_2", "model": "claude-opus-4-8",
                 "usage": {"input_tokens": 5, "output_tokens": 1}}},
    {"type": "content_block_start", "index": 0,
     "content_block": {"type": "text", "text": ""}},
    {"type": "content_block_delta", "index": 0,
     "delta": {"type": "text_delta", "text": "你好"}},
    {"type": "message_stop"},
]


def _stats_of(events: list[dict]) -> dict:
    st = new_state()
    for ev in events:
        on_event(st, ev, "claude")
    done = finish_events(st, Meter(model="claude-opus-4-8"))[-1]
    return done["stats"]


async def _fetch_image(_url: str):
    return "image/png", "QUJD"


class AnthropicCredentialTest(unittest.IsolatedAsyncioTestCase):
    """回传凭据的生产与消费（双向）。"""

    def test_thinking_turn_yields_native_blocks(self):
        blocks = json.loads(_stats_of(SSE_THINKING)["extra"]["native_blocks"])
        self.assertEqual([b["type"] for b in blocks], ["thinking", "tool_use"])
        self.assertEqual(blocks[0]["signature"], "SIG1")          # 签名逐字留存
        self.assertEqual(blocks[1]["input"], {"city": "上海"})     # 分片参数已拼成对象

    def test_text_only_turn_has_no_credential(self):
        """正文/工具内核能无损重建，只有含签名的思考块需要整条回传。"""
        extra = _stats_of(SSE_TEXT_ONLY).get("extra") or {}
        self.assertNotIn("native_blocks", extra)

    async def _rebuild(self, echo: bool):
        blocks = json.loads(_stats_of(SSE_THINKING)["extra"]["native_blocks"])
        msgs = [
            Message(role="user", content="天气"),
            Message(role="assistant", content="", reasoning="先想",
                    reasoning_echo=json.dumps(blocks, ensure_ascii=False),
                    tool_calls=[{"id": "toolu_9", "type": "function",
                                 "function": {"name": "get_weather",
                                              "arguments": '{"city":"上海"}'}}]),
            Message(role="tool", content="晴", tool_call_id="toolu_9"),
        ]
        _, native = await to_native_messages(msgs, _fetch_image, echo_reasoning=echo)
        return native

    async def test_credential_is_replayed_verbatim(self):
        native = await self._rebuild(echo=True)
        self.assertEqual([b["type"] for b in native[1]["content"]],
                         ["thinking", "tool_use"])
        self.assertEqual(native[1]["content"][0]["signature"], "SIG1")

    async def test_without_echo_turn_is_rebuilt_from_kernel_fields(self):
        native = await self._rebuild(echo=False)
        types = [b["type"] for b in native[1]["content"]]
        self.assertEqual(types, ["tool_use"])      # 思考块被有意省略（无 tools 时官方允许）
        self.assertEqual(native[2]["content"][0]["type"], "tool_result")

    async def test_provider_gates_echo_on_tools(self):
        """官方：带思考用工具时回传才严格必需；否则回传只会让历史思考持续计费。"""
        from palm_llm.providers import anthropic as ap

        prov = ap.AnthropicProvider(
            ProviderConfig(name="claude", type="anthropic",
                           base_url="https://api.anthropic.com", api_key="k"))
        blocks = json.loads(_stats_of(SSE_THINKING)["extra"]["native_blocks"])
        msgs = [Message(role="user", content="天气"),
                Message(role="assistant", content="答", reasoning_echo=json.dumps(blocks))]
        with_tools = await prov._build_payload(
            msgs, ModelParameters(tools=[{"type": "function",
                                          "function": {"name": "f", "parameters": {}}}]),
            "claude-opus-4-8", True)
        without = await prov._build_payload(msgs, ModelParameters(), "claude-opus-4-8", True)
        self.assertEqual(with_tools["messages"][1]["content"][0]["type"], "thinking")
        self.assertEqual(without["messages"][1]["content"][0]["type"], "text")


class ServerReplayTest(unittest.TestCase):
    """历史消息回放必须整条搬运 —— 少一个字段就是一次非法请求。"""

    def test_tool_turn_survives_assembly(self):
        from palm_llm.server.chat import _replay
        from palm_llm.server.models import Message as ApiMessage

        src = ApiMessage(role="assistant", content="", reasoning="想过",
                         reasoning_echo='[{"type":"thinking","signature":"S"}]',
                         tool_calls=[{"id": "call_1", "type": "function",
                                      "function": {"name": "f", "arguments": "{}"}}])
        out = _replay(src)
        self.assertEqual(out.tool_calls, src.tool_calls)
        self.assertEqual(out.reasoning, "想过")
        self.assertEqual(out.reasoning_echo, src.reasoning_echo)

    def test_tool_result_keeps_call_id(self):
        from palm_llm.server.chat import _replay
        from palm_llm.server.models import Message as ApiMessage

        out = _replay(ApiMessage(role="tool", content="晴", tool_call_id="call_1", name="f"))
        self.assertEqual(out.tool_call_id, "call_1")
        self.assertEqual(out.name, "f")

    def test_to_kernel_carries_reasoning(self):
        from palm_llm.server.models import Message as ApiMessage

        km = ApiMessage(role="assistant", content="答", reasoning="想过",
                        reasoning_echo="[1]").to_kernel()
        self.assertEqual(km.reasoning, "想过")
        self.assertEqual(km.reasoning_echo, "[1]")


if __name__ == "__main__":
    unittest.main(verbosity=2)

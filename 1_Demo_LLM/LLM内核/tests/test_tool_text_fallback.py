"""正文文本工具调用降级（tooltext）+ 工具原生支持修复（F1–F5）的回归用例。

两块内容：

**A. 文本降级**（无原生 tool_calls 时从正文里抠调用）
  五族形态（Hermes / Llama3 / Mistral / Qwen2.5 旧模板 / GGUF json 块）
  + 三条安全阀 + 流式分帧不丢字 + 事件路由 + ollama 通道端到端接入。

**B. 工具原生支持修复**
  F1 ollama 回填字段名错（tool_name）        F2 非流式 tool_calls 未归一
  F3 Anthropic 强制工具选择 × 手工思考冲突   F4 ollama 下发不存在的 tool_choice
  F5 缺 is_error / parallel_tool_calls / strict

全部离线：httpx.MockTransport 回放固定响应，不依赖真实服务与 API Key。
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from palm_llm.models import Message, ModelParameters, ProviderConfig, Tool
from palm_llm.providers import ollama as ol
from palm_llm.providers import openai_compat as oc
from palm_llm.providers.anthropic import _tool_choice_setup
from palm_llm.providers.base import normalize_tool_calls, to_chat_message
from palm_llm.providers.profiles import ModelRule
from palm_llm.providers.tooltext import (
    TextToolFilter,
    declared_names,
    filter_events,
    parse_region,
    text_tool_events,
)

NAMES = {"get_weather"}


# ─────────────────────────── 测试工具 ───────────────────────────
def _feed_all(text: str, names=NAMES, size: int | None = None):
    """把 text 按 size 切片模拟流式喂入 → (放行事件, 抽出的调用)。

    `size=None` 为整段一次性喂入；`size=1` 即逐字符喂，用于验证"标记跨帧"。
    """
    flt = TextToolFilter(names)
    out: list[dict] = []
    chunks = [text] if size is None else [text[i:i + size] for i in range(0, len(text), size)]
    for ch in chunks:
        out.extend(flt.feed(ch))
    out.extend(flt.finish())
    return out, flt.take_calls()


def _text_of(events) -> str:
    return "".join(e["content"] for e in events if "content" in e)


def _args(call: dict) -> dict:
    return json.loads(call["function"]["arguments"])


def _ndjson(*objs: dict) -> bytes:
    return b"".join((json.dumps(o, ensure_ascii=False) + "\n").encode("utf-8") for o in objs)


def _tool_decl(name: str = "get_weather") -> list[dict]:
    return [{"type": "function",
             "function": {"name": name, "description": "",
                          "parameters": {"type": "object",
                                         "properties": {"city": {"type": "string"}}}}}]


# ═══════════════════════ A1. 五族正文形态 ═══════════════════════
class MarkerShapeTest(unittest.TestCase):
    def test_hermes_tool_call_block(self):
        """Hermes / Qwen2 / Qwen3：<tool_call>{…}</tool_call>。"""
        s = '<tool_call>{"name": "get_weather", "arguments": {"city": "北京"}}</tool_call>'
        ev, calls = _feed_all(s)
        self.assertEqual(_text_of(ev), "")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["function"]["name"], "get_weather")
        self.assertEqual(_args(calls[0]), {"city": "北京"})
        self.assertEqual(calls[0]["index"], 0)
        self.assertTrue(calls[0]["id"].startswith("call_txt_"))

    def test_hermes_keeps_surrounding_text_in_order(self):
        s = '好的<tool_call>{"name":"get_weather","arguments":{"city":"北京"}}</tool_call>马上查'
        ev, calls = _feed_all(s)
        self.assertEqual(_text_of(ev), "好的马上查")
        self.assertEqual(len(calls), 1)

    def test_llama3_python_tag_uses_parameters(self):
        """Llama 3.1+：<|python_tag|>{…}<|eom_id|>，参数键名是 `parameters` 不是 `arguments`。"""
        s = '<|python_tag|>{"name": "get_weather", "parameters": {"city": "上海"}}<|eom_id|>'
        ev, calls = _feed_all(s)
        self.assertEqual(_text_of(ev), "")
        self.assertEqual(_args(calls[0]), {"city": "上海"})

    def test_mistral_tool_calls_array(self):
        """Mistral：[TOOL_CALLS][{…}]，无结束标记。"""
        s = '[TOOL_CALLS][{"name": "get_weather", "arguments": {"city": "广州"}}]'
        ev, calls = _feed_all(s)
        self.assertEqual(_text_of(ev), "")
        self.assertEqual(len(calls), 1)
        self.assertEqual(_args(calls[0]), {"city": "广州"})

    def test_mistral_tail_after_json_is_released(self):
        """无结束标记的区域：调用 JSON 之后的话必须原样放行，不能被吞掉。"""
        s = '[TOOL_CALLS][{"name": "get_weather", "arguments": {"city": "广州"}}]好的'
        ev, calls = _feed_all(s)
        self.assertEqual(_text_of(ev), "好的")
        self.assertEqual(len(calls), 1)

    def test_qwen_legacy_function_args_markers(self):
        """Qwen2.5 旧模板：✿FUNCTION✿: name + ✿ARGS✿: {…}（裸文本，非 JSON 块）。"""
        s = '✿FUNCTION✿: get_weather\n✿ARGS✿: {"city": "深圳"}\n✿RETURN✿'
        ev, calls = _feed_all(s)
        self.assertEqual(_text_of(ev), "")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["function"]["name"], "get_weather")
        self.assertEqual(_args(calls[0]), {"city": "深圳"})

    def test_qwen_legacy_without_return_marker(self):
        """没有 ✿RETURN✿ 时，区域吃到流末，收尾仍应解析出来。"""
        s = '✿FUNCTION✿: get_weather\n✿ARGS✿: {"city": "深圳"}'
        ev, calls = _feed_all(s)
        self.assertEqual(_text_of(ev), "")
        self.assertEqual(_args(calls[0]), {"city": "深圳"})

    def test_json_fence_fallback(self):
        """社区 GGUF：```json {…} ``` 块。"""
        s = '```json\n{"name": "get_weather", "arguments": {"city": "杭州"}}\n```'
        ev, calls = _feed_all(s)
        self.assertEqual(_text_of(ev), "")
        self.assertEqual(_args(calls[0]), {"city": "杭州"})

    def test_multiple_calls_get_sequential_index(self):
        s = ('<tool_call>{"name":"get_weather","arguments":{"city":"北京"}}</tool_call>'
             '<tool_call>{"name":"get_weather","arguments":{"city":"上海"}}</tool_call>')
        _, calls = _feed_all(s)
        self.assertEqual([c["index"] for c in calls], [0, 1])
        self.assertEqual([_args(c)["city"] for c in calls], ["北京", "上海"])

    def test_tool_calls_wrapper_object_accepted(self):
        s = '<tool_call>{"tool_calls": [{"name": "get_weather", "arguments": {}}]}</tool_call>'
        _, calls = _feed_all(s)
        self.assertEqual(len(calls), 1)


# ═══════════════════════ A2. 三条安全阀 ═══════════════════════
class SafetyValveTest(unittest.TestCase):
    def test_no_tools_declared_passes_through(self):
        """安全阀 1：没声明任何工具 → 整套机制关闭，正文原样放行。"""
        s = '<tool_call>{"name": "get_weather", "arguments": {}}</tool_call>'
        ev, calls = _feed_all(s, names=set())
        self.assertEqual(_text_of(ev), s)
        self.assertEqual(calls, [])

    def test_undeclared_name_passes_through(self):
        """安全阀 2：name 不在已声明集合里 → 判为普通正文（防止把自己的示例文档吃掉）。"""
        s = '<tool_call>{"name": "delete_everything", "arguments": {}}</tool_call>'
        ev, calls = _feed_all(s)
        self.assertEqual(_text_of(ev), s)
        self.assertEqual(calls, [])

    def test_region_without_json_passes_through(self):
        """安全阀 3：区域内不是 JSON → 连标记一起原样放行。"""
        s = "示例：<tool_call>这里写调用</tool_call> 结束"
        ev, calls = _feed_all(s)
        self.assertEqual(_text_of(ev), s)
        self.assertEqual(calls, [])

    def test_declared_names_accepts_all_three_native_shapes(self):
        """三家的工具声明形状不同，缺一种就会让安全阀 1 误判"没声明工具"、整套机制静默关闭。"""
        self.assertEqual(declared_names(
            [{"type": "function", "function": {"name": "a"}}]), {"a"})          # OpenAI
        self.assertEqual(declared_names([{"name": "b", "input_schema": {}}]), {"b"})
        self.assertEqual(declared_names(
            [{"functionDeclarations": [{"name": "c"}, {"name": "d"}]}]), {"c", "d"})  # Gemini
        self.assertEqual(declared_names(None), set())


# ═══════════════════════ A3. 流式分帧 ═══════════════════════
class StreamFramingTest(unittest.TestCase):
    def test_marker_split_across_frames(self):
        """标记被切到多帧里也要认出来（逐字符喂是最坏情况）。"""
        s = '前<tool_call>{"name":"get_weather","arguments":{"city":"北京"}}</tool_call>后'
        for size in (1, 2, 3, 5, 7, 13):
            ev, calls = _feed_all(s, size=size)
            self.assertEqual(_text_of(ev), "前后", f"size={size}")
            self.assertEqual(len(calls), 1, f"size={size}")

    def test_no_call_text_is_lossless_at_any_frame_size(self):
        """非调用正文：任意分帧下，放行的正文必须与原文逐字一致（不丢不重）。"""
        s = "这是一段很普通的话，里面没有任何工具调用，只是比较长" * 3
        for size in (1, 2, 4, 9, 64):
            ev, calls = _feed_all(s, size=size)
            self.assertEqual(_text_of(ev), s, f"size={size}")
            self.assertEqual(calls, [], f"size={size}")

    def test_near_miss_text_is_lossless(self):
        """含"半个标记"的正文（`<tool`、`[TOOL_CALL`）不能误吞。"""
        for s in ("看这个 <tool 标签", "数组 [TOOL_CALL 前缀", "结尾是 ```json 反引号"):
            ev, calls = _feed_all(s, size=3)
            self.assertEqual(_text_of(ev), s, s)
            self.assertEqual(calls, [], s)

    def test_oversized_region_falls_back_to_verbatim(self):
        """区域内一直不出现结束标记 → 超过上限就放弃解析，原文照发。"""
        s = "<tool_call>" + "x" * 70000
        ev, calls = _feed_all(s)
        self.assertEqual(calls, [])
        self.assertTrue(_text_of(ev).startswith("<tool_call>"))
        self.assertEqual(len(_text_of(ev)), len(s))


# ═══════════════════════ A4. 事件路由 ═══════════════════════
class EventRoutingTest(unittest.TestCase):
    def test_done_marks_finish_reason_and_emits_calls(self):
        flt = TextToolFilter(NAMES)
        out = flt.feed('<tool_call>{"name":"get_weather","arguments":{"city":"北京"}}</tool_call>')
        done = {"done": True, "usage": {}, "stats": {"finish_reason": "stop", "extra": {}}}
        out += text_tool_events(flt, done)
        calls = [e for e in out if "tool_calls" in e]
        self.assertEqual(len(calls), 1)
        final = out[-1]
        # 抽到的调用按 OpenAI 口径表现为 tool_calls，否则按 finish_reason 分支的调用方不会执行工具
        self.assertEqual(final["stats"]["finish_reason"], "tool_calls")
        # 服务端原值不丢
        self.assertEqual(final["stats"]["extra"]["finish_reason_vendor"], "stop")
        self.assertEqual(final["stats"]["extra"]["text_tool_calls"], 1)

    def test_native_tool_calls_win_and_derived_calls_dropped(self):
        """原生与正文两条路都出现时以原生为准：派生调用丢弃、不重复执行，标记文本也不外泄到正文。

        （同一逻辑调用被原生报了一次、正文又写了一次是病态场景；执行两份=副作用翻倍，
        所以派生那份作废；标记本身属于"已被消费的调用"，不该出现在展示给用户的正文里。）
        """
        s = '好的<tool_call>{"name":"get_weather","arguments":{}}</tool_call>马上查'
        flt = TextToolFilter(NAMES)
        out = flt.feed(s)
        native = [{"index": 0, "id": "call_1", "type": "function",
                   "function": {"name": "get_weather", "arguments": "{}"}}]
        out += text_tool_events(flt, {"tool_calls": native})
        out += text_tool_events(flt, {"done": True, "usage": {}, "stats": {}})
        self.assertEqual(_text_of(out), "好的马上查")          # 标记外的正文一字不丢
        self.assertEqual([e for e in out if "tool_calls" in e],
                         [{"tool_calls": native}])            # 只有原生那一份
        self.assertEqual(flt.take_calls(), [])                 # 派生调用已被取代

    def test_non_stream_filter_matches_stream_routing(self):
        """非流式整段过滤（filter_events）与流式逐帧（text_tool_events）结论必须一致。"""
        events = [
            {"reasoning": "想一下"},
            {"content": '前<tool_call>{"name":"get_weather","arguments":{"city":"北京"}}</tool_call>'},
            {"content": "后"},
            {"done": True, "usage": {}, "stats": {"finish_reason": "stop", "extra": {}}},
        ]
        got = filter_events(list(events), NAMES)
        self.assertEqual(_text_of(got), "前后")
        self.assertEqual([c["function"]["name"] for e in got
                          if "tool_calls" in e for c in e["tool_calls"]], ["get_weather"])
        self.assertIn({"reasoning": "想一下"}, got)

    def test_parse_region_reports_tail(self):
        calls, tail = parse_region("[TOOL_CALLS]",
                                   '[{"name":"get_weather","arguments":{}}] 尾巴',
                                   NAMES)
        self.assertEqual(len(calls), 1)
        self.assertEqual(tail, " 尾巴")
        # 有结束标记的区域：尾巴恒为空（整体属于该区域）
        _, tail2 = parse_region("<tool_call>", '{"name":"get_weather","arguments":{}}', NAMES)
        self.assertEqual(tail2, "")


# ═══════════════════════ A5. ollama 通道端到端 ═══════════════════════
class _Recorder:
    def __init__(self, *responses: httpx.Response):
        self._responses = list(responses)
        self.payloads: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.payloads.append(json.loads(request.content))
        if not self._responses:
            raise AssertionError("收到了超出预期的请求")
        return self._responses.pop(0)


class OllamaTextFallbackTest(unittest.IsolatedAsyncioTestCase):
    def _patch(self, *responses):
        rec = _Recorder(*responses)
        client = httpx.AsyncClient(transport=httpx.MockTransport(rec))
        self._orig = ol.get_client
        ol.get_client = lambda: client
        return rec

    def tearDown(self):
        if hasattr(self, "_orig"):
            ol.get_client = self._orig

    def _params(self, tools=True):
        return ModelParameters(tools=_tool_decl() if tools else None)

    async def _run(self, params, stream=True):
        prov = ol.OllamaProvider(ProviderConfig(name="ollama", type="ollama",
                                                base_url="http://x.invalid"))
        out = []
        async for ev in prov.complete([Message(role="user", content="北京天气")],
                                      params, model="m", stream=stream):
            out.append(ev)
        return out

    async def test_streaming_text_call_is_extracted(self):
        """自定义 GGUF 把调用写进正文 → 内核应按 tool_calls 事件交出。"""
        marker = '<tool_call>{"name":"get_weather","arguments":{"city":"北京"}}</tool_call>'
        body = _ndjson(
            {"message": {"role": "assistant", "content": "好的 "}, "done": False},
            # 标记故意被切成两帧：验证跨帧
            {"message": {"role": "assistant", "content": marker[:20]}, "done": False},
            {"message": {"role": "assistant", "content": marker[20:]}, "done": False},
            {"message": {"role": "assistant", "content": ""}, "done": True,
             "done_reason": "stop", "prompt_eval_count": 12, "eval_count": 6},
        )
        self._patch(httpx.Response(200, content=body))
        events = await self._run(self._params())

        content = "".join(e["content"] for e in events if "content" in e)
        self.assertEqual(content, "好的 ")
        got = [c for e in events if "tool_calls" in e for c in e["tool_calls"]]
        self.assertEqual(len(got), 1)
        self.assertEqual(_args(got[0]), {"city": "北京"})
        self.assertEqual(events[-1]["stats"]["finish_reason"], "tool_calls")

    async def test_nonstream_text_call_is_extracted(self):
        marker = '<tool_call>{"name":"get_weather","arguments":{"city":"上海"}}</tool_call>'
        body = json.dumps({"message": {"role": "assistant", "content": marker},
                           "done": True, "done_reason": "stop",
                           "prompt_eval_count": 5, "eval_count": 3}).encode()
        self._patch(httpx.Response(200, content=body))
        events = await self._run(self._params(), stream=False)
        got = [c for e in events if "tool_calls" in e for c in e["tool_calls"]]
        self.assertEqual(_args(got[0]), {"city": "上海"})
        self.assertEqual(events[-1]["stats"]["finish_reason"], "tool_calls")

    async def test_text_fallback_off_without_tools(self):
        """未声明 tools → 正文里的标记原样保留（安全阀 1 在通道层也成立）。"""
        marker = '<tool_call>{"name":"get_weather","arguments":{}}</tool_call>'
        body = json.dumps({"message": {"role": "assistant", "content": marker},
                           "done": True, "done_reason": "stop"}).encode()
        self._patch(httpx.Response(200, content=body))
        events = await self._run(self._params(tools=False), stream=False)
        self.assertEqual("".join(e["content"] for e in events if "content" in e), marker)
        self.assertFalse([e for e in events if "tool_calls" in e])

    async def test_native_tool_calls_normalized_on_nonstream(self):
        """F2：非流式整包下发的 tool_calls 必须与流式分片拼装出同一形状（补 index）。"""
        body = json.dumps({
            "message": {"role": "assistant", "content": "",
                        "tool_calls": [{"function": {"name": "get_weather",
                                                     "arguments": {"city": "北京"}}}]},
            "done": True, "done_reason": "stop"}).encode()
        self._patch(httpx.Response(200, content=body))
        events = await self._run(self._params(), stream=False)
        got = [c for e in events if "tool_calls" in e for c in e["tool_calls"]]
        self.assertEqual(got[0]["index"], 0)
        self.assertTrue(got[0]["id"])
        self.assertEqual(got[0]["type"], "function")
        self.assertIsInstance(got[0]["function"]["arguments"], str)


# ═══════════════════════ B1. F1 / F4：ollama 线格式 ═══════════════════════
class OllamaWireFormatTest(unittest.TestCase):
    def _payload(self, messages, params=None):
        return ol.OllamaProvider(
            ProviderConfig(name="ollama", type="ollama", base_url="http://x.invalid")
        )._build_payload(messages, params or ModelParameters(), "m", True)

    def test_tool_result_uses_tool_name_not_name(self):
        """F1：原生协议只认 `tool_name`，发 `name`/`tool_call_id` 会静默丢掉工具名。"""
        msg = Message(role="tool", content="晴", tool_call_id="call_1", name="get_weather")
        out = self._payload([msg])["messages"][0]
        self.assertEqual(out["tool_name"], "get_weather")
        self.assertNotIn("tool_call_id", out)
        self.assertNotIn("name", out)

    def test_assistant_tool_calls_arguments_become_object(self):
        """F1：原生要求 arguments 是**对象**，不是 JSON 字符串。"""
        msg = Message(role="assistant", content="", tool_calls=[
            {"id": "call_1", "type": "function",
             "function": {"name": "get_weather", "arguments": '{"city": "北京"}'}}])
        out = self._payload([msg])["messages"][0]
        self.assertEqual(out["tool_calls"][0]["function"]["arguments"], {"city": "北京"})

    def test_never_sends_tool_choice_or_parallel(self):
        """F4：原生 /api/chat 没有这两个字段，官方把 tool_choice 列在 Future improvements。"""
        params = ModelParameters(tools=_tool_decl(), tool_choice="required",
                                 parallel_tool_calls=True)
        payload = self._payload([Message(role="user", content="hi")], params)
        self.assertIn("tools", payload)
        self.assertNotIn("tool_choice", payload)
        self.assertNotIn("parallel_tool_calls", payload)

    def test_legacy_normalize_alias_matches_base(self):
        raw = [{"function": {"name": "f", "arguments": {"a": 1}}}]
        self.assertEqual(ol._normalize_tool_calls(raw), normalize_tool_calls(raw))
        self.assertIsNone(ol._normalize_tool_calls(None))
        self.assertIsNone(ol._normalize_tool_calls([]))


# ═══════════════════════ B2. F5 / F2：公共字段 ═══════════════════════
class ToolFieldRegressionTest(unittest.TestCase):
    def test_assistant_tool_calls_survive_to_openai(self):
        msg = Message(role="assistant", content="", tool_calls=[{"id": "1"}])
        self.assertEqual(to_chat_message(msg)["tool_calls"], [{"id": "1"}])

    def test_tool_error_flag_only_affects_anthropic(self):
        """F5：`tool_error` 是 Anthropic 专用（tool_result.is_error）；OpenAI 系无对应字段。"""
        msg = Message(role="tool", content="失败", tool_call_id="c1", tool_error=True)
        self.assertNotIn("is_error", to_chat_message(msg))

    def test_tool_strict_is_emitted_when_set(self):
        """F5：strict 默认为 None 不下发，显式设置才写进 function.strict。"""
        self.assertNotIn("strict", Tool(name="f").to_openai()["function"])
        self.assertTrue(Tool(name="f", strict=True).to_openai()["function"]["strict"])

    def test_openai_payload_carries_parallel_and_strict(self):
        """F5：parallel_tool_calls 与 tools[].function.strict 都要能下发。"""
        params = ModelParameters(tools=[Tool(name="f", strict=True)], parallel_tool_calls=False)
        payload = oc.OpenAICompatProvider(
            ProviderConfig(name="t", type="openai_compat", base_url="http://x.invalid/v1",
                           api_key="k")
        )._build_payload([Message(role="user", content="hi")], params, "m", True)
        self.assertIs(payload["parallel_tool_calls"], False)
        self.assertTrue(payload["tools"][0]["function"]["strict"])

    def test_normalize_adds_missing_index(self):
        """F2：缺 index 时按位置补 —— 否则调用方按 index 聚合会拿到 None。"""
        out = normalize_tool_calls([{"function": {"name": "a", "arguments": "{}"}}])
        self.assertEqual(out[0]["index"], 0)
        self.assertEqual(out[0]["type"], "function")
        self.assertTrue(out[0]["id"])


# ═══════════════════════ B3. F3：Anthropic 工具选择 ═══════════════════════
class AnthropicToolChoiceTest(unittest.TestCase):
    def _params(self, **kw):
        return ModelParameters(tools=_tool_decl(), **kw)

    def test_forced_tool_with_manual_thinking_downgrades(self):
        """F3：`any`/`tool` 与手工思考（type=enabled）互斥 → 降级 auto 并如实记账。"""
        notes: dict = {}
        got = _tool_choice_setup(self._params(tool_choice="required"),
                                 {"type": "enabled"}, None, notes)
        self.assertEqual(got, {"type": "auto"})
        self.assertIn("tool_choice_downgraded", notes)

    def test_forced_tool_with_adaptive_thinking_is_kept(self):
        """adaptive 推断思考与强制调用兼容，不降级。"""
        notes: dict = {}
        got = _tool_choice_setup(self._params(tool_choice="required"),
                                 {"type": "adaptive"}, None, notes)
        self.assertEqual(got, {"type": "any"})
        self.assertEqual(notes, {})

    def test_rule_level_rejection_downgrades_any_case(self):
        """Fable5.1 / Mythos5.1：任何情况都拒强制调用（规则级开关）。"""
        notes: dict = {}
        rule = ModelRule(pattern="x", reject_forced_tool=True)
        got = _tool_choice_setup(self._params(tool_choice="required"), None, rule, notes)
        self.assertEqual(got, {"type": "auto"})
        self.assertIn("tool_choice_downgraded", notes)

    def test_parallel_false_rides_on_tool_choice(self):
        """原生没有独立并行开关，parallel=False 并进 tool_choice.disable_parallel_tool_use。"""
        notes: dict = {}
        got = _tool_choice_setup(self._params(parallel_tool_calls=False), None, None, notes)
        self.assertEqual(got, {"type": "auto", "disable_parallel_tool_use": True})

    def test_auto_is_untouched(self):
        notes: dict = {}
        self.assertEqual(_tool_choice_setup(self._params(tool_choice="auto"), None, None, notes),
                         {"type": "auto"})
        self.assertEqual(notes, {})


if __name__ == "__main__":
    unittest.main(verbosity=2)

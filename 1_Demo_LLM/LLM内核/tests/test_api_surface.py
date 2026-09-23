"""对外 API 面（函数库）契约用例。

本文件回答三个问题（与加解密内核的 `ApiSurfaceTest` 同构）：

1. **入口唯一**：`palm_llm` 顶层导出与 `palm_llm.api` 一致，内部件（`_` 前缀）不可由旧路径导入。
2. **同功能已合并**：四个 `usage_from_*` / 两个 `resolve_*` / 两个 `error_for_*` /
   三个 request_id / 三个 data-uri 包装，各自只剩**一个**入口且行为等价。
3. **新动词可用**：`stream()` / `complete()` 走真实链路能用（httpx.MockTransport 回放）。
"""
from __future__ import annotations

import importlib
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

import palm_llm  # noqa: E402
from palm_llm import api  # noqa: E402
from palm_llm.models import Message, ModelParameters, ProviderConfig  # noqa: E402
from palm_llm.providers import PROTOCOLS  # noqa: E402
from palm_llm.providers import openai_compat as oc  # noqa: E402
from palm_llm.providers._multimodal import (  # noqa: E402
    DEFAULT_FILE_MIME,
    DEFAULT_MIME,
    data_uri,
)
from palm_llm.providers._profiles import _match_rule, resolve  # noqa: E402
from palm_llm.providers._profiles_data import PROFILES  # noqa: E402
from palm_llm.providers._telemetry import usage_from  # noqa: E402

# 硬切掉的旧名字（任何一个复活都说明合并没落干净）
REMOVED = (
    "error_for_status", "error_for_transport",
    "usage_from_openai", "usage_from_anthropic", "usage_from_gemini", "usage_from_ollama",
    "resolve_provider", "resolve_model",
    "new_request_id", "get_request_id", "ensure_request_id",
    "image_url", "file_uri",
)

# 硬切掉的旧模块路径
REMOVED_MODULES = (
    "palm_llm.providers.profiles", "palm_llm.providers.profiles_data",
    "palm_llm.providers.telemetry", "palm_llm.providers.multimodal",
    "palm_llm.providers.capability", "palm_llm.providers.tooltext",
    "palm_llm.providers.anthropic_wire", "palm_llm.providers.gemini_wire",
)


def _sse(*events: dict) -> bytes:
    return "".join("data: %s\n\n" % json.dumps(e, ensure_ascii=False)
                   for e in events).encode("utf-8")


class EntryPointTest(unittest.TestCase):
    def test_top_level_matches_api(self):
        """`palm_llm` 只是 `palm_llm.api` 的转出 —— 两份清单必须逐字一致。"""
        self.assertEqual(list(palm_llm.__all__), list(api.__all__))
        for name in api.__all__:
            self.assertTrue(hasattr(palm_llm, name), name)

    def test_legacy_names_are_gone(self):
        """旧名字硬切：顶层与各实现模块都不得再有。"""
        for name in REMOVED:
            with self.subTest(name=name):
                self.assertFalse(hasattr(palm_llm, name),
                                 f"{name} 仍在 palm_llm 顶层导出")

    def test_legacy_modules_are_gone(self):
        """内部件已私有化：旧模块路径必须导入失败（防止偷偷耦合回去）。"""
        for mod in REMOVED_MODULES:
            with self.subTest(mod=mod):
                with self.assertRaises(ModuleNotFoundError):
                    importlib.import_module(mod)

    def test_describe_lists_the_surface(self):
        d = api.describe()
        self.assertEqual(d["version"], palm_llm.__version__)
        for fn in ("stream", "complete", "classify_error", "request_id", "protocols"):
            self.assertIn(fn, d["functions"])
        self.assertEqual(set(d["protocols"]), set(PROTOCOLS))


class UsageFromTest(unittest.TestCase):
    """四个 usage 解析合并为 `usage_from(raw, protocol)`。"""

    def test_four_protocols_dispatch(self):
        oa = usage_from({"prompt_tokens": 100, "completion_tokens": 10,
                         "prompt_tokens_details": {"cached_tokens": 90}}, "openai")
        self.assertEqual((oa["input_tokens"], oa["cache_read_tokens"]), (10, 90))

        an = usage_from({"input_tokens": 5, "output_tokens": 7,
                         "cache_read_input_tokens": 3}, "anthropic")
        self.assertEqual((an["input_tokens"], an["total_tokens"]), (5, 15))

        ge = usage_from({"promptTokenCount": 50, "cachedContentTokenCount": 20,
                         "candidatesTokenCount": 5, "thoughtsTokenCount": 2}, "gemini")
        self.assertEqual((ge["input_tokens"], ge["reasoning_tokens"]), (30, 2))

        ol = usage_from({"prompt_eval_count": 4, "eval_count": 6,
                         "eval_duration": 1_000_000_000}, "ollama")
        self.assertEqual((ol["total_tokens"], ol["decode_ms"]), (10, 1000.0))

    def test_unknown_protocol_falls_back_to_openai(self):
        """未知协议按 openai 处理 —— 与厂"未知 type 回落 openai_compat"同一口径。"""
        got = usage_from({"prompt_tokens": 10, "completion_tokens": 1}, "not-a-protocol")
        self.assertEqual(got["input_tokens"], 10)
        self.assertEqual(got["output_tokens"], 1)


class ClassifyErrorTest(unittest.TestCase):
    """两个错误分类器合并为 `classify_error`。"""

    def test_status_source(self):
        self.assertIsInstance(api.classify_error("x", status=429), palm_llm.RateLimitError)
        self.assertIsInstance(api.classify_error("x", status=503), palm_llm.UpstreamServerError)

    def test_transport_source(self):
        self.assertIsInstance(api.classify_error("x", exc=RuntimeError("reset")),
                              palm_llm.TransportError)
        self.assertIsInstance(
            api.classify_error("x", exc=RuntimeError("reset"), interrupted=True),
            palm_llm.StreamInterruptedError)

    def test_status_wins_when_both_given(self):
        """两条来源互斥；同时给时以 `status` 为准（HTTP 层比 socket 层更具体）。"""
        err = api.classify_error("x", status=400, exc=RuntimeError("reset"))
        self.assertIsInstance(err, palm_llm.BadRequestError)


class RequestIdTest(unittest.TestCase):
    """4 个 request_id 入口合并为 `request_id()` + `set_request_id()`。"""

    def test_read_generates_and_sticks(self):
        api.set_request_id("fixed-1")
        self.assertEqual(api.request_id(), "fixed-1")

    def test_set_none_generates(self):
        api.set_request_id(None)
        rid = api.request_id()
        self.assertNotEqual(rid, "-")
        self.assertEqual(len(rid), 12)


class DataUriTest(unittest.TestCase):
    """三个 data-uri 包装合并为一个（只差默认 mime）。"""

    def test_kind_differs_only_by_default_mime(self):
        self.assertEqual(data_uri({"data": "A"}), "data:%s;base64,A" % DEFAULT_MIME)
        self.assertEqual(data_uri({"data": "A"}, DEFAULT_FILE_MIME),
                         "data:%s;base64,A" % DEFAULT_FILE_MIME)

    def test_explicit_mime_wins(self):
        self.assertEqual(data_uri({"data": "A", "mime": "image/webp"}),
                         "data:image/webp;base64,A")


class ResolveTest(unittest.TestCase):
    """两级匹配合并为 `resolve(base_url, model, type_hint)`。"""

    def test_two_levels_in_one_call(self):
        profile, rule = resolve("https://open.bigmodel.cn/api/paas/v4", "glm-5.3")
        self.assertEqual(profile.name, "glm")
        self.assertIsNotNone(rule)
        self.assertEqual(rule.thinking, "always_on")

    def test_unmatched_model_falls_back_silently(self):
        profile, rule = resolve("https://api.deepseek.com", "some-new-model")
        self.assertEqual(profile.name, "deepseek")
        self.assertIsNone(rule)

    def test_type_hint_beats_domain(self):
        self.assertEqual(resolve("https://open.bigmodel.cn", "", "kimi")[0].name, "kimi")

    def test_match_rule_is_the_profile_in_hand_entry(self):
        """`_match_rule` 是"Profile 已在手上"的二级入口（常规调用走 `resolve`）。"""
        prof, rule = _match_rule(PROFILES["glm"], "glm-9.9-turbo")
        self.assertIs(prof, PROFILES["glm"])
        self.assertIsNone(rule)


class CallVerbsTest(unittest.IsolatedAsyncioTestCase):
    """新动词 `stream()` / `complete()` 走真实链路（MockTransport 回放）。"""

    def _patch(self, *responses):
        seen: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(json.loads(request.content))
            return responses[min(len(seen) - 1, len(responses) - 1)]

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self._orig = oc.get_client
        oc.get_client = lambda: client
        return seen

    def tearDown(self):
        if hasattr(self, "_orig"):
            oc.get_client = self._orig

    def _cfg(self) -> ProviderConfig:
        return ProviderConfig(name="t", type="openai_compat",
                              base_url="http://x.invalid/v1", api_key="k",
                              default_model="m")

    async def test_stream_yields_increments(self):
        self._patch(httpx.Response(200, content=_sse(
            {"choices": [{"delta": {"content": "你"}}]},
            {"choices": [{"delta": {"content": "好"}}], "usage": {"prompt_tokens": 3,
                                                                 "completion_tokens": 2}},
            {"choices": [{"delta": {}, "finish_reason": "stop"}]},
        )))
        got = [ev async for ev in api.stream([Message(role="user", content="hi")],
                                             cfg=self._cfg())]
        self.assertEqual("".join(e["content"] for e in got if "content" in e), "你好")
        self.assertTrue(got[-1]["done"])
        self.assertIn("stats", got[-1])

    async def test_complete_aggregates_and_reports_stats(self):
        self._patch(httpx.Response(200, content=_sse(
            {"choices": [{"delta": {"reasoning_content": "想"}}]},
            {"choices": [{"delta": {"content": "答"}}], "usage": {"prompt_tokens": 4,
                                                                 "completion_tokens": 1}},
            {"choices": [{"delta": {}, "finish_reason": "stop"}]},
        )))
        out = await api.complete([Message(role="user", content="hi")], cfg=self._cfg())
        self.assertEqual(out["content"], "答")
        self.assertEqual(out["reasoning"], "想")
        self.assertIsNone(out["tool_calls"])
        self.assertEqual(out["finish_reason"], "stop")
        self.assertEqual(out["stats"]["input_tokens"], 4)

    async def test_default_model_comes_from_config(self):
        seen = self._patch(httpx.Response(200, content=_sse(
            {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]})))
        await api.complete([Message(role="user", content="hi")], cfg=self._cfg())
        self.assertEqual(seen[0]["model"], "m")        # cfg.default_model 兜底

    async def test_missing_cfg_and_prov_raises(self):
        with self.assertRaises(palm_llm.NotConfiguredError):
            await api.complete([Message(role="user", content="hi")])

    async def test_existing_instance_is_reused(self):
        seen = self._patch(httpx.Response(200, content=_sse(
            {"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]})))
        prov = oc.OpenAICompatProvider(self._cfg())
        await api.complete([Message(role="user", content="hi")], prov=prov)
        self.assertEqual(len(seen), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)

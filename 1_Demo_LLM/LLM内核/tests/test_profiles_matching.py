"""两级匹配（端点一级 / 模型二级）的用例。

覆盖：域名与 type 优先级、模型规则命中、未命中回落不报错、参数卫生、思考参数翻译、
以及经 `OpenAICompatProvider` 组装后的真实 payload。
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
from palm_llm.providers.profiles import apply_rule, resolve_model, resolve_provider
from palm_llm.providers.profiles_data import GLM, KIMI, PROFILES


def _payload(model: str, extra_body=None, temperature=0.7, base="http://x.invalid/v1",
             ptype="openai_compat"):
    """走真实链路：resolve → build → apply_rule，返回最终请求体。"""
    cfg = ProviderConfig(name="t", type=ptype, base_url=base, api_key="k")
    prof, rule = resolve_model(resolve_provider(cfg.base_url, cfg.type), model)
    built = oc.OpenAICompatProvider(cfg)._build_payload(
        [Message(role="user", content="你好")],
        ModelParameters(temperature=temperature, extra_body=extra_body),
        model, True)
    return apply_rule(built, prof, rule)


class LevelOneTest(unittest.TestCase):
    def test_domain_hint(self):
        self.assertEqual(resolve_provider("https://open.bigmodel.cn/api/paas/v4").name, "glm")
        self.assertEqual(resolve_provider("https://api.moonshot.cn/v1").name, "kimi")
        self.assertEqual(resolve_provider("https://api.deepseek.com").name, "deepseek")

    def test_type_hint_beats_domain(self):
        self.assertEqual(resolve_provider("https://open.bigmodel.cn", "kimi").name, "kimi")

    def test_unknown_falls_back_to_generic(self):
        self.assertEqual(resolve_provider("http://unknown.example").name, "generic")

    def test_all_profiles_registered(self):
        self.assertEqual(set(PROFILES) >=
                         {"generic", "glm", "kimi", "deepseek", "openai",
                          "anthropic", "gemini", "qwen", "doubao", "hunyuan"}, True)


class LevelTwoTest(unittest.TestCase):
    def test_glm53_hits_always_on(self):
        _, rule = resolve_model(GLM, "glm-5.3")
        self.assertIsNotNone(rule)
        self.assertEqual(rule.thinking, "always_on")

    def test_glm53_flash_shares_rule(self):
        _, rule = resolve_model(GLM, "glm-5.3-flash")
        self.assertIsNotNone(rule)
        self.assertEqual(rule.thinking, "always_on")

    def test_unknown_model_returns_no_rule(self):
        prof, rule = resolve_model(GLM, "glm-9.9-turbo")
        self.assertIsNone(rule)
        self.assertIs(prof, GLM)          # 回落供应商默认，不报错

    def test_specific_rule_wins_by_priority(self):
        _, rule = resolve_model(KIMI, "kimi-k2.7-code")
        self.assertEqual(rule.fixed_params["temperature"], 1.0)


class ApplyRuleTest(unittest.TestCase):
    def test_glm53_off_degrades_to_low(self):
        out = _payload("glm-5.3", {"thinking": {"type": "disabled"}},
                       base="https://open.bigmodel.cn")
        self.assertEqual(out["thinking"], {"type": "enabled"})   # 关不掉
        self.assertEqual(out["reasoning_effort"], "low")

    def test_kimi_code_forces_temperature(self):
        out = _payload("kimi-k2.7-code", {"enable_thinking": True},
                       temperature=0.3, base="https://api.moonshot.cn")
        self.assertEqual(out["temperature"], 1.0)
        self.assertEqual(out["top_p"], 0.95)

    def test_opus47_uses_adaptive_and_drops_budget(self):
        out = _payload("claude-opus-4-7", {"budget_tokens": 5000},
                       base="https://api.anthropic.com")
        self.assertEqual(out["thinking"], {"type": "adaptive"})
        self.assertNotIn("budget_tokens", out)

    def test_deepseek_flash_maps_xhigh_to_high(self):
        out = _payload("deepseek-v4-flash", {"reasoning_effort": "xhigh"},
                       base="https://api.deepseek.com")
        self.assertEqual(out["reasoning_effort"], "high")

    def test_deepseek_pro_maps_xhigh_to_max(self):
        out = _payload("deepseek-v4-pro", {"reasoning_effort": "xhigh"},
                       base="https://api.deepseek.com")
        self.assertEqual(out["reasoning_effort"], "max")

    def test_doubao_character_drops_thinking(self):
        out = _payload("doubao-seed-character-251128",
                       {"thinking": {"type": "disabled"}}, base="https://ark.volces.com")
        self.assertNotIn("thinking", out)

    def test_qwen_vl_translates_to_enable_thinking(self):
        out = _payload("qwen3-vl-plus", {"reasoning_effort": "high"},
                       base="https://dashscope.aliyuncs.com")
        self.assertTrue(out["enable_thinking"])

    def test_qwen_omni_flash_forbids_thinking_budget(self):
        out = _payload("qwen3.8-omni-flash",
                       {"reasoning_effort": "xhigh", "thinking_budget": 8192},
                       base="https://dashscope.aliyuncs.com")
        self.assertNotIn("thinking_budget", out)

    def test_generic_model_passes_through(self):
        out = _payload("some-unknown-model", {"foo": 1})
        self.assertEqual(out["foo"], 1)     # 未命中 → 原样透传


class EndToEndTest(unittest.IsolatedAsyncioTestCase):
    async def test_real_request_carries_rule_output(self):
        seen: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(json.loads(request.content))
            return httpx.Response(200, content=b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
                                               b'data: [DONE]\n\n')

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        orig = oc.get_client
        oc.get_client = lambda: client
        try:
            cfg = ProviderConfig(name="t", type="openai_compat",
                                 base_url="https://open.bigmodel.cn/api/paas/v4", api_key="k")
            prov = oc.OpenAICompatProvider(cfg)
            async for _ in prov.complete([Message(role="user", content="你好")],
                                         ModelParameters(extra_body={"thinking": {"type": "disabled"}}),
                                         model="glm-5.3"):
                pass
        finally:
            oc.get_client = orig

        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]["thinking"], {"type": "enabled"})
        self.assertEqual(seen[0]["reasoning_effort"], "low")


if __name__ == "__main__":
    unittest.main(verbosity=2)

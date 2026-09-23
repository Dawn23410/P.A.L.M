"""能力矩阵前置拦截用例（纯逻辑，无需网络）。

覆盖：
  - 视觉闸门：已知不支持视觉的模型带图 → 发请求前抛错
  - 未知档位（generic / ollama）→ 不拦，只记 capability_unknown（宁可放过不可错杀）
  - 文档闸门：整家不吃文档（reject_documents）/ 类型不在白名单 / 单文件与合计超限
  - 多模态 content blocks 与 files 的渲染（openai / anthropic 两种模式）
  - 闸门真的挂在 provider.complete() 上（拦截发生在任何 HTTP 之前）
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from palm_llm.models import Message, ModelParameters, ProviderConfig  # noqa: E402
from palm_llm.providers.capability import (  # noqa: E402
    CapabilityError,
    _b64_len,
    capabilities_for,
    check_capabilities,
)
from palm_llm.providers.multimodal import content_blocks  # noqa: E402
from palm_llm.providers.profiles import resolve_model, resolve_provider  # noqa: E402

# 造一个"已知能力"的模型对：DeepSeek 全系不吃文档，只有 flash 支持图像
VISION_MODEL = "deepseek-flash"
TEXT_MODEL = "deepseek-v4-pro"
GENERIC_MODEL = "llama3.2:3b"


def _merged(base_url: str, type_hint: str, model: str):
    return resolve_model(resolve_provider(base_url, type_hint), model)[0]


def _pdf(b64_chars: int = 40) -> str:
    return "data:application/pdf;base64," + ("A" * b64_chars)


def _img() -> str:
    return "data:image/png;base64,iVBORw0KGgo="


def _check(messages, base_url="", type_hint="deepseek", model=""):
    return check_capabilities(messages, _merged(base_url, type_hint, model), model, "test")


class VisionGateTest(unittest.TestCase):
    def test_text_only_model_with_image_is_blocked(self):
        with self.assertRaises(CapabilityError) as ctx:
            _check([Message(role="user", content="看这张图", images=[_img()])],
                   model=TEXT_MODEL)
        msg = str(ctx.exception)
        self.assertIn("不支持视觉输入", msg)
        self.assertIn("第 1 条消息", msg)          # 报错要能定位到具体消息
        self.assertIn(TEXT_MODEL, msg)

    def test_vision_capable_model_passes(self):
        self.assertEqual(
            _check([Message(role="user", images=[_img()])], model=VISION_MODEL), {})

    def test_generic_tier_does_not_block_but_records(self):
        """ollama / generic 档位模型名不固定 —— 硬拦会把 llava 打死，故只记账。"""
        notes = _check([Message(role="user", images=[_img()])],
                       type_hint="ollama", model=GENERIC_MODEL)
        self.assertIn("capability_unknown", notes)
        self.assertIn("未做能力校验", notes["capability_unknown"])

    def test_message_index_is_one_based(self):
        msgs = [Message(role="user", content="hi"),
                Message(role="user", content="看", images=[_img()])]
        with self.assertRaises(CapabilityError) as ctx:
            _check(msgs, model=TEXT_MODEL)
        self.assertIn("第 2 条消息", str(ctx.exception))


class DocumentGateTest(unittest.TestCase):
    def test_family_that_rejects_documents_is_blocked(self):
        with self.assertRaises(CapabilityError) as ctx:
            _check([Message(role="user", content="总结", files=[_pdf()])], model=VISION_MODEL)
        self.assertIn("不原生支持文档输入", str(ctx.exception))

    def test_glm_text_model_rejects_but_flash_accepts(self):
        """能力矩阵 v2.0：GLM 文本系列不吃文档，5.3-Flash 才是多模态+文件那个变体。"""
        texts = [Message(role="user", content="总结", files=[_pdf()])]
        with self.assertRaises(CapabilityError):
            _check(texts, type_hint="glm", model="glm-5.3")
        self.assertEqual(_check(texts, type_hint="glm", model="glm-5.3-flash"), {})

    def test_glm_text_model_rejects_image_too(self):
        with self.assertRaises(CapabilityError):
            _check([Message(role="user", images=[_img()])], type_hint="glm", model="glm-5.3")

    def test_mime_outside_declared_list_is_blocked(self):
        doc = {"mime": "application/msword", "data": "AAAA", "name": "a.doc"}
        with self.assertRaises(CapabilityError) as ctx:
            _check([Message(role="user", files=[doc])], type_hint="gemini",
                   model="gemini-2.5-flash")
        self.assertIn("application/msword", str(ctx.exception))
        self.assertIn("application/pdf", str(ctx.exception))   # 提示里给出可用类型

    def test_declared_mime_passes(self):
        doc = {"mime": "application/pdf", "data": "AAAA", "name": "a.pdf"}
        self.assertEqual(
            _check([Message(role="user", files=[doc])], type_hint="gemini",
                   model="gemini-2.5-flash"), {})

    def test_single_file_over_limit_is_blocked(self):
        doc = {"mime": "application/pdf", "data": "AAAA", "name": "big.pdf",
               "size": 60 * 1024 * 1024}
        with self.assertRaises(CapabilityError) as ctx:
            _check([Message(role="user", files=[doc])], type_hint="gemini",
                   model="gemini-2.5-flash")
        self.assertIn("超过单文件上限 50", str(ctx.exception))

    def test_total_over_limit_is_blocked(self):
        """单文件都不超、但合计超 —— 官方口径里单请求合计与单文件是两条限制。"""
        mk = lambda i: {"mime": "application/pdf", "data": "AAAA", "name": f"{i}.pdf",
                        "size": 30 * 1024 * 1024}
        with self.assertRaises(CapabilityError) as ctx:
            _check([Message(role="user", files=[mk(1), mk(2)])], type_hint="gemini",
                   model="gemini-2.5-flash")
        self.assertIn("合计", str(ctx.exception))

    def test_image_mime_inside_files_goes_through_vision_gate(self):
        doc = {"mime": "image/png", "data": "AAAA", "name": "a.png"}
        with self.assertRaises(CapabilityError) as ctx:
            _check([Message(role="user", files=[doc])], model=TEXT_MODEL)
        self.assertIn("不支持视觉输入", str(ctx.exception))

    def test_remote_url_is_not_guessed(self):
        """拿不到 mime/大小的附件不猜、不拦，只记一条跳过说明。"""
        notes = _check([Message(role="user", files=["https://example.com/a.pdf"])],
                       type_hint="gemini", model="gemini-2.5-flash")
        self.assertIn("capability_size_unchecked", notes)


class QueryApiTest(unittest.TestCase):
    def test_capabilities_for_reports_matrix(self):
        got = capabilities_for("", "deepseek", "deepseek-flash")
        self.assertEqual(got["profile"], "deepseek")
        self.assertTrue(got["supports_vision"])
        self.assertTrue(got["reject_documents"])
        self.assertEqual(got["rule"], r"deepseek-(v4-flash|flash).*")

    def test_generic_tier_is_marked_unknown(self):
        got = capabilities_for("http://127.0.0.1:11434", "ollama", "llama3.2:3b")
        self.assertFalse(got["capabilities_known"])

    def test_openai_documents_are_pdf_only(self):
        """Chat Completions 只收 .pdf —— 白名单必须窄，否则闸门形同虚设。"""
        got = capabilities_for("https://api.openai.com/v1", "openai", "gpt-5")
        self.assertEqual(got["doc_mimes"], ("application/pdf",))

    def test_deprecated_names_still_resolve(self):
        """改名/下线只补 note 不删规则 —— 存量配置不能因此匹配失败。"""
        self.assertEqual(capabilities_for("", "deepseek", "deepseek-v4-flash")["profile"],
                         "deepseek")
        self.assertEqual(capabilities_for("", "kimi", "kimi-k2.5")["profile"], "kimi")

    def test_no_attachments_no_notes(self):
        self.assertEqual(_check([Message(role="user", content="只有文本")],
                                model=TEXT_MODEL), {})


class Base64LengthTest(unittest.TestCase):
    def test_length_is_derived_without_decoding(self):
        self.assertEqual(_b64_len(_pdf(1000)), 750)     # 1000*3/4
        self.assertEqual(_b64_len(_pdf(999) + "A"), 750)


class MultimodalRenderTest(unittest.TestCase):
    def test_openai_file_block_uses_filename_and_data_uri(self):
        doc = {"mime": "application/pdf", "data": "AAAA", "name": "a.pdf"}
        blocks = content_blocks("总结", None, files=[doc])
        self.assertEqual(blocks[-1], {
            "type": "file",
            "file": {"filename": "a.pdf", "file_data": "data:application/pdf;base64,AAAA"},
        })

    def test_openai_file_block_builds_name_from_mime_when_absent(self):
        blocks = content_blocks("", None, files=[_pdf()])
        self.assertEqual(blocks[-1]["file"]["filename"], "document.pdf")

    def test_anthropic_file_block_is_document_source(self):
        blocks = content_blocks("总结", None, mode="anthropic",
                               files=[{"mime": "application/pdf", "data": "AAAA"}])
        self.assertEqual(blocks[-1], {
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf", "data": "AAAA"},
        })

    def test_message_to_openai_keeps_file_and_drops_empty_text(self):
        out = Message(role="user", files=[_pdf()]).to_openai()
        self.assertEqual(len(out["content"]), 1)
        self.assertEqual(out["content"][0]["type"], "file")

    def test_message_to_openai_mixes_text_image_and_file(self):
        out = Message(role="user", content="看看", images=[_img()],
                      files=[_pdf()]).to_openai()
        self.assertEqual([b["type"] for b in out["content"]],
                         ["text", "image_url", "file"])


class GateIsWiredTest(unittest.IsolatedAsyncioTestCase):
    """闸门必须挂在 complete() 上，且**在任何网络往返之前**触发。"""

    def _explode_transport(self):
        def handler(request):  # noqa: ANN001
            raise AssertionError(f"闸门没拦住，请求已经发出去了：{request.url}")
        return httpx.MockTransport(handler)

    async def _run(self, provider, model, messages):
        out = []
        async for ev in provider.complete(messages, ModelParameters(), model, stream=False):
            out.append(ev)
        return out

    async def test_openai_compat_blocks_before_http(self):
        from palm_llm.providers.openai_compat import OpenAICompatProvider
        from palm_llm.providers import base as base_mod

        prov = OpenAICompatProvider(ProviderConfig(
            name="ds", type="deepseek", base_url="https://api.deepseek.com/v1", api_key="k"))
        orig = base_mod.get_client
        base_mod.get_client = lambda: httpx.AsyncClient(transport=self._explode_transport())
        try:
            with self.assertRaises(CapabilityError):
                await self._run(prov, TEXT_MODEL, [Message(role="user", images=[_img()])])
        finally:
            base_mod.get_client = orig

    async def test_gemini_blocks_before_http(self):
        from palm_llm.providers import gemini as gm
        from palm_llm.providers.gemini import GeminiProvider

        prov = GeminiProvider(ProviderConfig(
            name="g", type="gemini", base_url="https://generativelanguage.googleapis.com",
            api_key="k"))
        orig = gm.get_client
        gm.get_client = lambda: httpx.AsyncClient(transport=self._explode_transport())
        try:
            doc = {"mime": "application/msword", "data": "AAAA", "name": "a.doc"}
            with self.assertRaises(CapabilityError):
                await self._run(prov, "gemini-2.5-flash", [Message(role="user", files=[doc])])
        finally:
            gm.get_client = orig

    async def test_generic_tier_reaches_transport_with_note(self):
        """未知档位不该被拦下：请求要真的发出去，并把"未校验"记进 stats.extra。"""
        from palm_llm.providers import ollama as ol
        from palm_llm.providers.ollama import OllamaProvider

        seen = {}

        def handler(request):  # noqa: ANN001
            seen["called"] = True
            body = json.dumps({"message": {"content": "hi"}, "done": True,
                               "done_reason": "stop"}).encode()
            return httpx.Response(200, content=body)

        prov = OllamaProvider(ProviderConfig(
            name="ollama", type="ollama", base_url="http://127.0.0.1:11434"))
        orig = ol.get_client
        ol.get_client = lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            events = await self._run(prov, "llava:latest", [Message(role="user", images=[_img()])])
        finally:
            ol.get_client = orig
        self.assertTrue(seen.get("called"), "未知档位被误拦，请求没发出去")
        self.assertIn("capability_unknown", events[-1]["stats"]["extra"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

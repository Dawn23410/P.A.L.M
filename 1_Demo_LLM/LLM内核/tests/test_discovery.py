"""palm_llm.server.discovery + palm_llm.providers.multimodal 回归测试。

目的：守护「抽公共脚手架后行为逐字不变」——
- 三个原生协议的模型发现错误文案（404/401/403/连接失败）必须与重构前**完全一致**；
- 字段抽取（ollama models[].name / anthropic data[].id / gemini models[].name 剥前缀）正确；
- multimodal 的 data_uri / image_url / file_uri 等价且 data URI 透传。

设计：不依赖任何真实服务，用假 client（async get）驱动。
运行：
    D:/P.A.L.M/1_Demo_LLM/LLM内核/.gwbench_venv/Scripts/python.exe -m unittest tests/test_discovery.py
"""
from __future__ import annotations

import asyncio
import httpx
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from palm_llm.providers.multimodal import data_uri, file_uri, image_url  # noqa: E402
from palm_llm.server.discovery import (  # noqa: E402
    _discover_anthropic,
    _discover_gemini,
    _discover_ollama,
)


class _Resp:
    def __init__(self, status: int, payload):
        self.status_code = status
        self._payload = payload
        self.headers = {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("status", request=None, response=self)


class _Client:
    def __init__(self, resp: _Resp):
        self._resp = resp
        self.last_url = None
        self.last_headers = None

    async def get(self, url, headers=None):
        self.last_url = url
        self.last_headers = headers or {}
        return self._resp


class _ClientRaise:
    async def get(self, url, headers=None):
        raise httpx.TransportError("boom")


BASE = "http://example.test"


class DiscoveryTests(unittest.TestCase):
    # ─────────────────────── ollama ───────────────────────
    def test_ollama_success(self):
        c = _Client(_Resp(200, {"models": [{"name": "a"}, {"name": "b"}, {"name": ""}]}))
        out = asyncio.run(_discover_ollama(c, BASE))
        self.assertEqual(out, ["a", "b"])
        self.assertEqual(c.last_url, f"{BASE}/api/tags")

    def test_ollama_404_message(self):
        c = _Client(_Resp(404, {}))
        with self.assertRaises(ValueError) as ctx:
            asyncio.run(_discover_ollama(c, BASE))
        self.assertEqual(str(ctx.exception), (
            f"返回 404：{BASE} 看起来不是 Ollama 原生地址"
            "（原生协议要求根地址，不带 /v1）。"
        ))

    def test_ollama_connect_error_message(self):
        with self.assertRaises(ValueError) as ctx:
            asyncio.run(_discover_ollama(_ClientRaise(), BASE))
        self.assertEqual(str(ctx.exception), (
            f"无法连接 Ollama（{BASE}）：TransportError，请确认服务已启动。"
        ))

    # ─────────────────────── anthropic ───────────────────────
    def test_anthropic_success_headers(self):
        c = _Client(_Resp(200, {"data": [{"id": "claude-1"}, {"id": ""}]}))
        out = asyncio.run(_discover_anthropic(c, BASE, "KEY"))
        self.assertEqual(out, ["claude-1"])
        self.assertEqual(c.last_url, f"{BASE}/v1/models")
        self.assertEqual(c.last_headers.get("x-api-key"), "KEY")
        self.assertIn("anthropic-version", c.last_headers)

    def test_anthropic_401_message(self):
        c = _Client(_Resp(401, {}))
        with self.assertRaises(ValueError) as ctx:
            asyncio.run(_discover_anthropic(c, BASE, "KEY"))
        self.assertEqual(str(ctx.exception), "鉴权失败（401）：API Key 可能无效。")

    def test_anthropic_404_message(self):
        c = _Client(_Resp(404, {}))
        with self.assertRaises(ValueError) as ctx:
            asyncio.run(_discover_anthropic(c, BASE, "KEY"))
        self.assertEqual(str(ctx.exception), (
            f"返回 404：{BASE}/v1/models 不存在。原生协议要求 base_url 填站点根地址"
            "（如 https://api.anthropic.com），不带 /v1。"
        ))

    # ─────────────────────── gemini ───────────────────────
    def test_gemini_success_strips_prefix(self):
        c = _Client(_Resp(200, {"models": [
            {"name": "models/gemini-2.5-flash"}, {"name": "models/y"}, {"name": ""}]}))
        out = asyncio.run(_discover_gemini(c, BASE, "KEY"))
        self.assertEqual(out, ["gemini-2.5-flash", "y"])
        self.assertEqual(c.last_url, f"{BASE}/v1beta/models")
        self.assertEqual(c.last_headers.get("x-goog-api-key"), "KEY")

    def test_gemini_403_message(self):
        c = _Client(_Resp(403, {}))
        with self.assertRaises(ValueError) as ctx:
            asyncio.run(_discover_gemini(c, BASE, "KEY"))
        self.assertEqual(str(ctx.exception), (
            "鉴权失败：API Key 可能无效（原生协议用 x-goog-api-key）。"
        ))

    def test_gemini_404_message(self):
        c = _Client(_Resp(404, {}))
        with self.assertRaises(ValueError) as ctx:
            asyncio.run(_discover_gemini(c, BASE, "KEY"))
        self.assertEqual(str(ctx.exception), (
            f"返回 404：{BASE}/v1beta/models 不存在。原生协议要求 base_url 填站点根地址"
            "（如 https://generativelanguage.googleapis.com），不带 /v1beta。"
        ))


class MultimodalTests(unittest.TestCase):
    def test_data_uri_equiv(self):
        # str 原样（URL / data URI）
        self.assertEqual(image_url("http://x/y.png"), "http://x/y.png")
        self.assertEqual(file_uri("data:application/pdf;base64,ZZZ"),
                         "data:application/pdf;base64,ZZZ")
        # dict → data URI，默认 mime 不同
        self.assertEqual(image_url({"data": "AAA", "mime": "image/png"}),
                         "data:image/png;base64,AAA")
        self.assertEqual(file_uri({"data": "BBB", "mime": "application/pdf"}),
                         "data:application/pdf;base64,BBB")
        # 默认值兜底
        self.assertEqual(image_url({"data": "CCC"}), "data:image/png;base64,CCC")
        self.assertEqual(file_uri({"data": "DDD"}),
                         "data:application/octet-stream;base64,DDD")
        # 公共件与薄包装等价
        self.assertEqual(image_url({"data": "E", "mime": "image/png"}),
                         data_uri({"data": "E"}, "image/png"))
        self.assertEqual(file_uri({"data": "F", "mime": "application/pdf"}),
                         data_uri({"data": "F"}, "application/pdf"))
        # 非 dict/str 退化为 str()
        self.assertEqual(image_url(123), "123")


if __name__ == "__main__":
    unittest.main()

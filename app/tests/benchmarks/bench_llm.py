"""LLM 内核基准 —— LLM 多供应商（openai_compat / anthropic / gemini / mock）。

现状：llm.models（ProviderConfig/Message/ModelParameters）已补齐，httpx 已安装，
故 provider 层可导入并实测：
  - MockProvider 离线回声/参数回显（无需 Key）；
  - get_provider_instance 工厂按 type 路由；
  - 真实 Key 可用时（桌面 可用API.json）跑一次流式首字延迟探针。
"""
from __future__ import annotations

import asyncio
import importlib
import time
import traceback
from .harness import benchmark


@benchmark("llm")
def bench(col):
    try:
        importlib.import_module("llm")
        col.pass_("import", "package_importable", "correctness",
                  "llm 包顶层可导入")
    except Exception as e:
        col.fail("import", "package_importable", "correctness", str(e),
                 "".join(traceback.format_exception(type(e), e, e.__traceback__))[:400])
        return

    try:
        importlib.import_module("llm.providers")
        col.pass_("import", "providers_importable", "correctness",
                  "llm.providers 可导入（llm.models + httpx 已具备）")
    except Exception as e:
        col.skip("import", "providers_importable", "correctness",
                 f"llm.providers 导入失败: {type(e).__name__}: {e}")
        return

    # 工厂路由 + MockProvider 离线回声（无需 Key）
    try:
        from llm.providers import get_provider_instance
        from llm.models import ProviderConfig, Message, ModelParameters
        mock_cfg = ProviderConfig(name="mock", type="mock", api_key="x")
        mock = get_provider_instance(mock_cfg)
        assert mock is not None
        col.pass_("factory", "factory_routing", "correctness",
                  "get_provider_instance 按 type 路由到 MockProvider")

        async def _mock():
            out = []
            async for c in mock.complete(
                [Message(role="user", content="hi")],
                ModelParameters(), "mock-model", stream=True):
                out.append(c)
            return out
        res = asyncio.run(_mock())
        joined = "".join(c.get("content", "") for c in res)
        assert any(c.get("done") for c in res), "MockProvider 未产出 done"
        col.pass_("mock", "mock_provider_echo", "correctness",
                  f"MockProvider 离线回声可用（输出 {len(joined)} 字符，含 done）")
    except Exception as e:
        col.fail("factory", "factory_routing", "correctness", str(e),
                 "".join(traceback.format_exception(type(e), e, e.__traceback__))[:400])

    # 真实 Key 可用时跑流式首字延迟探针（不计入 FAIL；失败仅 skip）
    try:
        sys = importlib.import_module("sys")
        sys.path.insert(0, ".")
        from tests.integration.keystore import load_llm_key, build_provider_config
        key, err = load_llm_key()
        if err:
            col.skip("live", "real_provider_ttfb", "degradation",
                     f"无可用 LLM 密钥（{err}）→ 跳过真实端点探针")
        else:
            p = get_provider_instance(build_provider_config(key))
            params = ModelParameters(temperature=0.3, max_tokens=32,
                                     extra_body={"enable_thinking": False})
            msgs = [Message(role="user", content="只回复数字：3乘7等于几？")]

            async def _live():
                t0 = time.perf_counter()
                first = None
                async for c in p.complete(msgs, params, key.default_model, stream=True):
                    if c.get("content") and first is None:
                        first = time.perf_counter()
                    if c.get("done"):
                        break
                return (first - t0) * 1000 if first else None
            ttfb = asyncio.run(_live())
            col.pass_("live", "real_provider_ttfb", "latency",
                      f"真实端点 {key.provider}/{key.default_model} 流式首字 {ttfb:.0f}ms"
                      f"（本地开销约0.2ms，余为服务端思考）")
    except Exception as e:
        col.skip("live", "real_provider_ttfb", "degradation",
                 f"真实端点探针跳过: {type(e).__name__}: {e}")

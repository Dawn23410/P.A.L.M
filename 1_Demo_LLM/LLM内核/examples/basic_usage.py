"""palm_llm 函数库用法示例。

直接运行（**无需 API Key、无需联网**）：
    python examples/basic_usage.py

脚本分两部分：
  1. 离线自检 —— 打印函数库清单，并用 httpx.MockTransport 回放让 `stream()` /
     `complete()` 真的跑通一遍（证明入口可用，而不是"文档说可用"）；
  2. 真实调用 —— 设了 `PALM_LLM_EXAMPLE_KEY` 才执行（切勿把 Key 写进代码）。
"""
import asyncio
import json
import os
import sys

import httpx

# 让"从仓库根运行 python examples/basic_usage.py"也能找到 palm_llm
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from palm_llm import (  # noqa: E402
    Message,
    ModelParameters,
    ProviderConfig,
    complete,
    describe,
    stream,
)

MOCK_EVENTS = [
    {"choices": [{"delta": {"reasoning_content": "先想一下。"}}]},
    {"choices": [{"delta": {"content": "你好"}}]},
    {"choices": [{"delta": {"content": "，世界。"}}],
     "usage": {"prompt_tokens": 8, "completion_tokens": 4,
               "prompt_tokens_details": {"cached_tokens": 6}}},
    {"choices": [{"delta": {}, "finish_reason": "stop"}]},
]


def demo_surface() -> None:
    """① 函数库自述：一眼看清这个内核提供什么。"""
    d = describe()
    print("palm_llm %s" % d["version"])
    print("  协议   :", ", ".join(sorted(d["protocols"])))
    print("  函数   :", ", ".join(d["functions"]))
    print("  数据契约:", ", ".join(d["data_types"]))


def _mock_cfg() -> ProviderConfig:
    return ProviderConfig(name="mock", type="openai_compat",
                          base_url="http://mock.invalid/v1", api_key="k",
                          default_model="demo-model")


async def demo_offline() -> None:
    """② 用 MockTransport 回放，让两个调用动词真的跑通。"""
    from palm_llm.providers import openai_compat as oc

    body = "".join("data: %s\n\n" % json.dumps(e, ensure_ascii=False)
                   for e in MOCK_EVENTS).encode("utf-8")
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _req: httpx.Response(200, content=body)))
    orig = oc.get_client
    oc.get_client = lambda: client
    try:
        print("\n>>> stream()：增量到达（首字即出，适合实时展示）")
        async for ev in stream([Message(role="user", content="你好")],
                               ModelParameters(max_tokens=64), cfg=_mock_cfg()):
            if "reasoning" in ev:
                print("    [思考]", ev["reasoning"])
            elif "content" in ev:
                print("    [正文]", ev["content"])
            elif ev.get("done"):
                st = ev["stats"]
                print("    [统计] TTFT=%sms 非缓存输入=%s 缓存命中=%s 输出=%s 结束=%s"
                      % (st["ttft_ms"], st["input_tokens"], st["cache_read_tokens"],
                         st["output_tokens"], st["finish_reason"]))

        print("\n>>> complete()：一次性（把增量拼成整段后返回）")
        out = await complete([Message(role="user", content="你好")], cfg=_mock_cfg())
        print("    正文 :", out["content"])
        print("    思考 :", out["reasoning"])
        print("    工具 :", out["tool_calls"])
        print("    结束 :", out["finish_reason"])
        print("    统一 :", {k: out["stats"][k]
                             for k in ("input_tokens", "cache_read_tokens", "output_tokens")})
    finally:
        oc.get_client = orig


async def demo_real() -> None:
    """③ 真实调用：设了环境变量才跑（换任意 OpenAI 兼容端点均可）。"""
    key = os.environ.get("PALM_LLM_EXAMPLE_KEY", "")
    if not key:
        print("\n[跳过] 未设 PALM_LLM_EXAMPLE_KEY，真实调用未执行。")
        print("       设置方式（PowerShell）：$env:PALM_LLM_EXAMPLE_KEY=\"你的Key\"")
        return
    cfg = ProviderConfig(name="bigmodel", type="openai_compat",
                         base_url="https://open.bigmodel.cn/api/paas/v4",
                         api_key=key, default_model="glm-4.5-air")
    print("\n>>> 真实调用（流式）")
    async for ev in stream([Message(role="user", content="用一句话介绍你自己")], cfg=cfg):
        if "content" in ev:
            print(ev["content"], end="", flush=True)
    print()


def main() -> None:
    demo_surface()
    asyncio.run(demo_offline())
    asyncio.run(demo_real())
    print("\n[ok] palm_llm 函数库示例执行完毕。")


if __name__ == "__main__":
    main()

"""palm_llm 基本用法示例（可直接运行：python examples/basic_usage.py）。

演示：OpenAI 兼容流式调用 + 多模态消息构造 + 非流式调用。
Key 从环境变量 PALM_LLM_EXAMPLE_KEY 读取（切勿硬编码入库）。
"""
import asyncio
import os
import sys

from palm_llm import (
    Message,
    ModelParameters,
    OpenAICompatProvider,
    ProviderConfig,
    Tool,
    get_provider_instance,
)


def build_config() -> ProviderConfig:
    """示例用智谱 BigModel（OpenAI 兼容）；换成任意 OpenAI 兼容端点均可。"""
    api_key = os.environ.get("PALM_LLM_EXAMPLE_KEY", "")
    if not api_key:
        print("请先设置环境变量：set PALM_LLM_EXAMPLE_KEY=你的Key")
        sys.exit(1)
    return ProviderConfig(
        name="bigmodel",
        type="openai_compat",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        api_key=api_key,
        default_model="glm-4.5-air",
    )


async def run_stream() -> None:
    prov = get_provider_instance(build_config())
    print(">>> 流式调用：")
    async for chunk in prov.complete(
        [Message(role="user", content="你好，今天是几号？")],
        ModelParameters(temperature=0.8, max_tokens=256),
        model="glm-4.5-air",
        stream=True,
    ):
        if "content" in chunk:
            print(chunk["content"], end="", flush=True)
        if chunk.get("done"):
            print("\n[usage]", chunk.get("usage"))


async def run_multimodal() -> None:
    # 多模态：images 支持 data URI 或 http(s) URL
    msg = Message(
        role="user",
        content="描述这张图",
        images=["https://example.com/cat.png"],
    )
    prov = get_provider_instance(build_config())
    print("\n>>> 多模态消息 + 非流式：")
    async for chunk in prov.complete([msg], ModelParameters(), model="glm-4.5-air", stream=False):
        print(chunk)


def main() -> None:
    asyncio.run(run_stream())
    asyncio.run(run_multimodal())

    # 直接用具体 Provider 类（不走工厂）也可
    _ = OpenAICompatProvider
    print("\n[ok] palm_llm 基本用法示例执行完毕。")


if __name__ == "__main__":
    main()

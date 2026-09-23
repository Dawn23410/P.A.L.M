"""palm_llm — P.A.L.M 的 LLM 全栈内核（内嵌独立项目）。

多厂商大模型统一**流式**调用层。对外只有**一个入口**（`palm_llm`，等价 `palm_llm.api`），
函数清单与数据契约见 `api.py`；协议四选一（`ProviderConfig.type`）：
`openai_compat`（默认）/ `anthropic` / `ollama` / `gemini`。

设计要点（不变的三条）
----------------------
- 纯异步：`async for chunk in provider.complete(...)`，每个 chunk 是增量字典
  `{"content"}` / `{"reasoning"}` / `{"tool_calls"}` / `{"done", "usage", "stats"}`。
  `stats` 是跨协议归一的回传统一字段（缓存命中 / TTFT / 输出速度…），**新代码只读它**；
  `usage` 保厂商原样，仅为向后兼容。
- 事件循环安全的 httpx 客户端复用（按 loop **对象身份**缓存，跨循环不串号）。
- HTTP/2 优先；未装 h2 时自动降级 HTTP/1.1（仅警告一次）。
- 思考链随增量透传（兼容 `reasoning_content` / `reasoning` / Anthropic 的
  `thinking_delta` / ollama 的 `message.thinking` / Gemini 的 `thought` part）。

最小用法（一次性）
    import asyncio
    from palm_llm import ProviderConfig, Message, complete

    cfg = ProviderConfig(name="demo", type="openai_compat",
                         base_url="https://open.bigmodel.cn/api/paas/v4",
                         api_key="your-key", default_model="glm-4.5-air")
    out = asyncio.run(complete([Message(role="user", content="你好")], cfg=cfg))
    print(out["content"], out["stats"]["ttft_ms"])

最小用法（流式，首字即出）
    from palm_llm import ProviderConfig, Message, stream
    async for ev in stream([Message(role="user", content="你好")], cfg=cfg):
        if "content" in ev:
            print(ev["content"], end="", flush=True)

本地 ollama（`base_url` 是**原生根地址**，不带 `/v1`）：
    cfg = ProviderConfig(name="ollama", type="ollama",
                         base_url="http://127.0.0.1:11434", default_model="spark-x2.5:1.7b")
"""
from __future__ import annotations

from . import api
from .api import *          # noqa: F401,F403
from .api import VERSION as __version__

# `api.__all__` 是唯一事实来源；此处显式声明以免 linters 报 F403 未定义。
__all__ = list(api.__all__)

# 应用服务层（配置 / 会话 / SSE 调度 / CLI）随包挂载，内核 API 保持纯净不被污染。
# 惰性：import palm_llm 时不出错即带出 palm_llm.server 子包。
from . import server  # noqa: E402,F401

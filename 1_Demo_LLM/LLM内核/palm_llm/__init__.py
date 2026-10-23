"""palm_llm — P.A.L.M 的 LLM 全栈包（内嵌独立项目）。

多厂商大模型统一**流式**调用层。协议四选一（`ProviderConfig.type`）：
  - `openai_compat`（默认）—— OpenAI 兼容端点，覆盖国内外绝大多数厂商与网关；
  - `anthropic` —— Anthropic **原生** `/v1/messages`（system 外提、块级 SSE、
    原生缓存 token 字段、`output_config.effort` 档位）；
  - `ollama` —— Ollama **原生** `/api/chat`，本地部署首选（`think` 是一等参数，
    思维链在 `message.thinking`，并返回 token 计数与分段耗时）；
  - `gemini` / `google` —— Gemini **原生** `generateContent`（user/model 两角色、
    `parts[]`、`systemInstruction`、`x-goog-api-key`、无 `[DONE]`）。

设计要点：
  - 纯异步（`async for chunk in provider.complete(...)`），每个 chunk 是增量字典
    `{"content": ...}` / `{"reasoning": ...}` / `{"tool_calls": ...}`
    / `{"done": True, "usage": {...}, "stats": {...}}`；
    `stats` 为跨协议归一的回传统一字段（缓存命中 / TTFT / 输出速度…），新代码只读它；
  - 事件循环安全的 httpx 客户端复用（按 loop 对象身份缓存，跨循环不串号）；
  - HTTP/2 优先，未装 h2 时自动降级 HTTP/1.1（仅一次警告）；
  - 思维链随增量透传（兼容 `reasoning_content` / `reasoning` / Anthropic 的
    `thinking_delta` / ollama 的 `message.thinking`），供前端实时显示。

最小用法：
    from palm_llm import get_provider_instance, ProviderConfig, Message, ModelParameters
    cfg = ProviderConfig(name="demo", type="openai_compat",
                         base_url="https://open.bigmodel.cn/api/paas/v4",
                         api_key="your-key", default_model="glm-4.5-air")
    prov = get_provider_instance(cfg)
    async for chunk in prov.complete(
        [Message(role="user", content="你好")], ModelParameters(), model="glm-4.5-air"
    ):
        print(chunk)

本地 ollama（注意 base_url 是**原生根地址**，不带 /v1）：
    cfg = ProviderConfig(name="ollama", type="ollama",
                         base_url="http://127.0.0.1:11434", default_model="spark-x2.5:1.7b")
    params = ModelParameters(max_tokens=256, extra_body={"reasoning_effort": "none"})  # 或 {"think": False}
"""
from __future__ import annotations

from .errors import (
    AuthError,
    BadRequestError,
    NotConfiguredError,
    PalmLLMError,
    RateLimitError,
    StreamInterruptedError,
    TransportError,
    UpstreamServerError,
)
from .models import Message, ModelParameters, ProviderConfig, Tool
from .obs import configure_logging, get_request_id, set_request_id
from .providers import (
    OLLAMA_DEFAULT_BASE_URL,
    BaseProvider,
    CapabilityError,
    OllamaProvider,
    OpenAICompatProvider,
    capabilities_for,
    get_provider_instance,
)
from .retry import LOW_LATENCY, STABLE, RetryPolicy

__all__ = [
    "Message",
    "ModelParameters",
    "ProviderConfig",
    "Tool",
    "BaseProvider",
    "OpenAICompatProvider",
    "OllamaProvider",
    "OLLAMA_DEFAULT_BASE_URL",
    "CapabilityError",
    "capabilities_for",
    "get_provider_instance",
    # 类型化异常（据错决策：能不能重试 / 要不要等）
    "PalmLLMError",
    "TransportError",
    "UpstreamServerError",
    "RateLimitError",
    "AuthError",
    "BadRequestError",
    "NotConfiguredError",
    "StreamInterruptedError",
    # 重试策略（个人低延迟 / 企业高稳）
    "RetryPolicy",
    "LOW_LATENCY",
    "STABLE",
    # 可观测
    "configure_logging",
    "get_request_id",
    "set_request_id",
]

# 应用服务层（配置 / 会话 / SSE 调度 / WebUI / CLI），内核 API 保持纯净不被污染。
# 惰性挂载：import palm_llm 时不出错即带出 palm_llm.server 子包。
from . import server  # noqa: E402,F401

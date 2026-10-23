"""模型 Provider 抽象层。

支持四种协议：

- `openai_compat` —— OpenAI 兼容 `/chat/completions`。国内外绝大多数厂商
  （智谱 / DeepSeek / OpenAI / Moonshot / 通义 …）与各类网关均走该格式。
- `anthropic` —— Anthropic **原生** `/v1/messages`。system 外提、max_tokens 必填、
  块级 SSE、原生缓存 token 字段、`output_config.effort` 档位，兼容层拿不到这些。
- `ollama` —— Ollama **原生** `/api/chat`（本地部署首选）。原生协议才有明确的
  `think` 一等参数与 `message.thinking` 思维链字段，且返回 token 计数与分段耗时；
  OpenAI 兼容层 `/v1` 在这几点上都有坑，详见 `ollama.py` 模块文档。
- `gemini` —— Gemini **原生** `generateContent`。角色只有 user/model、内容一律
  `parts[]`、system 走 `systemInstruction`、思考参数 3 系列 / 2.5 系列两套并存、
  鉴权用 `x-goog-api-key`，详见 `gemini.py` 模块文档。
"""
from ..errors import (
    AuthError,
    BadRequestError,
    NotConfiguredError,
    PalmLLMError,
    RateLimitError,
    StreamInterruptedError,
    TransportError,
    UpstreamServerError,
)
from ..retry import LOW_LATENCY, STABLE, RetryPolicy
from .anthropic import AnthropicProvider
from .base import BaseProvider
from .capability import CapabilityError, capabilities_for, check_capabilities
from .gemini import GEMINI_DEFAULT_BASE_URL, GeminiProvider
from .ollama import OLLAMA_DEFAULT_BASE_URL, OllamaProvider
from .openai_compat import OpenAICompatProvider
from .telemetry import Meter, TurnStats

__all__ = [
    "BaseProvider",
    "OpenAICompatProvider",
    "AnthropicProvider",
    "OllamaProvider",
    "GeminiProvider",
    "OLLAMA_DEFAULT_BASE_URL",
    "GEMINI_DEFAULT_BASE_URL",
    "Meter",
    "TurnStats",
    "CapabilityError",
    "capabilities_for",
    "check_capabilities",
    "get_provider_instance",
    # 异常层级（类型化错误，供调用方据错决策）
    "PalmLLMError",
    "TransportError",
    "UpstreamServerError",
    "RateLimitError",
    "AuthError",
    "BadRequestError",
    "NotConfiguredError",
    "StreamInterruptedError",
    # 重试策略（企业稳 / 个人快，同一个旋钮）
    "RetryPolicy",
    "LOW_LATENCY",
    "STABLE",
]


def get_provider_instance(cfg) -> BaseProvider:
    """按 cfg.type 取 provider；未知 type 一律回退 openai_compat（容错，非静默失败）。"""
    mapping = {
        "openai_compat": OpenAICompatProvider,
        "anthropic": AnthropicProvider,   # 原生 /v1/messages
        "ollama": OllamaProvider,         # 原生 /api/chat
        "ollama_native": OllamaProvider,  # 显式别名，便于与 openai_compat 打 /v1 区分
        "gemini": GeminiProvider,         # 原生 /v1beta/models/{m}:generateContent
        "google": GeminiProvider,         # 别名：与官方 SDK 的习惯叫法一致
    }
    cls = mapping.get(cfg.type, OpenAICompatProvider)
    return cls(cfg)

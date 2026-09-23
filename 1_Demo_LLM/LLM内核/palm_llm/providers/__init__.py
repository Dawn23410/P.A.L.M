"""模型 Provider 抽象层。

支持四种协议（`cfg.type` 决定，见 `PROTOCOLS`）：

- `openai_compat` —— OpenAI 兼容 `/chat/completions`。国内外绝大多数厂商
  （智谱 / DeepSeek / OpenAI / Moonshot / 通义 …）与各类网关均走该格式，**默认通道**。
- `anthropic` —— Anthropic **原生** `/v1/messages`。system 外提、max_tokens 必填、
  块级 SSE、原生缓存 token 字段、`output_config.effort` 档位，兼容层拿不到这些。
- `ollama` —— Ollama **原生** `/api/chat`（本地部署首选）。原生协议才有明确的
  `think` 一等参数与 `message.thinking` 思维链字段，且返回 token 计数与分段耗时；
  OpenAI 兼容层 `/v1` 在这几点上都有坑，详见 `ollama.py` 模块文档。
- `gemini` —— Gemini **原生** `generateContent`。角色只有 user/model、内容一律
  `parts[]`、system 走 `systemInstruction`、思考参数 3 系列 / 2.5 系列两套并存、
  鉴权用 `x-goog-api-key`，详见 `gemini.py` 模块文档。

实现件（方言 Profile、回传拆分器、线格式翻译、文本工具降级、能力矩阵）一律以 `_` 前缀
私有（`_profiles` / `_profiles_data` / `_telemetry` / `_multimodal` / `_tooltext` /
`_capability` / `_anthropic_wire` / `_gemini_wire`）：它们可被随时重排，
调用方请只依赖 `palm_llm`（等价于 `palm_llm.api`）。
"""
from ._capability import CapabilityError, capabilities_for, check_capabilities
from ._telemetry import Meter, TurnStats
from .anthropic import AnthropicProvider
from .base import BaseProvider
from .gemini import GEMINI_DEFAULT_BASE_URL, GeminiProvider
from .ollama import OLLAMA_DEFAULT_BASE_URL, OllamaProvider
from .openai_compat import OpenAICompatProvider

# 协议键 → provider 类。`palm_llm.api.protocols()` 与工厂共用这一份 —— 分头维护两张
# 映射必然漂移，而漂移的表现是"某个协议悄悄回落到了 openai_compat"，最难发现。
# 别名（ollama_native / google）与官方 SDK 的习惯叫法一致，便于调用方直接照抄。
PROTOCOLS = {
    "openai_compat": OpenAICompatProvider,
    "anthropic": AnthropicProvider,      # 原生 /v1/messages
    "ollama": OllamaProvider,            # 原生 /api/chat
    "ollama_native": OllamaProvider,     # 别名：与 openai_compat 打 /v1 区分
    "gemini": GeminiProvider,            # 原生 /v1beta/models/{m}:generateContent
    "google": GeminiProvider,            # 别名：与官方 SDK 的习惯叫法一致
}

DEFAULT_PROTOCOL = "openai_compat"

__all__ = [
    "PROTOCOLS",
    "DEFAULT_PROTOCOL",
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
]


def get_provider_instance(cfg) -> BaseProvider:
    """按 cfg.type 取 provider；未知 type 一律回落 openai_compat（容错，非静默失败）。"""
    return PROTOCOLS.get(cfg.type, PROTOCOLS[DEFAULT_PROTOCOL])(cfg)

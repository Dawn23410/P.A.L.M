"""模型 Provider 抽象层。"""
from .base import BaseProvider
from .anthropic import AnthropicProvider
from .gemini import GeminiProvider
from .mock import MockProvider
from .openai_compat import OpenAICompatProvider

__all__ = ["BaseProvider", "get_provider_instance"]


def get_provider_instance(cfg) -> BaseProvider:
    mapping = {
        "openai_compat": OpenAICompatProvider,
        "anthropic": AnthropicProvider,
        "gemini": GeminiProvider,
        "mock": MockProvider,
    }
    cls = mapping.get(cfg.type, OpenAICompatProvider)
    return cls(cfg)

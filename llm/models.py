"""LLM 内核数据模型：ProviderConfig / Message / ModelParameters。

职责：在 providers 与调用方之间定义稳定的数据结构。所有 provider
（openai_compat / anthropic / gemini / mock）均依赖本模块，故它是 llm
包可导入的前置条件。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ProviderConfig:
    """单个模型提供方的连接配置。"""
    name: str                                   # 逻辑名（如 "nonelinear" / "openai"）
    type: str = "openai_compat"                 # 对应 provider 实现键
    base_url: str = ""                          # API base（openai_compat 用）
    api_key: str = ""                           # 凭证（切勿入库；从 .env / 密钥文件加载）
    default_model: str = ""                     # 该 provider 的默认模型名
    extra: dict = field(default_factory=dict)   # 透传（如 organization / project）


@dataclass
class Message:
    """一条对话消息。"""
    role: str                       # "system" | "user" | "assistant"
    content: str = ""
    images: Optional[list[str]] = None   # 多模态：data URI 或 http(s) URL 列表


@dataclass
class ModelParameters:
    """生成参数。字段与 OpenAI / Anthropic / Gemini 公共子集对齐。"""
    temperature: float = 0.7
    top_p: float = 1.0
    max_tokens: int = 1024
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    extra_body: Optional[dict] = None     # 透传（如 {"enable_thinking": False}）

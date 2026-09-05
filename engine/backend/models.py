"""Pydantic 数据模型定义。"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class Message(BaseModel):
    role: str = Field(..., description="system / user / assistant")
    content: str = ""
    images: Optional[List[str]] = Field(default=None, description="图片 URL 列表（多模态）")
    reasoning: Optional[str] = Field(default=None, description="思维链（深度思考模型的 reasoning_content）")
    ts: Optional[float] = None


class ModelParameters(BaseModel):
    temperature: float = 0.7
    top_p: float = 1.0
    max_tokens: int = 8192
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    # 透传给 API 的额外参数（如关闭思考：{"enable_thinking": False}），
    # 用于在不改代码的情况下微调首字延迟。
    extra_body: Optional[dict] = None


class ProviderConfig(BaseModel):
    id: str
    name: str
    type: str = Field(..., description="openai_compat / anthropic / gemini")
    base_url: str = ""
    api_key: str = ""
    models: List[str] = Field(default_factory=list)


class Preset(BaseModel):
    name: str
    prompt: str


class AppConfig(BaseModel):
    providers: List[ProviderConfig] = Field(default_factory=list)
    active_provider: str = ""
    active_model: str = ""
    system_prompt: str = "你是一个有帮助的AI助手。"
    parameters: ModelParameters = Field(default_factory=ModelParameters)
    presets: List[Preset] = Field(default_factory=list)


class Conversation(BaseModel):
    id: str
    title: str = "新对话"
    created_at: float = 0.0
    updated_at: float = 0.0
    messages: List[Message] = Field(default_factory=list)


class ChatRequest(BaseModel):
    conversation_id: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    system_prompt: Optional[str] = None
    parameters: Optional[ModelParameters] = None
    content: str = ""                         # 最新用户消息文本
    images: Optional[List[str]] = None        # 最新用户消息图片 URL（可含 /uploads/ 本地路径）

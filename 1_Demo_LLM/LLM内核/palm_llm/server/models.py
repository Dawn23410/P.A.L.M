"""Pydantic 数据模型定义。"""
from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field

from palm_llm.models import Message as _KernelMessage, ModelParameters as _KernelParams, ProviderConfig as _KernelProviderConfig


class Message(BaseModel):
    role: str = Field(..., description="system / user / assistant / tool")
    content: str = ""
    images: Optional[List[str]] = Field(default=None, description="图片 URL 列表（多模态）")
    files: Optional[List[Any]] = Field(
        default=None,
        description="文档附件（PDF/txt…）：data URI 字符串，或 "
                    '{"data","mime","name","size"} 字典；能否发送由能力矩阵前置拦截判定',
    )
    reasoning: Optional[str] = Field(default=None, description="思维链（深度思考模型的 reasoning_content）")
    reasoning_echo: Optional[str] = Field(
        default=None,
        description="原生思考块的回传凭据（不透明，由 Anthropic 通道产出并原样带回；勿解析）",
    )
    ts: Optional[float] = None
    # ── 原生 Tool Calling（OpenAI 格式）──
    tool_calls: Optional[List[dict]] = Field(default=None, description="assistant 的工具调用（OpenAI 原生结构）")
    tool_call_id: Optional[str] = Field(default=None, description='role="tool" 时对应的 tool_call id')
    name: Optional[str] = Field(default=None, description='role="tool" 时的工具名')
    tool_error: bool = Field(default=False, description="工具执行失败（→ Anthropic tool_result.is_error）")

    def to_kernel(self) -> _KernelMessage:
        """转为内核 Message（`ts` 为纯应用层字段，不进内核）。

        `reasoning` / `reasoning_echo` 必须带进内核：多轮把上一轮思考原样回传是部分
        供应商的硬契约（DeepSeek 带 tools 时、Kimi K3 无条件），丢了就 400。
        """
        return _KernelMessage(role=self.role, content=self.content, images=self.images,
                              files=self.files,
                              tool_calls=self.tool_calls, tool_call_id=self.tool_call_id,
                              name=self.name, tool_error=self.tool_error,
                              reasoning=self.reasoning, reasoning_echo=self.reasoning_echo)


class ModelParameters(BaseModel):
    temperature: float = 0.7
    top_p: float = 1.0
    max_tokens: int = 8192
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    # 透传给 API 的额外参数（如关闭思考：{"enable_thinking": False}），
    # 用于在不改代码的情况下微调首字延迟。
    extra_body: Optional[dict] = None
    # ── 原生 Tool Calling ──
    # tools：OpenAI 原生工具声明数组（[{"type":"function","function":{...}}]），
    # 不另造 DSL，与 OpenAI 规范逐字一致，便于直接复用各厂商文档。
    tools: Optional[List[dict]] = None
    tool_choice: Optional[Any] = Field(default=None, description='"auto"|"none"|"required"|{"type":"function",...}')
    parallel_tool_calls: Optional[bool] = Field(
        default=None, description="是否允许并行工具调用（None=不下发，由各家默认决定）")

    def to_kernel(self) -> _KernelParams:
        """转为内核 ModelParameters（字段同构，显式转换防漂移）。"""
        return _KernelParams(
            temperature=self.temperature,
            top_p=self.top_p,
            max_tokens=self.max_tokens,
            frequency_penalty=self.frequency_penalty,
            presence_penalty=self.presence_penalty,
            extra_body=self.extra_body,
            tools=self.tools,
            tool_choice=self.tool_choice,
            parallel_tool_calls=self.parallel_tool_calls,
        )


class ProviderConfig(BaseModel):
    id: str
    name: str
    type: str = Field(
        default="openai_compat",
        description='协议实现键：openai_compat（OpenAI 兼容 /chat/completions）'
                    ' | anthropic（Anthropic 原生 /v1/messages，base_url 填站点根地址）'
                    ' | ollama（Ollama 原生 /api/chat，base_url 填原生根地址，不带 /v1）',
    )
    base_url: str = ""
    api_key: str = ""
    models: List[str] = Field(default_factory=list)

    def to_kernel(self) -> _KernelProviderConfig:
        """转为内核 dataclass，消除对内核字段的隐式 duck-type 依赖。"""
        return _KernelProviderConfig(
            name=self.name or self.id,
            type=self.type,
            base_url=self.base_url,
            api_key=self.api_key,
            default_model=(self.models[0] if self.models else ""),
            extra={},
        )


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
    files: Optional[List[Any]] = None         # 最新用户消息文档附件（同上；由能力矩阵前置拦截判定）
    # 请求级端点/KEY：每次 API 传输可携带，优先级高于 config.json，不落盘。
    # 都未携带时回落到 config.json 的 provider 配置。
    provider_type: Optional[str] = Field(default=None, description="请求级 provider 类型（默认 openai_compat）")
    base_url: Optional[str] = Field(default=None, description="请求级端点覆盖")
    api_key: Optional[str] = Field(default=None, description="请求级 KEY 覆盖")

"""LLM 内核数据模型：ProviderConfig / Message / ModelParameters / Tool。

职责：在 providers 与调用方之间定义稳定的数据结构。
（协议由 `ProviderConfig.type` 决定：openai_compat / anthropic / ollama / gemini。）"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ProviderConfig:
    """单个模型提供方的连接配置。"""
    name: str                                   # 逻辑名（如 "nonelinear" / "openai"）
    type: str = "openai_compat"                 # provider 实现键（见 providers/__init__.py 工厂）
    base_url: str = ""                          # API base
    api_key: str = ""                           # 凭证（切勿入库；从 .env / 密钥文件加载）
    default_model: str = ""                     # 该 provider 的默认模型名
    extra: dict = field(default_factory=dict)   # 透传（如 organization / project）
    # 重试策略（palm_llm.retry.RetryPolicy）。None = 用 DEFAULT（低延迟档：最多重试 1 次、
    # 不退避）。企业部署可传 STABLE（3 次 + 指数退避 + 抖动）。见 retry.py 取舍说明。
    # 字符串注解，避免 models 反向依赖 retry。
    retry: Optional["RetryPolicy"] = None


@dataclass
class Message:
    """一条对话消息（OpenAI 对话格式）。

    除常规 system/user/assistant 外，原生 Tool Calling 需要两种形态：
      - assistant 消息携带 `tool_calls`（模型要求调用工具）
      - role="tool" 消息携带 `tool_call_id`（工具执行结果回填）
    """
    role: str                                  # system | user | assistant | tool
    content: str = ""
    images: Optional[list[str]] = None         # 多模态：data URI 或 http(s) URL 列表
    # 文档附件（PDF / txt / docx …）。元素有两种形态，与 images 保持一致：
    #   - str：data URI（`data:application/pdf;base64,...`）或 http(s) URL
    #   - dict：{"data": <base64 或 data URI>, "mime": "application/pdf",
    #            "name": "a.pdf", "size": <原始字节数，可选>}
    # `size` 缺省时由内核按 base64 长度反推（近似），供能力矩阵的大小闸门使用。
    files: Optional[list] = None
    # ── Tool Calling 扩展 ──
    tool_calls: Optional[list[dict]] = None    # assistant 消息的工具调用（OpenAI 原生结构）
    tool_call_id: Optional[str] = None         # role="tool" 时，对应 assistant tool_call 的 id
    name: Optional[str] = None                 # role="tool" 时的工具名（可选）
    # role="tool" 且工具执行失败时置真 → Anthropic 的 `tool_result.is_error`。
    # OpenAI 系无对应字段（约定把错误文本写进 content），故只对 Anthropic 生效。
    tool_error: bool = False
    # ── 思考块回传（跨通道契约，非可选装饰）──
    # 部分供应商要求多轮把上一轮的思考原样送回，否则 400（DeepSeek 带 tools 时、Kimi K3 无条件）。
    # `reasoning` 为纯文本（OpenAI 系的 reasoning_content 口径）；
    # `reasoning_echo` 存原生格式的不透明凭据（Anthropic 的 thinking 块含签名），**勿解析**。
    reasoning: Optional[str] = None
    reasoning_echo: Optional[str] = None

    def to_openai(self) -> dict:
        """转为 OpenAI /chat/completions 的 message 结构。"""
        if self.role == "system":
            return {"role": "system", "content": self.content}
        # 工具结果回填
        if self.role == "tool":
            out: dict[str, Any] = {"role": "tool", "content": self.content}
            if self.tool_call_id:
                out["tool_call_id"] = self.tool_call_id
            if self.name:
                out["name"] = self.name
            return out
        if self.images or self.files:
            # 多模态：统一走 providers.multimodal（兼容 str URL 与 {"data","mime"} 字典）。
            # 仅在正文非空时加 text block —— 纯附件消息不塞空文本块（部分网关视为空消息）。
            from .providers.multimodal import content_blocks  # 延迟导入，避免与 providers 循环

            blocks = content_blocks(self.content or "", self.images, files=self.files)
            if not self.content:
                blocks = [b for b in blocks if b.get("type") != "text"]
            out = {"role": self.role, "content": blocks}
        else:
            out = {"role": self.role, "content": self.content}
        # assistant 携带工具调用（content 可能为 None，必须显式带上）
        if self.tool_calls:
            out["tool_calls"] = self.tool_calls
        return out


@dataclass
class Tool:
    """OpenAI 格式的函数工具声明（原生 Tool / Function Calling）。

    两种构造方式：
      1) 结构化：Tool(name=..., description=..., parameters={...JSON Schema...})
      2) 原样透传：Tool(raw={"type": "function", "function": {...}})

    `to_openai()` 始终输出 OpenAI 规范的
    {"type": "function", "function": {"name", "description", "parameters"}}。
    """
    name: str = ""
    description: str = ""
    parameters: dict = field(default_factory=dict)   # JSON Schema（可为 {}）
    raw: Optional[dict] = None                       # 已按 OpenAI 结构组装时直接透传
    # OpenAI 结构化函数调用：强制参数严格符合 JSON Schema（不支持的端点会忽略/报错，
    # 故默认 None = 不下发；Anthropic 无对应能力，见 anthropic_wire.native_tools）
    strict: Optional[bool] = None

    def to_openai(self) -> dict:
        if self.raw:
            return self.raw
        fn: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters or {"type": "object", "properties": {}},
        }
        if self.strict is not None:
            fn["strict"] = self.strict
        return {"type": "function", "function": fn}

    @staticmethod
    def normalize(tools: Optional[list]) -> Optional[list[dict]]:
        """把 list[Tool] / list[dict] 统一成 OpenAI payload 的 tools 数组。"""
        if not tools:
            return None
        out = []
        for t in tools:
            if isinstance(t, Tool):
                out.append(t.to_openai())
            elif isinstance(t, dict):
                # 允许 {"type":"function","function":{...}} 或裸 function 定义
                out.append(t if "function" in t else
                           {"type": "function", "function": t})
            elif hasattr(t, "to_openai"):
                out.append(t.to_openai())
        return out or None


@dataclass
class ModelParameters:
    """生成参数（OpenAI 兼容格式）。"""
    temperature: float = 0.7
    top_p: float = 1.0
    # 默认 8192：GLM 系思考链可吃掉数千 token，默认值过小会导致 content 被耗尽为空
    # （实测 max_tokens=1024 时 reasoning_tokens=1021、content=0）。
    max_tokens: int = 8192
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    extra_body: Optional[dict] = None     # 透传（如 {"enable_thinking": False}）
    # ── 原生 Tool Calling ──
    tools: Optional[list] = None          # list[Tool] 或 OpenAI 原生 list[dict]
    tool_choice: Optional[Any] = None     # "auto" | "none" | "required" | {"type":"function",...}
    # 是否允许一次返回多个工具调用。None = 不下发（各家默认不同，不代调用方做决定）。
    # OpenAI 系写 `parallel_tool_calls`；Anthropic 无同名参数，False 映射为
    # tool_choice.disable_parallel_tool_use（见 anthropic_wire.native_tool_choice）。
    parallel_tool_calls: Optional[bool] = None

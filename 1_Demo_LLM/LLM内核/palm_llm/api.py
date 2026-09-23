"""palm_llm 对外**函数库** —— 调用方唯一需要 import 的入口。

数据契约（dataclass，定义在 `models.py`）
----------------------------------------
    ProviderConfig   连接配置（name / type / base_url / api_key / default_model / retry）
    Message          一条对话消息（含 images / files / tool_calls / reasoning_echo）
    ModelParameters  生成参数（采样 + tools / tool_choice / parallel_tool_calls）
    Tool             工具声明（结构化或原样透传）
    TurnStats        回传统一字段（token / 计时 / 派生指标），见 `providers/_telemetry.py`

函数库（本模块）
----------------
    连接   get_provider_instance(cfg)          配置 → provider 实例
           protocols()                        支持的协议键 → provider 类名
    调用   stream(messages, ...)               异步流式（增量事件）
           complete(messages, ...)             一次性（把增量拼成整段后返回）
    能力   capabilities_for(base_url, model, ...)  端点+模型的能力矩阵
           check_capabilities(messages, profile, ...)  发请求前的硬拦（违规抛 CapabilityError）
    失败   classify_error(...)                 失败信号 → 类型化错误（供据错决策）
    可观测 configure_logging / log_event / request_id / set_request_id
    自述   describe()                          本内核的版本 / 协议 / 函数清单

为什么要有这一层
----------------
`providers/_*.py` 一律以下划线私有：它们是可以随时重排的实现件（方言 Profile、回传
拆分器、线格式翻译、文本工具降级…）。调用方只从 `palm_llm`（或等价的 `palm_llm.api`）
取件，内部改动才不会变成对外破坏性变更。

与 `引用` 的关系：`palm_llm/__init__.py` 只做"转出 + 惰性挂载 server 子包"，
真正的函数清单与文档在本模块 —— 单一事实来源。
"""
from __future__ import annotations

from typing import AsyncIterator, Optional

from .errors import (
    AuthError,
    BadRequestError,
    CapabilityError,
    NotConfiguredError,
    PalmLLMError,
    RateLimitError,
    StreamInterruptedError,
    TransportError,
    UpstreamServerError,
    classify_error,
)
from .models import Message, ModelParameters, ProviderConfig, Tool
from .obs import configure_logging, log_event, request_id, set_request_id
from .providers import (
    GEMINI_DEFAULT_BASE_URL,
    OLLAMA_DEFAULT_BASE_URL,
    AnthropicProvider,
    BaseProvider,
    GeminiProvider,
    OllamaProvider,
    OpenAICompatProvider,
    PROTOCOLS,
    capabilities_for,
    check_capabilities,
    get_provider_instance,
)
from .providers._telemetry import TurnStats
from .retry import LOW_LATENCY, STABLE, RetryPolicy

VERSION = "0.7.0"


# ─────────────────────────── 连接 ───────────────────────────
def protocols() -> dict:
    """支持的协议键 → provider 类名（含别名）。

    `cfg.type` 命中这里才走特化通道；未命中一律回落 `openai_compat`（容错而非静默失败）。
    """
    return {k: cls.__name__ for k, cls in PROTOCOLS.items()}


# ─────────────────────────── 调用 ───────────────────────────
def _instance(cfg: Optional[ProviderConfig], prov: Optional[BaseProvider]) -> BaseProvider:
    """取 provider 实例：给实例就用实例，否则用配置建一个。"""
    if prov is not None:
        return prov
    if cfg is None:
        raise NotConfiguredError(
            "需要给 cfg（ProviderConfig）或 prov（已有的 provider 实例）之一。")
    return get_provider_instance(cfg)


def _model_of(prov: BaseProvider, model: str) -> str:
    return model or prov.cfg.default_model


async def stream(messages: list[Message], params: Optional[ModelParameters] = None, *,
                 model: str = "", cfg: Optional[ProviderConfig] = None,
                 prov: Optional[BaseProvider] = None) -> AsyncIterator[dict]:
    """异步流式调用：产出内核增量事件。

    事件形态（详见 `BaseProvider.complete`）：
        {"content": 增量} / {"reasoning": 增量} / {"tool_call_delta": {...}}
        / {"tool_calls": [...]} / {"done": True, "usage": {...}, "stats": {...}}
    本函数只是把"取实例 → 选模型 → 调用"三步收成一次调用；不做任何额外包装，
    以免破坏各 provider 的**单生成器**约束（见 `providers/ollama.py` 模块文档）。
    """
    instance = _instance(cfg, prov)
    async for ev in instance.complete(
            messages, params or ModelParameters(), _model_of(instance, model), stream=True):
        yield ev


async def complete(messages: list[Message], params: Optional[ModelParameters] = None, *,
                   model: str = "", cfg: Optional[ProviderConfig] = None,
                   prov: Optional[BaseProvider] = None) -> dict:
    """一次性调用：内部仍走流式，把增量拼成整段后返回（省去调用方自己聚合）。

    返回：
        {"content", "reasoning", "tool_calls", "usage", "stats", "finish_reason"}
      - `tool_calls` 为 None 表示本轮没有工具调用；
      - `usage` 保厂商原样，`stats` 是跨协议归一的统一字段（**新代码只读 stats**）。

    ⚠️ 与直接迭代 `stream()` 的差别仅在于"谁来拼接"；需要首字延迟/中途展示的场景
    请用 `stream()`，一次性封装会等到整段结束才返回。
    """
    content: list[str] = []
    reasoning: list[str] = []
    tool_calls: Optional[list] = None
    usage: dict = {}
    stats: dict = {}
    async for ev in stream(messages, params, model=model, cfg=cfg, prov=prov):
        if "content" in ev:
            content.append(ev["content"])
        elif "reasoning" in ev:
            reasoning.append(ev["reasoning"])
        elif "tool_calls" in ev:
            tool_calls = ev["tool_calls"]
        elif ev.get("done"):
            usage = ev.get("usage") or {}
            stats = ev.get("stats") or {}
    return {
        "content": "".join(content),
        "reasoning": "".join(reasoning),
        "tool_calls": tool_calls,
        "usage": usage,
        "stats": stats,
        "finish_reason": (stats or {}).get("finish_reason", ""),
    }


# ─────────────────────────── 自述 ───────────────────────────
def describe() -> dict:
    """本内核的版本 / 协议 / 公开函数 / 数据契约清单（供自检、文档与 UI 生成）。"""
    return {
        "name": "palm_llm",
        "version": VERSION,
        "protocols": protocols(),
        "functions": [
            "get_provider_instance", "protocols",
            "stream", "complete",
            "capabilities_for", "check_capabilities",
            "classify_error",
            "configure_logging", "log_event", "request_id", "set_request_id",
            "describe",
        ],
        "data_types": ["ProviderConfig", "Message", "ModelParameters", "Tool", "TurnStats"],
        "providers": ["OpenAICompatProvider", "AnthropicProvider",
                      "OllamaProvider", "GeminiProvider"],
    }


__all__ = [
    # ── 版本与自述 ──
    "VERSION", "describe", "protocols",
    # ── 数据契约 ──
    "ProviderConfig", "Message", "ModelParameters", "Tool", "TurnStats",
    # ── provider 层 ──
    "BaseProvider", "OpenAICompatProvider", "AnthropicProvider", "OllamaProvider",
    "GeminiProvider", "get_provider_instance",
    "OLLAMA_DEFAULT_BASE_URL", "GEMINI_DEFAULT_BASE_URL",
    # ── 调用 ──
    "stream", "complete",
    # ── 能力 ──
    "capabilities_for", "check_capabilities", "CapabilityError",
    # ── 失败分类 ──
    "classify_error",
    "PalmLLMError", "TransportError", "UpstreamServerError", "RateLimitError",
    "AuthError", "BadRequestError", "NotConfiguredError", "StreamInterruptedError",
    # ── 重试策略（同一旋钮的两端）──
    "RetryPolicy", "LOW_LATENCY", "STABLE",
    # ── 可观测 ──
    "configure_logging", "log_event", "request_id", "set_request_id",
]

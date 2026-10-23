"""LLM 流式调用桥：经 models 砖 capabilities["create_stream"] 流式调用 LLM。

集中放在独立模块，供 brick.py（原生 function calling 路径）复用，保证编排层真实
Token 计量口径一致。

边流式产出增量字典（{content}/{reasoning}/{tool_calls}），边通过 usage_container
收集真实 Token 用量。tools 非空时走原生 function calling，tool_calls 按 index
累积成完整列表随增量产出。
"""
from __future__ import annotations

import logging
from typing import AsyncIterator

from palm._core.schemas.chat import ChatMessage, ProviderRef
from palm._core.token_estimate import estimate_tokens

_LOGGER = logging.getLogger(__name__)


def _resolve_provider_ref(provider: object) -> ProviderRef | None:
    """把 dict / ProviderRef 形式的供应商参数统一为 ProviderRef 对象。"""
    if provider and isinstance(provider, dict):
        return ProviderRef(**provider)
    if isinstance(provider, ProviderRef):
        return provider
    return None


def _convert_to_chat_messages(messages: list) -> list[ChatMessage]:
    """把 dict 消息转为 ChatMessage 对象，保留 tool_calls / tool_call_id 供原生续调用。"""
    chat_messages: list[ChatMessage] = []
    for m in messages:
        if isinstance(m, dict):
            chat_messages.append(ChatMessage(
                role=m.get("role", "user"),
                content=m.get("content", ""),
                tool_calls=m.get("tool_calls"),
                tool_call_id=m.get("tool_call_id"),
                name=m.get("name"),
                reasoning=m.get("reasoning", "") or m.get("reasoning_content", "") or "",
                images=m.get("images"),
            ))
        else:
            chat_messages.append(m)
    return chat_messages


def _normalize_chunk(chunk) -> tuple[str, str, object, object]:
    """把上游 chunk 统一为 (正文, 推理链, 原始 tool_calls, usage) 四元组。"""
    if isinstance(chunk, dict):
        return (
            chunk.get("content") or chunk.get("delta") or "",
            chunk.get("reasoning") or "",
            chunk.get("tool_calls"),
            chunk.get("usage"),
        )
    if isinstance(chunk, str):
        return chunk, "", None, None
    return (
        getattr(chunk, "content", None) or getattr(chunk, "delta", "") or "",
        getattr(chunk, "reasoning", None) or "",
        getattr(chunk, "tool_calls", None),
        getattr(chunk, "usage", None),
    )


def _merge_tool_calls(raw_tc: list[dict], acc: list[dict]) -> None:
    """按 index 把分段传入的 tool_calls 合并成完整列表（OpenAI 协议 arguments 分段）。"""
    for tc in raw_tc:
        idx = tc.get("index", 0)
        while len(acc) <= idx:
            acc.append({"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
        cur = acc[idx]
        if tc.get("id"):
            cur["id"] = tc["id"]
        if tc.get("type"):
            cur["type"] = tc["type"]
        fn = tc.get("function") or {}
        if fn.get("name"):
            cur["function"]["name"] = fn["name"]
        if fn.get("arguments"):
            cur["function"]["arguments"] += fn["arguments"]


def _collect_chunk_usage(usage: object, merged_usage: dict) -> None:
    """累加单块返回的真实 Token 用量（每轮调用累加，不用估算覆盖）。"""
    if not usage:
        return
    for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
        v = usage.get(k) if isinstance(usage, dict) else None
        if v is not None:
            merged_usage.setdefault(k, 0)
            merged_usage[k] += int(v)


def _finalize_usage_container(
    usage_container: dict | None, messages: list, collected: str, merged_usage: dict,
) -> None:
    """循环结束后回写用量到容器；真实用量缺失时标记估算（不混入真实累计）。

    估算值不累加进容器：避免混合场景（部分轮真实/部分轮估算）用估算污染真实
    台账累计；纯估算请求由 done 侧据 total<=0 判断不落账（用户要求不显示 mock 用量）。
    """
    if usage_container is None:
        return
    prompt = int(merged_usage.get("prompt_tokens") or 0)
    completion = int(merged_usage.get("completion_tokens") or 0)
    total = int(merged_usage.get("total_tokens") or 0)
    if total <= 0:
        usage_container["is_estimate"] = True
        return
    # 累加不覆盖（ReAct 循环多次调用需累加）
    usage_container["prompt_tokens"] = usage_container.get("prompt_tokens", 0) + prompt
    usage_container["completion_tokens"] = usage_container.get("completion_tokens", 0) + completion
    usage_container["total_tokens"] = usage_container.get("total_tokens", 0) + total


async def stream_llm(
    messages: list[dict],
    model: str,
    provider: object = None,
    usage_container: dict | None = None,
    tools: list | None = None,
) -> AsyncIterator[dict]:
    """经 models 砖 capabilities["create_stream"] 调用 LLM。

    边流式产出增量字典（{content}/{reasoning}/{tool_calls}），边通过 usage_container
    收集真实 Token 用量。tools 非空时走原生 function calling，tool_calls 按 index
    累积成完整列表随增量产出。
    """
    from palm._core.container import registry
    models_brick = container.get("models")
    if not models_brick:
        raise RuntimeError("models 砖未启用")
    stream_fn = (getattr(models_brick, "capabilities", {}) or {}).get("create_stream")
    if not stream_fn:
        raise RuntimeError("models 砖未暴露 create_stream 能力")

    provider_ref = _resolve_provider_ref(provider)
    chat_messages = _convert_to_chat_messages(messages)
    collected = ""
    merged_usage: dict = {}
    # 流式 tool_calls 按 index 合并（OpenAI 协议 arguments 分段传入）
    tool_calls_acc: list[dict] = []

    try:
        async for chunk in stream_fn(chat_messages, model=model, provider=provider_ref, tools=tools):
            if chunk is None:
                continue
            content, reasoning, raw_tc, usage = _normalize_chunk(chunk)
            _collect_chunk_usage(usage, merged_usage)
            # 原生工具调用：累积并随增量产出完整快照
            if raw_tc:
                _merge_tool_calls(raw_tc, tool_calls_acc)
                yield {"tool_calls": list(tool_calls_acc)}
            # 正文增量进入解析文本；推理链(reasoning)单独透传，供前端实时显示思考链
            if content:
                collected += content
                yield {"content": content}
            if reasoning:
                yield {"reasoning": reasoning}
    except Exception as exc:
        _LOGGER.error("LLM 流式调用异常: %s", exc)
        raise
    finally:
        # 本地模型不返回 usage 时按中英文感知估算，计入容器（供台账统计）。
        _finalize_usage_container(usage_container, messages, collected, merged_usage)
"""Chat providers.

- MockProvider: local echo so the UI runs fully offline without credentials.
- OpenAIProvider: stream from a real OpenAI-compatible endpoint when the user
  adds a model in Settings.
- AnthropicProvider: stream from Anthropic's native Messages API (Claude).

Real providers are selected at request time via ``stream_chat(..., provider=...)``,
with the protocol decided by ``provider.mode`` (openai | anthropic). ``MockProvider``
stays the default and the brick router is untouched.

联网统一经 palm_sdk.net 门面（网卡砖唯一执行器）；本砖不持有 httpx/requests/socket。
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator

from palm_sdk.net import arequest


@dataclass
class ChatDelta:
    """单个流式分片：正文内容与推理（思维链）内容可分开发送。"""

    content: str = ""
    reasoning: str = ""
    # 原生工具调用（OpenAI/DeepSeek 的 tool_calls 格式），跨轮续调用。
    tool_calls: list[dict] | None = None
    # 用量统计（部分事件携带，如 OpenAI 流式结束时的 usage / Anthropic 的 message_delta）。
    usage: dict | None = None


class BaseProvider(ABC):
    name = "base"

    @abstractmethod
    def stream(self, messages, note: str = "") -> AsyncIterator[ChatDelta]:
        """逐个产出 ChatDelta：content 为正文增量，reasoning 为思维链增量。"""
        ...


def _content_with_images(text: str, images: list[dict], mode: str):
    """纯文本 + 图像 → 多模态 content blocks（供视觉模型分析截图）。"""
    blocks = [{"type": "text", "text": text or ""}]
    for img in images:
        data = img.get("data", "")
        mime = img.get("mime", "image/png")
        if mode == "anthropic":
            blocks.append({"type": "image", "source": {"type": "base64", "media_type": mime, "data": data}})
        else:
            blocks.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}})
    return blocks


def _to_oai_messages(messages, mode: str = "openai") -> list[dict]:
    """把 ChatMessage 列表转成 OpenAI 格式，保留原生工具调用所需的 tool_calls / tool 角色。

    原生模式下 assistant 消息携带 tool_calls、工具结果以 role=tool 回灌，
    二者都必须原样保留，模型才能跨轮续调用同一组工具。

    多模态：user/system 消息携带 images 时，content 转为 content blocks 列表
    （OpenAI 用 image_url，Anthropic 用 image source）。tool/assistant 消息
    不支持图像，保持纯文本——截图经独立 user 消息注入（见 execution 层）。
    """
    out = []
    for m in messages:
        images = getattr(m, "images", None) or []
        if m.role == "tool":
            out.append({
                "role": "tool",
                "content": m.content or "",
                "tool_call_id": m.tool_call_id or "",
            })
        elif m.role == "assistant":
            msg: dict = {"role": "assistant", "content": m.content or ""}
            if m.tool_calls:
                msg["tool_calls"] = m.tool_calls
                # thinking 模型（如 Kimi）续轮要求 assistant 的 tool_call 消息带
                # reasoning_content 字段；部分网关把空串也视为缺失，故给非空占位。
                msg["reasoning_content"] = m.reasoning or "tool_call"
            out.append(msg)
        elif m.role in ("system", "user"):
            content = _content_with_images(m.content, images, mode) if images else (m.content or "")
            out.append({"role": m.role, "content": content})
    return out


class MockProvider(BaseProvider):
    """Echo-style provider so the UI is fully usable without an API key."""

    name = "mock"

    async def stream(self, messages, note: str = "") -> AsyncIterator[ChatDelta]:
        last = messages[-1].content if messages else ""
        reply = f"[mock] 你说了：{last}\n"
        if note:
            reply += f"\n收到附件：{note}\n"
        reply += (
            "\n这是后端本地回显（mock）。当在「设置 › 模型」里添加并选择自定义供应商后，"
            "后端会代理到真实端点返回模型回复，前后端完全解耦。"
        )
        for token in reply:
            yield ChatDelta(content=token)
            await asyncio.sleep(0.01)
        # 估算本地用量，使「用量明细」在离线（mock）模式下也有记录可看：
        # 按字符粗估（输入 /2、输出 /4），仅用于本地演示，不计入真实配额语义。
        prompt_chars = sum(len(getattr(m, "content", "") or "") for m in messages)
        completion_chars = len(reply)
        prompt_tokens = max(1, round(prompt_chars / 2))
        completion_tokens = max(1, round(completion_chars / 4))
        yield ChatDelta(
            usage={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            }
        )


class OpenAIProvider(BaseProvider):
    """OpenAI-compatible Chat Completions (OpenAI / DeepSeek / Qwen / Ollama ...)."""

    name = "openai"

    def __init__(self, base_url: str, api_key: str, model: str, temperature=None, max_tokens=None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    async def stream(self, messages, note: str = "", tools: list | None = None,
                     thinking: dict | None = None) -> AsyncIterator[ChatDelta]:
        payload = {
            "model": self.model,
            "messages": _to_oai_messages(messages),
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        if self.max_tokens is not None:
            payload["max_tokens"] = self.max_tokens
        if tools is not None:
            payload["tools"] = tools
        if thinking is not None:
            payload["thinking"] = thinking
        # DeepSeek V4 系列默认开启内部推理链，导致 TTFT 飙升（Pro 5.9s→1.5s, Flash 2.1s→1.2s）。
        # 主动关闭推理：仅 DeepSeek 模型生效，其他 OpenAI 兼容端点不受影响。
        if "deepseek" in self.model.lower():
            payload["enable_thinking"] = False
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        # 经网卡门面转发（异步 SSE 流式）；默认拒绝外网，未授权主机由网卡拦截。
        resp = await arequest(
            "POST", f"{self.base_url}/chat/completions",
            json=payload, headers=headers, stream=True, timeout=600.0,
        )
        if resp.status_code != 200:
            text = await resp.aread()
            raise RuntimeError(f"provider {resp.status_code}: {text[:400]}")
        async for line in resp.aiter_lines():
            if not line.startswith("data:"):
                continue
            sse_payload = line[5:].strip()
            if sse_payload == "[DONE]":
                break
            try:
                event = json.loads(sse_payload)
            except json.JSONDecodeError:
                continue
            choices = event.get("choices") or [{}]
            delta = choices[0].get("delta", {}) or {}
            content = delta.get("content")
            # 推理（思维链）字段多源兼容：DeepSeek/Qwen/Kimi 用 reasoning_content；
            # 部分 OpenAI 兼容端点用 reasoning；Ollama 经 OpenAI 兼容协议返回 thinking。
            reasoning = (
                delta.get("reasoning_content")
                or delta.get("reasoning")
                or delta.get("thinking")
            )
            # 原生工具调用 tool_calls（OpenAI/DeepSeek 流式协议，arguments 是分段传入的）
            tc_delta = delta.get("tool_calls")
            if content:
                yield ChatDelta(content=content)
            if reasoning:
                yield ChatDelta(reasoning=reasoning)
            if tc_delta:
                yield ChatDelta(tool_calls=tc_delta)
            # 用量统计：流式结束时随 usage 事件返回（此时 choices 为空）。
            usage = event.get("usage")
            if isinstance(usage, dict):
                yield ChatDelta(
                    usage={
                        "prompt_tokens": usage.get("prompt_tokens", 0),
                        "completion_tokens": usage.get("completion_tokens", 0),
                        "total_tokens": usage.get("total_tokens", 0),
                    }
                )


class AnthropicProvider(BaseProvider):
    """Anthropic Messages API (native streaming, Claude)."""

    name = "anthropic"

    def __init__(self, base_url: str, api_key: str, model: str, temperature=None, max_tokens=None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    async def stream(self, messages, note: str = "") -> AsyncIterator[ChatDelta]:
        system_parts = [m.content for m in messages if m.role == "system"]
        convo = [m for m in messages if m.role in ("user", "assistant")]
        payload = {
            "model": self.model,
            "system": "\n".join(system_parts).strip(),
            "messages": _to_oai_messages(convo, mode="anthropic"),
            "stream": True,
        }
        # 开启扩展思维需 max_tokens 足够大，且 Anthropic 禁止 thinking 与 temperature 同时传。
        if self.max_tokens is not None and self.max_tokens >= 2048:
            payload["thinking"] = {"type": "enabled", "budget_tokens": 1024}
        elif self.temperature is not None:
            payload["temperature"] = self.temperature
        if self.max_tokens is not None:
            payload["max_tokens"] = self.max_tokens
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
            "x-api-key": self.api_key,
        }
        input_tokens = 0
        # 经网卡门面转发（异步 SSE 流式）。
        resp = await arequest(
            "POST", f"{self.base_url}/v1/messages",
            json=payload, headers=headers, stream=True, timeout=600.0,
        )
        if resp.status_code != 200:
            text = await resp.aread()
            raise RuntimeError(f"provider {resp.status_code}: {text[:400]}")
        async for line in resp.aiter_lines():
            if not line.startswith("data:"):
                continue
            sse_payload = line[5:].strip()
            try:
                event = json.loads(sse_payload)
            except json.JSONDecodeError:
                continue
            et = event.get("type")
            if et == "message_start":
                # 提示（输入）token 数在 message_start 的 usage 中给出。
                input_tokens = (event.get("usage") or {}).get("input_tokens", 0)
            elif et == "message_delta":
                # 补全（输出）token 数在 message_delta 的 usage 中给出。
                output_tokens = (event.get("usage") or {}).get("output_tokens", 0)
                yield ChatDelta(
                    usage={
                        "prompt_tokens": input_tokens,
                        "completion_tokens": output_tokens,
                        "total_tokens": input_tokens + output_tokens,
                    }
                )
            elif et == "content_block_delta":
                delta = event.get("delta", {}) or {}
                dt = delta.get("type")
                if dt == "thinking_delta":
                    thinking = delta.get("thinking")
                    if thinking:
                        yield ChatDelta(reasoning=thinking)
                elif dt == "text_delta":
                    text = delta.get("text")
                    if text:
                        yield ChatDelta(content=text)
                # signature_delta 等无需透传


_PROVIDERS = {"openai": OpenAIProvider, "anthropic": AnthropicProvider}


async def stream_chat(
    messages,
    model: str = "mock",
    note: str = "",
    provider=None,
    temperature=None,
    max_tokens=None,
    tools: list | None = None,
    thinking: dict | None = None,
) -> AsyncIterator[ChatDelta]:
    """Dispatch to a real provider when ``provider`` is supplied, else mock.

    ``provider.mode`` selects the protocol: "anthropic" -> Anthropic native,
    anything else (default) -> OpenAI-compatible. Yields ChatDelta with
    content and/or reasoning increments.
    """
    if provider is not None:
        cls = _PROVIDERS.get(getattr(provider, "mode", "openai"), OpenAIProvider)
        async for delta in cls(
            provider.base_url, provider.api_key, model,
            temperature=temperature, max_tokens=max_tokens,
        ).stream(messages, note=note, tools=tools, thinking=thinking):
            yield delta
        return
    async for delta in MockProvider().stream(messages, note=note):
        yield delta


def new_chat_id() -> str:
    return uuid.uuid4().hex[:12]


def now() -> int:
    return int(time.time())

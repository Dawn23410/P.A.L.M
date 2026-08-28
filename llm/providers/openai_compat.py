"""OpenAI 兼容协议 Provider（覆盖绝大多数国内外厂商）。"""
from __future__ import annotations

import json

import httpx

from ..models import Message, ModelParameters
from .base import BaseProvider, get_client


class OpenAICompatProvider(BaseProvider):
    async def complete(self, messages, params: ModelParameters, model: str, stream: bool = True):
        self._check_key()
        url = self.cfg.base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.cfg.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [self._conv(m) for m in messages],
            "stream": stream,
            "temperature": params.temperature,
            "top_p": params.top_p,
            "max_tokens": params.max_tokens,
            "frequency_penalty": params.frequency_penalty,
            "presence_penalty": params.presence_penalty,
        }
        # 透传额外参数（如关闭思考：{"enable_thinking": False} / {"thinking": {"type": "disabled"}}）
        if getattr(params, "extra_body", None):
            payload.update(params.extra_body)

        # ★ 复用全局单例客户端（HTTP/2 + 连接池 + 保活），不再每次新建连接
        client = get_client()

        if not stream:
            r = await client.post(url, headers=headers, json=payload)
            if r.status_code != 200:
                raise RuntimeError(f"[{self.name}] {r.status_code}: {r.text[:500]}")
            obj = r.json()
            msg = obj["choices"][0]["message"]
            content = msg.get("content") or ""
            reasoning = msg.get("reasoning_content") or ""
            usage = obj.get("usage", {})
            if reasoning:
                yield {"reasoning": reasoning}           # 非流式思维链（整段）
            yield {"content": content}
            yield {"done": True, "usage": usage}
            return

        usage: dict = {}
        async with client.stream("POST", url, headers=headers, json=payload) as resp:
            if resp.status_code != 200:
                txt = await resp.aread()
                raise RuntimeError(f"[{self.name}] {resp.status_code}: {txt.decode('utf-8', 'ignore')[:500]}")
            async for line in resp.aiter_lines():          # ★ 按行读取，非逐字节
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except Exception:
                    continue
                if obj.get("usage"):
                    usage = obj["usage"]
                try:
                    delta = obj["choices"][0]["delta"]
                except (KeyError, IndexError):
                    continue
                reasoning = delta.get("reasoning_content")
                if reasoning:
                    yield {"reasoning": reasoning}         # ★ 思维链增量（深度思考）
                content = delta.get("content")
                if content:
                    yield {"content": content}             # ★ 首字立即下发，无多余阻塞
        yield {"done": True, "usage": usage}

    @staticmethod
    def _conv(m: Message) -> dict:
        if m.role == "system":
            return {"role": "system", "content": m.content}
        if m.images:
            content = []
            if m.content:
                content.append({"type": "text", "text": m.content})
            for img in m.images:
                content.append({"type": "image_url", "image_url": {"url": img}})
            return {"role": m.role, "content": content}
        return {"role": m.role, "content": m.content}

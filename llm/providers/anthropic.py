"""Anthropic (Claude) 原生适配。"""
from __future__ import annotations

import json

import httpx

from ..models import Message, ModelParameters
from .base import BaseProvider


class AnthropicProvider(BaseProvider):
    async def complete(self, messages, params: ModelParameters, model: str, stream: bool = True):
        self._check_key()
        url = self.cfg.base_url.rstrip("/") + "/messages"
        headers = {
            "x-api-key": self.cfg.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        system_parts = [m.content for m in messages if m.role == "system"]
        conv_msgs = [m for m in messages if m.role != "system"]

        payload = {
            "model": model,
            "max_tokens": params.max_tokens,
            "messages": [await self._conv(m) for m in conv_msgs],
            "stream": stream,
            "temperature": params.temperature,
            "top_p": params.top_p,
        }
        if system_parts:
            payload["system"] = "\n".join(system_parts)

        async with httpx.AsyncClient(timeout=180) as client:
            if not stream:
                r = await client.post(url, headers=headers, json=payload)
                if r.status_code != 200:
                    raise RuntimeError(f"[{self.name}] {r.status_code}: {r.text[:500]}")
                obj = r.json()
                text = "".join(b.get("text", "") for b in obj.get("content", []))
                yield {"content": text}
                yield {"done": True, "usage": obj.get("usage", {})}
                return

            async with client.stream("POST", url, headers=headers, json=payload) as resp:
                if resp.status_code != 200:
                    txt = await resp.aread()
                    raise RuntimeError(f"[{self.name}] {resp.status_code}: {txt.decode('utf-8', 'ignore')[:500]}")
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    try:
                        obj = json.loads(data)
                    except Exception:
                        continue
                    etype = obj.get("type")
                    if etype == "content_block_delta" and obj.get("delta", {}).get("type") == "text_delta":
                        yield {"content": obj["delta"].get("text", "")}
                    elif etype == "message_stop":
                        yield {"done": True}
                    elif etype == "error":
                        raise RuntimeError(f"[{self.name}] {obj.get('error', {}).get('message', 'unknown error')}")

    async def _conv(self, m: Message) -> dict:
        if m.images:
            content = []
            if m.content:
                content.append({"type": "text", "text": m.content})
            for img in m.images:
                media, b64 = await self.image_to_b64(img)
                content.append({
                    "type": "image",
                    "source": {"type": "base64", "media_type": media, "data": b64},
                })
            return {"role": m.role, "content": content}
        return {"role": m.role, "content": m.content}

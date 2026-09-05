"""Google Gemini 原生适配。"""
from __future__ import annotations

import json

import httpx

from ..models import Message, ModelParameters
from .base import BaseProvider


class GeminiProvider(BaseProvider):
    async def complete(self, messages, params: ModelParameters, model: str, stream: bool = True):
        self._check_key()
        url = (
            f"{self.cfg.base_url.rstrip('/')}/models/{model}:"
            f"streamGenerateContent?alt=sse&key={self.cfg.api_key}"
        )
        headers = {"content-type": "application/json"}

        system_parts = [m.content for m in messages if m.role == "system"]
        conv_msgs = [m for m in messages if m.role != "system"]

        contents = []
        for m in conv_msgs:
            role = "model" if m.role == "assistant" else "user"
            parts = []
            if m.content:
                parts.append({"text": m.content})
            for img in (m.images or []):
                media, b64 = await self.image_to_b64(img)
                parts.append({"inline_data": {"mime_type": media, "data": b64}})
            contents.append({"role": role, "parts": parts})

        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": params.temperature,
                "topP": params.top_p,
                "maxOutputTokens": params.max_tokens,
            },
        }
        if system_parts:
            payload["systemInstruction"] = {"parts": [{"text": "\n".join(system_parts)}]}

        async with httpx.AsyncClient(timeout=180) as client:
            if not stream:
                r = await client.post(url.replace("streamGenerateContent", "generateContent").replace("?alt=sse", ""), headers=headers, json=payload)
                if r.status_code != 200:
                    raise RuntimeError(f"[{self.name}] {r.status_code}: {r.text[:500]}")
                obj = r.json()
                text = self._extract(obj)
                yield {"content": text}
                yield {"done": True, "usage": obj.get("usageMetadata", {})}
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
                    text = self._extract(obj)
                    if text:
                        yield {"content": text}
                yield {"done": True}

    @staticmethod
    def _extract(obj: dict) -> str:
        try:
            parts = obj["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts)
        except (KeyError, IndexError):
            return ""

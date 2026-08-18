"""Agent 工具：把文字合成为语音（经 tts_sovits 砖块的客户端）。"""
from __future__ import annotations

import hashlib
import os
import time

from palm_sdk.bricks.agent.tool_base import Tool, ToolSpec
from palm_sdk.core.config import settings
from .client import TtsClientError, synthesize_speech


class TtsTool(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="text_to_speech",
            description="将文字合成为语音。可用于让助手“开口说话”；可选指定参考音频进行音色克隆。",
            parameters={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "要合成的文本"},
                    "text_language": {"type": "string", "description": "文本语种：zh/en/ja/ko/yue，默认 zh"},
                    "refer_wav_path": {"type": "string", "description": "参考音频路径（音色克隆用），省略则用默认音色"},
                    "prompt_text": {"type": "string", "description": "参考音频对应的原文"},
                    "prompt_language": {"type": "string", "description": "参考音频语种：zh/en/ja/ko/yue"},
                },
                "required": ["text"],
            },
            event_type="",
            permission="tts.speak",
        )

    async def execute(self, text: str, text_language: str = "zh",
                      refer_wav_path: str = "", prompt_text: str = "",
                      prompt_language: str = "") -> str:
        payload = self._build_payload(text, text_language, refer_wav_path, prompt_text, prompt_language)
        try:
            audio = await synthesize_speech(payload, settings.SOVITS_API_URL, settings.SOVITS_API_ROUTE)
        except TtsClientError as exc:
            return f"语音合成失败：{exc}"
        filename = self._save_audio(audio)
        local_path = os.path.join(settings.SOVITS_OUTPUT_DIR, filename)
        return f"已合成语音：/api/tts/audio/{filename}（本地路径 {local_path}）"

    def _build_payload(self, text, text_language, refer_wav_path, prompt_text, prompt_language) -> dict:
        # 省略的参考音频回退到砖块配置的默认音色，使单音色开箱即用。
        payload = {"text": text, "text_language": text_language}
        if refer_wav_path:
            payload["refer_wav_path"] = refer_wav_path
            payload["prompt_text"] = prompt_text
            payload["prompt_language"] = prompt_language or "zh"
        elif settings.SOVITS_DEFAULT_REFER_WAV:
            payload["refer_wav_path"] = settings.SOVITS_DEFAULT_REFER_WAV
            payload["prompt_text"] = settings.SOVITS_DEFAULT_REFER_TEXT
            payload["prompt_language"] = settings.SOVITS_DEFAULT_REFER_LANG
        return payload

    def _save_audio(self, audio: bytes) -> str:
        os.makedirs(settings.SOVITS_OUTPUT_DIR, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        digest = hashlib.sha1(audio[:2048]).hexdigest()[:8]
        filename = f"tts_{stamp}_{digest}.wav"
        with open(os.path.join(settings.SOVITS_OUTPUT_DIR, filename), "wb") as fh:
            fh.write(audio)
        return filename
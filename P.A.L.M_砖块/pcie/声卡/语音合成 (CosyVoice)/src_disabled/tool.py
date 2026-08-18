"""Agent 工具：用自然语言描述「造」一个参考音色（供 GSV 克隆）。

侧重点不是语言合成，而是音色创造：本工具让助手基于一段基底参考音频 + 自然语言
风格描述，产出一段干净、可克隆的参考音频，并把 GSV（GPT-SoVITS）克隆所需的
refer_wav_path / prompt_text 一并返回。完整砖内直接调用 engine，不经 HTTP 代理。
"""
from __future__ import annotations

from palm_sdk.bricks.agent.tool_base import Tool, ToolSpec
from .engine import create_voice


class CreateVoiceTool(Tool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="create_voice",
            description=(
                "用自然语言描述创造一个新音色（参考音频）。"
                "返回的 wav 路径可直接交给 GSV（GPT-SoVITS）经 refer_wav_path 克隆做实时合成。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "自然语言风格描述，如「温柔的少女音色，带一点慵懒和笑意」；留空则纯克隆基底",
                    },
                    "seed_audio": {
                        "type": "string",
                        "description": "基底参考音频路径（必填，CosyVoice2 instruct2 以此为基底叠加风格）；留空则用默认种子音色",
                    },
                    "seed_text": {
                        "type": "string",
                        "description": "基底参考音频的原文（纯克隆模式必填，instruct2 模式可省略）",
                    },
                    "sample_text": {
                        "type": "string",
                        "description": "参考音频朗读的示例文案，默认用配置中的示例句",
                    },
                    "voice_id": {
                        "type": "string",
                        "description": "自定义音色名（留空自动生成）",
                    },
                },
                "required": ["description"],
            },
            event_type="",
            permission="cosyvoice.create_voice",
        )

    async def execute(self, description: str, seed_audio: str = "",
                      seed_text: str = "", sample_text: str = "",
                      voice_id: str = "") -> str:
        try:
            meta = create_voice(
                description=description,
                seed_audio=seed_audio,
                seed_text=seed_text,
                sample_text=sample_text,
                voice_id=voice_id,
            )
        except (ValueError, RuntimeError) as exc:
            return f"造音失败：{exc}"
        lines = [
            f"已造出音色「{meta['voice_id']}」（模式 {meta['mode']}）：",
            f"  参考音频：{meta['wav_path']}",
            f"  音频原文：{meta['sample_text']}",
            "GSV 克隆指令：",
            f"  refer_wav_path={meta['gsv_refer_wav_path']}",
            f"  prompt_text={meta['gsv_prompt_text']}",
            f"  prompt_language={meta['gsv_prompt_language']}",
        ]
        return "\n".join(lines)
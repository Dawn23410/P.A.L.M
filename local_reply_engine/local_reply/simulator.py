"""离线本地回复模拟器（local_reply 补足「无网模拟 LLM 聊天」缺口）。

WHY 存在：原 weave 域库只产出「注入 LLM 的风格约束」，本身不生成回复。
本模块用同源离线轻量聊天引擎（engine.StitchEngine）做**本地检索 + 缝合**生成，
使 local_reply 能在无网、无本地 LLM 的环境跑完整聊天循环——真实模拟 LLM 的轻量聊天，
满足：无网非 LLM / 语义检索答为所问 / 语料库自管理 / 四要素切分回归 / 随机性注入 / 语气匹配。

契约：LocalChatSimulator.reply(user_text) -> str，全程零网络、零 LLM。

架构：StitchEngine（检索+缝合，619 段梦瑶语料）为底座；weave 风格面
（PersonaFace/WeaveFace/RhythmFace）作为可选"表达风格约束"叠加层，
与引擎的四要素调味互补，可插拔。
"""
from __future__ import annotations

from dataclasses import replace

from .engine import StitchEngine
from .faces.base import FaceContext
from .faces.persona import PersonaFace
from .faces.rhythm import RhythmFace
from .faces.weave import WeaveFace
from .middleware.inject import PromptAssembler
from .persona_card import default_persona, CharacterCard


class LocalChatSimulator:
    """基于同源离线引擎的聊天模拟器（无网、无本地 LLM）。"""

    def __init__(self, persona_name: str = "梦瑶", use_style_faces: bool = True):
        card = default_persona()
        if persona_name and persona_name != card.name:
            card = replace(card, name=persona_name)
        self.card: CharacterCard = card
        self.history: list[tuple[str, str]] = []
        self.engine = StitchEngine()  # 零依赖 mock 模式，自动装载 619 段语料
        self._assembler = PromptAssembler()
        self._faces = [PersonaFace(), WeaveFace(), RhythmFace()] if use_style_faces else []

    # ---- 主入口：调用同源引擎做检索+缝合，生成角色化回复 ----
    def reply(self, user_text: str) -> str:
        """无网产出一轮角色化回复（答为所问、随机多变、语气匹配），更新历史。"""
        # 引擎 _callback 期望 history 为历史回复字符串列表（做话题承接），
        # 故取 self.history 中每轮的 reply 部分传入。
        past_replies = [r for (_, r) in self.history]
        result = self.engine.respond(user_text, past_replies)
        reply = result["reply"]
        self.history.append((user_text, reply))
        return reply

    # ---- 透明诊断：展示本轮引擎决策，便于验证 6 指标 ----
    def diagnose(self, user_text: str) -> dict:
        """返回引擎本轮完整决策（检索命中 / 情感 / 语气 / 改写变体 / 模式）。"""
        past_replies = [r for (_, r) in self.history]
        return self.engine.respond(user_text, past_replies)

    # ---- 风格面组合（可选增强层，证明 weave 子系统仍可用）----
    def build_prompt(self, user_text: str) -> str:
        """组装 weave 风格面的注入提示（透明可见，证明语境拆分+组合仍在）。"""
        ctx = FaceContext(user_text=user_text, persona=self.card, history=self.history)
        modules = [f.produce_module(ctx) for f in self._faces]
        modules = [m for m in modules if m is not None]
        return self._assembler.assemble(modules)

    @property
    def mode(self) -> str:
        return self.engine.mode

    @property
    def corpus_size(self) -> int:
        return len(self.engine.records)


if __name__ == "__main__":
    sim = LocalChatSimulator("梦瑶")
    print(f"引擎模式={sim.mode} | 语料段数={sim.corpus_size}")
    for turn in ["你好", "作业好多写不完", "我好累", "今天好开心呀"]:
        print(f"\n用户：{turn}")
        d = sim.diagnose(turn)
        print(f"梦瑶：{d['reply']}")
        print(f"  [情感={d['emotion']} | 语气={d.get('tone_manner')} | 召回={d['matches'][:1]} | 改写变体={len(d['rewrite_variants'])}]")

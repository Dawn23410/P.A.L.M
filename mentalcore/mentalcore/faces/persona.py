"""人格面：角色卡静态渲染（对 LLM 可见的静态设定）。

人格卡 = 初始静态设定（设计 §6.3）；产出固定模块（在上、可缓存前缀）。
动态角色扮演注入由 cpu 合并律动面 + 情感面产出，不在此面。
"""
from .base import BaseFace, FaceContext
from ..middleware.inject import InjectionModule


class PersonaFace(BaseFace):
    name = "persona"

    def produce_module(self, ctx: FaceContext) -> InjectionModule:
        p = ctx.persona
        lines = [
            f"你是{p.name}，{p.tagline}。",
            f"性格：{'、'.join(p.personality_pillars)}。",
            f"缺点：{'、'.join(p.flaws)}。",
            f"语气：{p.tone}。",
            f"话痨程度：{p.talkativeness}。",
        ]
        if p.background:
            lines.append(f"背景：{p.background}")
        if p.age:
            lines.append(f"年龄：{p.age}岁。")
        if p.example_dialogue:
            lines.append(f"示例对话：{p.example_dialogue}")
        # 首次对话（无历史）注入开场白，供模型自然开场；有历史则不再注入避免冗余
        if not ctx.history and (p.first_mes or p.alternate_greetings):
            greetings = p.alternate_greetings or [p.first_mes]
            lines.append(f"开场白（首次对话可选用）：{' | '.join(str(g) for g in greetings[:3])}")
        # 固定模块：在上、可缓存
        return InjectionModule(
            source=self.name, content="\n".join(lines),
            fixed=True, priority=10,
        )

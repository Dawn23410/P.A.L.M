"""记忆面：短期记忆检索（demo 简化）。

设计 §6.2：复用记忆层思路。demo 用近期对话当短期记忆动态模块；
核心记忆（用户画像）与向量库在 demo 中以空/简化呈现，留接口。
不可用即不注入：无历史则 available=False。
"""
from .base import BaseFace, FaceContext
from ..middleware.inject import InjectionModule


class MemoryFace(BaseFace):
    name = "memory"

    def produce_module(self, ctx: FaceContext) -> InjectionModule:
        recent = ctx.history[-3:]
        if not recent:
            return InjectionModule(source=self.name, content="", available=False)
        lines = ["【近期对话】"]
        for turn in recent:
            lines.append(f"用户：{turn.get('user', '')}")
            lines.append(f"{ctx.persona.name}：{turn.get('assistant', '')}")
        # 动态模块：在下
        return InjectionModule(
            source=self.name, content="\n".join(lines),
            fixed=False, priority=20,
        )

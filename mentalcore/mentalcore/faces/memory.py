"""记忆面：短期记忆（近期对话）+ 长期语义召回（设计 §6.2）。

- 短期：取最近 N 轮作为动态模块。
- 长期：若上下文携带可用语义记忆，对当前用户输入做语义检索，召回相关记忆片段。
- 不可用即不注入：无历史且无语义记忆则 available=False。
"""
from .base import BaseFace, FaceContext
from ..middleware.inject import InjectionModule

_RECENT_TURNS = 3
_RECALL_TOPK = 3
# 注入块上限：防长历史/长回复撑爆 prompt（上下文打磨，控制首字延迟）
_MAX_BLOCK_CHARS = 600


class MemoryFace(BaseFace):
    name = "memory"

    def produce_module(self, ctx: FaceContext) -> InjectionModule:
        blocks = []

        recent = ctx.history[-_RECENT_TURNS:]
        if recent:
            lines = ["【近期对话】"]
            for turn in recent:
                lines.append(f"用户：{turn.get('user', '')}")
                lines.append(f"{ctx.persona.name}：{turn.get('assistant', '')}")
            blocks.append(self._truncate("\n".join(lines)))

        recall = self._recall(ctx)
        if recall:
            lines = ["【长期记忆·相关】"]
            lines.extend(f"- {item}" for item in recall)
            blocks.append(self._truncate("\n".join(lines)))

        if not blocks:
            return InjectionModule(source=self.name, content="", available=False)
        return InjectionModule(
            source=self.name, content="\n\n".join(blocks),
            fixed=False, priority=20,
        )

    @staticmethod
    def _truncate(text: str) -> str:
        if len(text) <= _MAX_BLOCK_CHARS:
            return text
        return text[:_MAX_BLOCK_CHARS] + "…（已截断）"

    def _recall(self, ctx: FaceContext) -> list:
        mem = ctx.semantic_memory
        if mem is None or not getattr(mem, "available", False):
            return []
        try:
            results = mem.search(ctx.user_text, top_k=_RECALL_TOPK)
        except Exception:
            return []
        out = []
        for r in results:
            content = r.get("content") or ""
            score = r.get("score")
            if content:
                tag = f"（相关度 {score:.2f}）" if isinstance(score, (int, float)) else ""
                out.append(f"{content}{tag}")
        return out

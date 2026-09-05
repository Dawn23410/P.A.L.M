"""面上下文与内部基类约定（非插槽 ABC，仅内部 convenance）。"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from ..persona_card import CharacterCard


@dataclass
class FaceContext:
    """一轮对话中传给各面的上下文。"""
    user_text: str
    persona: CharacterCard
    history: list = field(default_factory=list)
    now: datetime = field(default_factory=datetime.now)
    affinity_stage_name: str = ""


class BaseFace:
    """内部面的轻量约定：统一 name 与 produce_module 接口（非抽象）。"""

    name: str = "base"

    def produce_module(self, ctx: FaceContext):
        """产出注入模块；返回 None 表示本面不参与本轮注入。"""
        return None

"""角色设定提供者：封装所有角色扮演相关逻辑，支持即插即用。

提供两个实现：
- DefaultPersonaProvider：完整角色扮演能力，用于主Agent/陪伴场景
- NoopPersonaProvider：空实现，用于纯工具Agent/Worker场景，无任何角色化逻辑

通过注入不同的PersonaProvider，同一个Agent内核可以无缝切换"陪伴模式"和"纯工具模式"，
无需修改任何内核代码。
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from .protocols import MemoryProtocol, PersonaProviderProtocol

_LOGGER = logging.getLogger(__name__)


class NoopPersonaProvider:
    """空角色设定提供者：无角色扮演，标准助手语气。用于Worker/纯工具Agent。"""

    persona_text: str = ""
    character_card: Any = None
    emotion_hint: str = ""

    def collect_known_character_names(self) -> list[str]:
        return []

    def strip_roleplay_tone(self, text: str, known_names: list[str]) -> str:
        return text

    def compile_roleplay_section(self, memory: MemoryProtocol | None, user_message: str) -> str:
        return (
            "【系统提示】当前未启用角色扮演。"
            "你必须以标准助手语气回答，禁止出现\"喵\"、动作描写、自称等任何角色化表达。"
        )

    def get_no_roleplay_constraint(self) -> str:
        return ""

    def should_filter_tools(self) -> bool:
        return False

    def clean_assistant_text(self, text: str, has_persona: bool) -> str:
        return text


class DefaultPersonaProvider:
    """默认角色设定提供者：完整角色扮演能力，封装所有角色相关逻辑。"""

    def __init__(
        self,
        persona_text: str = "",
        character_card: Any = None,
    ) -> None:
        self.persona_text = persona_text
        self.character_card = character_card
        self.emotion_hint: str = ""
        self._cached_character_names: Optional[list[str]] = None

    def _get_roleplay_api(self) -> Any:
        """获取角色扮演砖API（延迟导入，避免循环依赖）。"""
        from palm._core.interop import get_roleplay_api
        api = get_roleplay_api()
        if api is None:
            raise RuntimeError("角色扮演砖未注册")
        return api

    def collect_known_character_names(self) -> list[str]:
        """返回当前进程已加载的全部角色名（内置+用户导入）。"""
        if self._cached_character_names is not None:
            return self._cached_character_names
        names: list[str] = []
        try:
            for entry in self._get_roleplay_api().list_characters():
                name = (entry.get("name") or "").strip()
                if 2 <= len(name) <= 8:
                    names.append(name)
        except Exception:
            pass
        self._cached_character_names = names
        return names

    def invalidate_character_names_cache(self) -> None:
        """失效角色名缓存，新增/导入角色后调用。"""
        self._cached_character_names = None

    def strip_roleplay_tone(self, text: str, known_names: list[str]) -> str:
        """非角色扮演模式下，过滤文本里的角色化表达残留。"""
        return self._get_roleplay_api().strip_roleplay_tone(text, known_names)

    def compile_roleplay_section(self, memory: MemoryProtocol | None, user_message: str) -> str:
        """构建角色设定段落：静态人设 + 当前状态 + 动态叠加层。"""
        if not self.persona_text:
            return (
                "【系统提示】当前未启用角色扮演。"
                "你必须以标准助手语气回答，禁止出现\"喵\"、动作描写、自称等任何角色化表达。"
            )
        stance = ""
        if memory is not None:
            try:
                stance = memory.core.build_stance_injection(self.character_card)
            except Exception:
                pass
        section = self.persona_text
        if stance:
            section += "\n\n## 当前状态\n" + stance
        dyn = ""
        if memory is not None:
            try:
                dyn = memory.core.build_dynamic_overlay(user_message, stage_name="")
            except Exception:
                pass
        if dyn:
            section += "\n\n## 动态情境（仅此刻生效，不得视为角色卡固定设定）\n" + dyn
        return section

    def get_no_roleplay_constraint(self) -> str:
        """获取无角色时的强约束提示。"""
        try:
            return self._get_roleplay_api()._NO_ROLEPLAY_CONSTRAINT
        except Exception:
            return ""

    def should_filter_tools(self) -> bool:
        """角色扮演模式下是否需要限制工具（人格对话时不暴露全部工具）。"""
        return bool(self.persona_text)

    def clean_assistant_text(self, text: str, has_persona: bool) -> str:
        """清洗助手输出文本，非角色模式下去除角色化残留。"""
        if has_persona:
            return text
        return self.strip_roleplay_tone(text, self.collect_known_character_names())


def create_persona_provider(
    persona_text: str = "",
    character_card: Any = None,
) -> PersonaProviderProtocol:
    """工厂函数：根据是否有角色设定自动创建对应Provider。"""
    if persona_text:
        return DefaultPersonaProvider(persona_text=persona_text, character_card=character_card)
    return NoopPersonaProvider()
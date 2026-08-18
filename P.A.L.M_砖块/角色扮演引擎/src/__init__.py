"""角色扮演引擎子包：人设卡片 / 渲染 / 语气守卫。

2026-08-06 好感度域（affection/affinity_engine/affinity_store/dynamics_engine）
拆出为独立 affinity 砖。本砖保留角色卡域：CharacterCard / 人设渲染 /
语气污染守卫 / 角色导入，经 capabilities["roleplay_api"] 对外暴露。
consumers 用 app.bricks._shared.interop.get_roleplay_api() 取用。
"""
from __future__ import annotations

from .character import (
    CharacterCard,
    SceneBrief,
    VoiceProfile,
    builtin_characters,
    ensure_builtins,
    list_characters,
    load_character,
    save_character,
    set_mengyao_skill_path,
)
from .persona import render_persona
from .pollution_guard import (
    strip_roleplay_tone,
    _NO_ROLEPLAY_CONSTRAINT,
    BUILTIN_CHAR_NAMES,
)
from .import_skill import import_from_markdown

__all__ = [
    "CharacterCard",
    "VoiceProfile",
    "SceneBrief",
    "builtin_characters",
    "ensure_builtins",
    "list_characters",
    "load_character",
    "save_character",
    "set_mengyao_skill_path",
    "render_persona",
    "strip_roleplay_tone",
    "_NO_ROLEPLAY_CONSTRAINT",
    "BUILTIN_CHAR_NAMES",
    "import_from_markdown",
]

from . import brick  # noqa: E402,F401  触发砖注册

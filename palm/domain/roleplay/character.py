"""薄桥接层：实现已整合至独立项目「人格引擎」（`P.A.L.M/人格引擎/palm_persona`）。

原模块路径与导出符号保持不变，调用面零改动。实现：palm_persona.character
"""
import palm_boot  # noqa: F401  自举：挂载人格引擎等独立项目

from palm_persona.character import *  # noqa: F401,F403
from palm_persona.character import (  # noqa: F401
    VoiceProfile,
    SceneBrief,
    CharacterCard,
    builtin_characters,
    set_mengyao_skill_path,
    ensure_builtins,
    load_character,
    save_character,
    list_characters,
)

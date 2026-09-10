"""薄桥接层：实现已整合至独立项目「人格引擎」（`P.A.L.M/人格引擎/palm_persona`）。

原模块路径与导出符号保持不变，调用面零改动。实现：palm_persona.persona_render
"""
import palm_boot  # noqa: F401  自举：挂载人格引擎等独立项目

from palm_persona.persona_render import *  # noqa: F401,F403
from palm_persona.persona_render import (  # noqa: F401
    render_persona,
)

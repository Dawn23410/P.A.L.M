"""心智核心（微核心）包入口。

设计定位：P.A.L.M 主板上的「心智核心」砖，对外仅暴露 MentalCoreSlotPort
（send_message / receive / control / get_model_info）。本包独立可部署，
通过桥接 palm 库复用其模型层、SM4 加密、ChromaDB 向量记忆等真实能力。

关键约束（沿用 palm 铁律）：
- 所有出网必须经 palm._core.net 网卡门面；启动期必须注册网卡执行器。
- 缺失即降级：palm 不可导入 / gmssl 缺失 / chromadb 缺失 / Ollama 不在，
  核心都不崩溃，而是明文降级或语义记忆降级并明确告警（fail-operational）。
"""
import os
import sys

__version__ = "0.1.0"


def _ensure_palm_importable() -> None:
    """保证同仓库的 palm 库可导入：把仓库根目录（项目目录的上级）加入 sys.path。

    包为嵌套结构 mentalcore/mentalcore/__init__.py，故需向上两级到达 P.A.L.M/。
    """
    here = os.path.dirname(os.path.abspath(__file__))  # .../mentalcore/mentalcore
    project_root = os.path.dirname(here)               # .../mentalcore
    repo_root = os.path.dirname(project_root)          # .../P.A.L.M
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)


_ensure_palm_importable()

from .core import MentalCore, MentalCoreSlotPort, build_core  # noqa: E402
from .persona_card import CharacterCard, AffinityStage  # noqa: E402
from .transport import TransportPacket, ControlCode, INTENT_ROUTES  # noqa: E402
from .exo import build_exo, WorkCube, ExoSlotPort  # noqa: E402

__all__ = [
    "MentalCore",
    "MentalCoreSlotPort",
    "CharacterCard",
    "AffinityStage",
    "TransportPacket",
    "ControlCode",
    "INTENT_ROUTES",
    "build_core",
    "build_exo",
    "WorkCube",
    "ExoSlotPort",
    "__version__",
]

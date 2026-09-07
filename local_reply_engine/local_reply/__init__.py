"""local_reply — 本地回复引擎（从 P.A.L.M 实物抽取 + 打包的独立包）。

两大子系统：
1. 风格子系统（weave 域库）：faces/（7 面）+ middleware/（inject 组合 + split 语境拆分）
   + persona_card + transport，产出注入 LLM 的「表达风格约束」文本。
2. 同源聊天引擎（engine/）：移植自 P.A.L.M/palm/services/chat 的离线轻量聊天引擎
   （StitchEngine + HybridRetriever + Hub），零依赖、零联网、零本地 LLM，
   装载 619 段梦瑶语料，满足：无网非 LLM / 语义检索答为所问 / 语料自管理 /
   四要素切分回归 / 随机性注入 / 语气匹配——即模拟 LLM 的轻量聊天引擎。

依赖：零（不 import palm/blocks 等任何外层），可单独 import / 运行 / 移植。
"""
from .persona_card import CharacterCard, default_persona
from .faces.base import BaseFace, FaceContext
from .faces.weave import WeaveFace
from .simulator import LocalChatSimulator
from .router import HybridRouter, RouteResult
from .engine import (
    StitchEngine,
    HybridRetriever,
    Hub,
    Embedder,
    Sentiment,
    Rewriter,
    parse_reply,
    load_persona_bank,
    CONFIDENCE_THRESHOLDS,
)

__all__ = [
    "CharacterCard", "default_persona", "BaseFace", "FaceContext", "WeaveFace",
    "LocalChatSimulator",
    "StitchEngine", "HybridRetriever", "Hub", "Embedder", "Sentiment", "Rewriter",
    "parse_reply", "load_persona_bank", "CONFIDENCE_THRESHOLDS",
    "HybridRouter", "RouteResult",
]


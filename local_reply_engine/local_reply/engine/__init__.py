"""local_reply.engine — 同源离线轻量聊天引擎（移植自 P.A.L.M/palm/services/chat）。

设计：默认 mock 模式，纯标准库、零联网、零本地 LLM，开箱即用。
流水线：情感定语气 → 混合检索召回 → 桥接缝合 → 四要素调味 → 多样性改写 → 短上下文回调。

对外出口（均为零依赖、可离线使用）：
- StitchEngine      ：主引擎，respond(query, history) -> dict（含 reply/emotion/matches/...）
- HybridRetriever   ：BM25 + 字 n-gram TF-IDF 离线混合检索
- Hub / Embedder / Sentiment / Rewriter ：垂直小模型中心（mock 离线占位 + 可选真实权重升级）
- parse_reply / load_persona_bank ：四要素解析与语料库装载
"""
from .core import (
    HybridRetriever,
    parse_reply,
    load_persona_bank,
    char_ngrams,
    tokenize,
    has_signal,
    EXPRESSION_LIB,
)
from .engine import StitchEngine, CONFIDENCE_THRESHOLDS
from .hub import Hub, Embedder, Sentiment, Rewriter

__all__ = [
    "StitchEngine",
    "HybridRetriever",
    "Hub",
    "Embedder",
    "Sentiment",
    "Rewriter",
    "parse_reply",
    "load_persona_bank",
    "char_ngrams",
    "tokenize",
    "EXPRESSION_LIB",
]

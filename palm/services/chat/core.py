# -*- coding: utf-8 -*-
"""薄桥接层：对话缝合引擎·核心检索与解析 —— 实现已演进至独立包 local_reply_engine。

历史背景：本文件曾是独立包的同源副本；独立包此后大幅演进（信号判定/同义词归一/
OOD 识别/语义档/泛化补洞等），P.A.L.M 内留副本只会双份漂移，故收敛为再导出 shim。
真实实现：Desktop/P.A.L.M/缝合引擎/local_reply/engine/core.py。

兼容符号：parse_reply / load_persona_bank / char_ngrams / tokenize / HybridRetriever。
行为差异（来自独立包的演进，非回归）：
- load_persona_bank 不再按 limit=5000 截断（大语料全量加载）。
- HybridRetriever 已加字/词 n-gram 倒排索引与候选封顶（2 万条语料常数级检索）。
"""
from __future__ import annotations

import os
import sys

# 路径兜底：palm/services/chat -> palm/services -> palm -> P.A.L.M -> Desktop/P.A.L.M/缝合引擎
_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))),
    "P.A.L.M", "缝合引擎")

try:
    import local_reply  # 已 pip install / 已在 sys.path
except ImportError:
    if _PKG_ROOT not in sys.path:
        sys.path.insert(0, _PKG_ROOT)
    import local_reply  # 本地开发兜底（直接挂载目录）

from local_reply.engine.core import (  # noqa: E402,F401
    HybridRetriever,
    char_ngrams,
    load_persona_bank,
    parse_reply,
    tokenize,
)

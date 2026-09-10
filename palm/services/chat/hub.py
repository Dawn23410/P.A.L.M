# -*- coding: utf-8 -*-
"""薄桥接层：垂直小模型中心 —— 实现已演进至独立包 local_reply_engine。

历史背景：本文件曾是独立包的同源副本；独立包此后演进（bge-m3 权重自包含、
模型注册表、缓存指纹隔离等），P.A.L.M 内留副本只会双份漂移，故收敛为再导出 shim。
真实实现：Desktop/local_reply_engine/local_reply/engine/hub.py。

与旧副本的差异（来自独立包演进，非回归）：
- MODEL_DIR 随独立包走（local_reply/engine/models/weights，含 bge_m3/bge_small 权重），
  不再指向本砖 palm/services/chat/models/weights。
"""
from __future__ import annotations

import os
import sys

# 路径兜底：palm/services/chat -> palm/services -> palm -> P.A.L.M -> Desktop/local_reply_engine
_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))),
    "local_reply_engine")

try:
    import local_reply  # 已 pip install / 已在 sys.path
except ImportError:
    if _PKG_ROOT not in sys.path:
        sys.path.insert(0, _PKG_ROOT)
    import local_reply  # 本地开发兜底（直接挂载目录）

from local_reply.engine.hub import (  # noqa: E402,F401
    MODEL_DIR,
    Embedder,
    Hub,
    Rewriter,
    Sentiment,
    _OFFLINE_DIM,
)

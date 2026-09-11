# -*- coding: utf-8 -*-
"""薄桥接层：对话缝合引擎·运行时 —— 实现已演进至独立包 local_reply_engine。

历史背景：本文件曾是独立包的同源副本；独立包此后大幅演进（三档 tier、
语义 bge-m3 检索、置信度分级、思维链 reason 层等），P.A.L.M 内留副本只会
双份漂移，故收敛为再导出 shim。真实实现：Desktop/P.A.L.M/缝合引擎/local_reply/engine/engine.py。

与旧副本的差异（来自独立包演进，非回归）：
- StitchEngine 新增 tier="full"/"balanced"/"lite" 与 semantic 开关；
  use_jieba 默认 False（实测 jieba 词级分词令中文虚词干扰检索）。
- 默认语料/数据目录随独立包走（local_reply/engine/{corpus,data}，2837 条语料），
  不再指向本砖 palm/services/chat/{corpus,data}。
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

from local_reply.engine.engine import StitchEngine  # noqa: E402,F401

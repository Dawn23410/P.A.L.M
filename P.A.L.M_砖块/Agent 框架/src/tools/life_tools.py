"""生活/信息/生产力工具中转层（精简后仅 re-export 国内特色与产能工具）。"""
from __future__ import annotations

from .life_domestic_prod_tools import (
    ChengyuTool, FestivalTool, ChineseDictTool, QRCodeTool,
    PROD_TOOLS,
)

__all__ = ["PROD_TOOLS", "ChengyuTool", "FestivalTool", "ChineseDictTool", "QRCodeTool"]

"""parse 砖块：支持的文件类型与异常码约定。

控制器据此识别传入文件并分发；不支持的类型直接抛弃并回传异常码。
"""
from __future__ import annotations

from pathlib import Path

TEXT_EXTS = {".txt", ".md", ".markdown", ".html", ".htm", ".csv", ".json"}
DOC_EXTS = {".docx", ".pdf", ".xlsx", ".xlsm", ".pptx"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp"}

SUPPORTED = TEXT_EXTS | DOC_EXTS | IMAGE_EXTS

# 异常码（字符串 + 数字，便于前端分支与日志追踪）。
EXCEPTION_CODES = {
    "UNSUPPORTED_FILE": 4001,   # 文件类型不在 SUPPORTED 内，已抛弃
    "ENGINE_UNAVAILABLE": 5002,  # 图片/OCR 依赖未安装
    "PROCESS_FAILED": 5001,      # 处理过程抛出未预期异常
}


def is_supported(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED


def kind_of(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in DOC_EXTS:
        return "document"
    return "text"

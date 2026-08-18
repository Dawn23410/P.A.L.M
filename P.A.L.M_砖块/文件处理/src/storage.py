"""文件落盘工具：校验 + 防路径穿越 + 写盘 + 元信息。

校验层（大小/扩展名 allowlist/魔数一致性）与落盘层分离，落盘函数只调用校验。
"""
from __future__ import annotations

import logging
import mimetypes
import os
import re
import uuid

from fastapi import UploadFile
from pydantic import BaseModel

from palm_sdk.core.config import settings

_LOGGER = logging.getLogger(__name__)

# 单文件上限 50MB；单请求最多 10 个
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_FILES_PER_REQUEST = 10

# 允许的业务格式（扩展名 allowlist）
ALLOWED_EXTENSIONS = {
    "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "md", "csv",
    "png", "jpg", "jpeg", "gif", "webp", "bmp",
    "zip", "json", "py", "js", "ts", "mp3", "wav", "mp4",
}

# 魔数 → 真实扩展名（仅取最关键字节）
_MAGIC = {
    b"%PDF": "pdf",
    b"PK\x03\x04": "zip",
    b"\x89PNG\r\n\x1a\n": "png",
    b"\xff\xd8\xff": "jpg",
    b"GIF8": "gif",
    b"BM": "bmp",
    b"RIFF": "wav",
    b"ID3": "mp3",
    b"\x00\x00\x00\x18ftypmp4": "mp4",
}

# 声明扩展名与魔数一致才放行的格式（纯文本类信任声明，不在此列）
_STRICT_EXTS = {
    "pdf", "docx", "xlsx", "pptx", "png", "jpg", "jpeg",
    "gif", "bmp", "zip", "wav", "mp3", "mp4",
}

_FID_RE = re.compile(r"^[0-9a-f]{12}$")


class UploadRejected(Exception):
    """上传被校验层拒绝（携带中文原因）。"""


class UploadedFile(BaseModel):
    id: str
    name: str
    size: int
    mime: str
    url: str


def _safe_name(filename: str) -> str:
    # 仅保留原始文件名（basename），避免路径穿越把文件写到目录之外。
    return os.path.basename(filename) or "file"


def _detect_real_ext(content: bytes, declared_ext: str) -> str:
    """用魔数判定真实类型，与声明扩展名交叉验证。

    命中魔数返回魔数扩展名；无魔数特征（纯文本类）信任声明。
    """
    head = content[:16]
    for magic, ext in _MAGIC.items():
        if head.startswith(magic):
            return ext
    return declared_ext


def _validate_upload(filename: str, content: bytes) -> str:
    """校验单文件：大小 + 扩展名 allowlist + 魔数一致性。

    返回可信扩展名；不满足则抛 UploadRejected。
    """
    if len(content) > MAX_UPLOAD_BYTES:
        raise UploadRejected(f"文件超过 {MAX_UPLOAD_BYTES // 1024 // 1024}MB 上限")
    ext = os.path.splitext(filename)[1].lower().lstrip(".")
    if not ext or ext not in ALLOWED_EXTENSIONS:
        raise UploadRejected(f"不支持的格式：.{ext or '未知'}")
    real_ext = _detect_real_ext(content, ext)
    if ext in _STRICT_EXTS and real_ext != ext and not (ext == "jpeg" and real_ext == "jpg"):
        raise UploadRejected(f"文件实际类型(.{real_ext})与扩展名(.{ext})不符")
    return ext


def _is_valid_fid(fid: str) -> bool:
    """fid 为 12 位 hex（上传时生成）才属合法标识。"""
    return bool(_FID_RE.match(fid))


def _resolve_upload_path(upload_dir: str, fid: str) -> str | None:
    """按 fid 在上传目录查找匹配文件，防路径穿越。

    fid 可为 12 位 hex（匹配 {fid}.*）或完整存储文件名（精确匹配）。
    """
    if not os.path.isdir(upload_dir):
        return None
    for name in os.listdir(upload_dir):
        if name == fid or (name.startswith(fid + ".") and _is_valid_fid(fid)):
            return os.path.join(upload_dir, name)
    return None


def read_upload_bytes(fid: str) -> bytes | None:
    """按 fid 读取上传文件内容，供其他砖块复用；无匹配返回 None。"""
    path = _resolve_upload_path(settings.UPLOAD_DIR, fid)
    if path is None or not os.path.isfile(path):
        return None
    with open(path, "rb") as fh:
        return fh.read()


async def save_uploads(
    files: list[UploadFile], upload_dir: str
) -> tuple[list[UploadedFile], list[dict]]:
    """落盘上传文件，返回（成功列表, 被拒列表）。

    单文件失败隔离：被拒文件记入 rejected 并写日志，不拖累整批。
    """
    if len(files) > MAX_FILES_PER_REQUEST:
        raise UploadRejected(f"单次最多上传 {MAX_FILES_PER_REQUEST} 个文件")
    os.makedirs(upload_dir, exist_ok=True)
    saved: list[UploadedFile] = []
    rejected: list[dict] = []
    for f in files:
        try:
            content = await f.read()
            ext = _validate_upload(f.filename or "file", content)
            fid = uuid.uuid4().hex[:12]
            stored = f"{fid}.{ext}"
            with open(os.path.join(upload_dir, stored), "wb") as out:
                out.write(content)
            saved.append(
                UploadedFile(
                    id=fid,
                    name=_safe_name(f.filename or "file"),
                    size=len(content),
                    mime=f.content_type or mimetypes.guess_type(stored)[0] or "application/octet-stream",
                    url=f"/api/files/{fid}/content",
                )
            )
            _LOGGER.info("上传成功 fid=%s name=%s size=%d ext=%s", fid, f.filename, len(content), ext)
        except UploadRejected as e:
            rejected.append({"name": f.filename, "error": str(e)})
            _LOGGER.warning("上传被拒 name=%s reason=%s", f.filename, e)
        except Exception as e:
            rejected.append({"name": f.filename, "error": f"保存失败：{e}"})
            _LOGGER.exception("上传失败 name=%s", f.filename)
    return saved, rejected
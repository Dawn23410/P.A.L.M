"""file 砖块：接收文件并经应用层鉴权提供访问（移除无鉴权静态目录）。

所有文件类操作收进 /api/files 路由组；读取经应用层鉴权，不再暴露静态目录。
"""
from __future__ import annotations

import mimetypes
import os

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response

from palm_sdk.core.config import settings
from palm_sdk.core.logging import get_logger
from palm_sdk.security import require_api_token
from palm_sdk.bricks.base import Brick, BrickManifest, registry
from palm_sdk.permission import PermissionSpec, RiskLevel, require_permission

logger = get_logger(__name__)
from .storage import (
    MAX_FILES_PER_REQUEST,
    UploadedFile,
    _resolve_upload_path,
    read_upload_bytes,
    save_uploads,
)

router = APIRouter(prefix="/api/files", tags=["file"])


@router.post("/upload", dependencies=[Depends(require_api_token), Depends(require_permission("file.write"))])
async def upload(files: list[UploadFile] = File(...)) -> list[UploadedFile]:
    saved, rejected = await save_uploads(files, settings.UPLOAD_DIR)
    logger.info("文件上传 saved=%d rejected=%d", len(saved), len(rejected))
    if not saved and rejected:
        raise HTTPException(status_code=400, detail={"uploaded": 0, "errors": rejected})
    return saved


@router.get("/{file_id}/content", dependencies=[Depends(require_api_token), Depends(require_permission("file.read"))])
def read_upload(file_id: str) -> Response:
    """经应用层鉴权读取上传文件（替代原无鉴权静态目录）。

    file_id 为 12 位 hex 或完整存储文件名；无匹配返回 404。
    """
    path = _resolve_upload_path(settings.UPLOAD_DIR, file_id)
    if path is None or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="文件不存在")
    with open(path, "rb") as fh:
        data = fh.read()
    media_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
    return Response(content=data, media_type=media_type)


brick = Brick(
    manifest=BrickManifest(
        name="file",
        title="文件处理",
        description="接收上传文件并经应用层鉴权提供访问（移除无鉴权静态目录）",
        bus_type="board",
        can_accept_files=True,
    ),
    router=router,
    capabilities={"read_upload": read_upload_bytes},
    permissions=[
        PermissionSpec(key="file.read", title="读取本地文件",
                        description="读取你电脑上的任意本地文件内容（纯文本）。",
                        risk=RiskLevel.MEDIUM, brick="file"),
        PermissionSpec(key="file.write", title="写入本地文件",
                        description="在你的电脑上创建或修改文件（写入/追加/复制/移动/建目录）。",
                        risk=RiskLevel.MEDIUM, brick="file"),
        PermissionSpec(key="file.delete", title="删除本地文件",
                        description="永久删除你电脑上的本地文件，不可恢复。",
                        risk=RiskLevel.HIGH, brick="file"),
        PermissionSpec(key="file.fs_query", title="浏览与检索文件",
                        description="列出目录、查看文件元信息、按名搜索文件、计算文件哈希。",
                        risk=RiskLevel.LOW, brick="file"),
    ],
)
registry.register(brick)
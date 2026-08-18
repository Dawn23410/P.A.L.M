"""parse 砖块：文件解析与结构化。

三个语义化端点（hybrid 方案，不强制单 invoke）：
- POST /api/parse           文件传入接口（异步处理，立即返回 job_id）
- GET  /api/parse/{job_id}  状态传出接口（pending/processing/done/failed + 异常码）
- GET  /api/parse/{job_id}/result  结构化数据传出接口（done 返回数据，failed 返回异常码）

不支持的文件在传入接口即被抛弃并回传异常码 UNSUPPORTED_FILE(4001)。
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from palm_sdk.core.logging import get_logger
from palm_sdk.security import require_api_token
from palm_sdk.bricks.base import Brick, BrickManifest, registry
from .controller import _fail_unsupported, run_parse_job

logger = get_logger(__name__)
from .jobs import store
from .types import is_supported

router = APIRouter(
    prefix="/api/parse",
    tags=["parse"],
    dependencies=[Depends(require_api_token)],
)
_executor = ThreadPoolExecutor(max_workers=1)  # 串行处理，避免 OCR 并发竞争


@router.post("")
async def upload_parse(file: UploadFile = File(...)):
    file_bytes = await file.read()
    filename = file.filename or "unknown"
    if not is_supported(Path(filename)):
        job = store.create(filename)
        _fail_unsupported(job, filename)
        return JSONResponse(store.to_status(job), status_code=200)
    job = store.create(filename)
    loop = asyncio.get_running_loop()
    asyncio.ensure_future(
        loop.run_in_executor(_executor, run_parse_job, job, file_bytes, filename)
    )
    logger.info("解析任务创建 job_id=%s filename=%s", job.job_id, filename)
    return JSONResponse(store.to_status(job), status_code=202)


@router.get("/{job_id}", dependencies=[Depends(require_api_token)])
async def get_status(job_id: str):
    job = store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "任务不存在"})
    return store.to_status(job)


@router.get("/{job_id}/result", dependencies=[Depends(require_api_token)])
async def get_result(job_id: str):
    job = store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "任务不存在"})
    if job.status in ("pending", "processing"):
        return JSONResponse({"job_id": job_id, "status": job.status}, status_code=202)
    if job.status == "failed":
        return JSONResponse(
            {"status": "failed", "code": job.code, "code_num": job.code_num, "message": job.message},
            status_code=200,
        )
    return job.result


brick = Brick(
    manifest=BrickManifest(
        name="parse",
        title="解析与结构化",
        description="识别文件类型并分发到文档/图片解析脚本，输出统一结构化数据（含图片 OCR）",
        bus_type="pcie",
        can_accept_files=True,
    ),
    router=router,
)
registry.register(brick)
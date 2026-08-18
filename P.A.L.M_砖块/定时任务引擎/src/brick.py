"""定时任务引擎砖：提供任务管理 HTTP 端点与跨砖能力。

- HTTP：列表/创建/查询/删除/启停，供设置页与 agent 工具调用。
- capabilities：create_job / list_jobs / delete_job / on_entity_deleted。
  on_entity_deleted 接 housekeeping 扇出：会话或角色被删时，清掉指向它的任务，
  避免孤儿定时任务在已删除上下文里继续触发。
- 调度循环由 engine.py 单例在导入时启动，本砖仅负责状态与派发入口。
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from palm_sdk.bricks.base import Brick, BrickManifest, registry
from palm_sdk.security import require_api_token
from .cron import compute_next_fire
from .engine import engine
from .store import ScheduleJob, ScheduleStore

store = ScheduleStore()
router = APIRouter(prefix="/api/scheduler", tags=["scheduler"])

_VALID_TYPES = ("once", "interval", "cron", "rrule")


class JobCreate(BaseModel):
    conversation_id: str
    character_id: str = ""
    model: str = ""
    title: str
    brief: str
    schedule_type: str
    schedule_value: str


class JobUpdate(BaseModel):
    enabled: bool


def _serialize(job: ScheduleJob) -> dict:
    return job.to_dict()


@router.get("/jobs", dependencies=[Depends(require_api_token)])
async def list_jobs(conversation_id: str = ""):
    """列出任务；可指定会话过滤。"""
    jobs = store.list_jobs(conversation_id)
    return {"jobs": [_serialize(job) for job in jobs]}


@router.post("/jobs", dependencies=[Depends(require_api_token)])
async def create_job(payload: JobCreate):
    """创建定时任务，并立即计算下次触发时间。"""
    if payload.schedule_type not in _VALID_TYPES:
        raise HTTPException(status_code=400, detail=f"不支持的周期类型：{payload.schedule_type}")
    next_run = compute_next_fire(
        payload.schedule_type, payload.schedule_value, time.time()
    )
    if next_run is None and payload.schedule_type == "once":
        raise HTTPException(status_code=400, detail="一次性时间已过期或格式无效")
    job = store.create_job(
        conversation_id=payload.conversation_id,
        character_id=payload.character_id,
        model=payload.model,
        title=payload.title,
        brief=payload.brief,
        schedule_type=payload.schedule_type,
        schedule_value=payload.schedule_value,
        next_run=next_run or 0.0,
    )
    return {"job": _serialize(job)}


@router.get("/jobs/{job_id}", dependencies=[Depends(require_api_token)])
async def get_job(job_id: str):
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"job": _serialize(job)}


@router.delete("/jobs/{job_id}", dependencies=[Depends(require_api_token)])
async def delete_job(job_id: str):
    if not store.delete_job(job_id):
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"ok": True}


@router.post("/jobs/{job_id}/toggle", dependencies=[Depends(require_api_token)])
async def toggle_job(job_id: str, payload: JobUpdate):
    """启停任务；重新启用时重算下次触发时间。"""
    job = store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    changes: dict = {"enabled": payload.enabled}
    if payload.enabled:
        nxt = compute_next_fire(job.schedule_type, job.schedule_value, time.time(), job.last_run)
        changes["next_run"] = nxt or 0.0
    store.update_job(job_id, **changes)
    return {"ok": True}


def _handle_entity_deleted(entity_type: str, entity_id: str) -> str:
    """级联清理：会话/角色删除时移除指向它的定时任务。"""
    if entity_type == "conversation":
        removed = store.delete_by_conversation(entity_id)
        return f"conversation {entity_id}: 清理 {removed} 个定时任务"
    if entity_type == "character":
        removed = store.delete_by_character(entity_id)
        return f"character {entity_id}: 清理 {removed} 个定时任务"
    return f"ignored entity_type={entity_type}"


brick = Brick(
    manifest=BrickManifest(
        name="scheduler",
        title="定时任务引擎",
        description="定时触发与主动推送：持久化任务、周期触发、经 agent 生成并 SSE 推送。",
        bus_type="board",
    ),
    router=router,
    capabilities={
        # 供 agent 工具创建任务；返回 ScheduleJob（同进程直接取 .id）。
        "create_job": lambda *a, **k: store.create_job(*a, **k),
        "list_jobs": lambda conv="": store.list_jobs(conv),
        "delete_job": lambda job_id: store.delete_job(job_id),
        "on_entity_deleted": _handle_entity_deleted,
    },
)
registry.register(brick)
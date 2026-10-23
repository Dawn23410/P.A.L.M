"""parse 砖块：内存任务存储（单机桌面场景，无需持久化）。

每个上传文件对应一个 Job；状态沿 pending -> processing -> done/failed 推进。
后台线程处理时通过 update 写回结果；状态接口与结果接口只读该表。
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Job:
    job_id: str
    filename: str
    status: str = "pending"            # pending | processing | done | failed
    code: str | None = None            # 异常码（失败时）
    code_num: int | None = None
    message: str | None = None
    progress: int = 0
    result: Any = None
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, filename: str) -> Job:
        jid = uuid.uuid4().hex[:12]
        job = Job(job_id=jid, filename=filename)
        with self._lock:
            self._jobs[jid] = job
        return job

    def get(self, jid: str) -> Job | None:
        with self._lock:
            return self._jobs.get(jid)

    def update(self, job: Job, **kw: Any) -> None:
        for k, v in kw.items():
            setattr(job, k, v)
        if kw.get("status") in ("done", "failed"):
            job.finished_at = time.time()
        with self._lock:
            self._jobs[job.job_id] = job

    def to_status(self, job: Job) -> dict:
        return {
            "job_id": job.job_id,
            "filename": job.filename,
            "status": job.status,
            "code": job.code,
            "code_num": job.code_num,
            "message": job.message,
            "progress": job.progress,
            "created_at": job.created_at,
            "finished_at": job.finished_at,
        }


store = JobStore()

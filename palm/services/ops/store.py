"""定时任务仓库：把调度任务持久化到 Data/schedules.json。

任务由 scheduler 砖统一管理；tick 线程与 HTTP 端点共享此仓库，读写加锁，
避免守护线程与请求并发改写同一文件导致损坏。
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass

from palm._core.config import settings
from palm._core.paths import brick_data_dir


@dataclass
class ScheduleJob:
    """单个定时任务。

    schedule_type: once(一次性 ISO 时间) / interval(每 N 秒) / cron(5 字段) / rrule(RFC5545)。
    schedule_value: 与类型对应的字符串（见 cron.compute_next_fire）。
    next_run: 下次触发时间戳（0 表示待计算）；last_run: 上次触发时间。
    """

    id: str
    conversation_id: str
    character_id: str
    model: str
    title: str
    brief: str
    schedule_type: str
    schedule_value: str
    enabled: bool = True
    created_at: float = 0.0
    last_run: float | None = None
    next_run: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ScheduleJob":
        return cls(
            id=data.get("id", ""),
            conversation_id=data.get("conversation_id", ""),
            character_id=data.get("character_id", ""),
            model=data.get("model", ""),
            title=data.get("title", ""),
            brief=data.get("brief", ""),
            schedule_type=data.get("schedule_type", "once"),
            schedule_value=data.get("schedule_value", ""),
            enabled=bool(data.get("enabled", True)),
            created_at=float(data.get("created_at", 0.0) or 0.0),
            last_run=data.get("last_run"),
            next_run=float(data.get("next_run", 0.0) or 0.0),
        )


def _store_path() -> str:
    # 已配置存储池则用全局池（位置无关）；否则回退砖内 data/（砖可随意移动）。
    base = getattr(settings, "STORAGE_POOL_DIR", "") or brick_data_dir(__file__)
    return os.path.join(base, "schedules.json")


class ScheduleStore:
    """调度任务 JSON 仓库（线程安全）。"""

    def __init__(self, path: str | None = None) -> None:
        self._path = path or _store_path()
        self._lock = threading.RLock()

    def _load(self) -> list[dict]:
        try:
            with open(self._path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return data if isinstance(data, list) else []
        except FileNotFoundError:
            return []
        except Exception:
            # 损坏文件不阻断调度器：以空列表降级，避免守护线程崩溃。
            return []

    def _save(self, jobs: list[dict]) -> None:
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        tmp = f"{self._path}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(jobs, handle, ensure_ascii=False, indent=2)
        # Windows 下目标文件可能被外部进程（杀毒/索引器/另一实例）锁定，
        # 直接 os.replace 会抛 PermissionError(WinError 32/5) 致写入丢失；
        # 这是真实部署的健壮性缺陷，重试吸收瞬时共享冲突而非任其失败。
        last_exc: OSError | None = None
        for attempt in range(5):
            try:
                os.replace(tmp, self._path)
                return
            except OSError as exc:
                last_exc = exc
                if attempt < 4:
                    time.sleep(0.01 * (2 ** attempt))
        if last_exc:
            raise last_exc

    def list_jobs(self, conversation_id: str = "") -> list[ScheduleJob]:
        with self._lock:
            raw = self._load()
        jobs = [ScheduleJob.from_dict(item) for item in raw]
        if conversation_id:
            jobs = [job for job in jobs if job.conversation_id == conversation_id]
        return jobs

    def get_job(self, job_id: str) -> ScheduleJob | None:
        with self._lock:
            raw = self._load()
        for item in raw:
            if item.get("id") == job_id:
                return ScheduleJob.from_dict(item)
        return None

    def create_job(
        self,
        conversation_id: str,
        character_id: str,
        model: str,
        title: str,
        brief: str,
        schedule_type: str,
        schedule_value: str,
        next_run: float = 0.0,
    ) -> ScheduleJob:
        job = ScheduleJob(
            id=f"sch_{uuid.uuid4().hex[:10]}",
            conversation_id=conversation_id,
            character_id=character_id,
            model=model,
            title=title,
            brief=brief,
            schedule_type=schedule_type,
            schedule_value=schedule_value,
            created_at=time.time(),
            next_run=next_run,
        )
        with self._lock:
            raw = self._load()
            raw.append(job.to_dict())
            self._save(raw)
        return job

    def delete_job(self, job_id: str) -> bool:
        with self._lock:
            raw = self._load()
            kept = [item for item in raw if item.get("id") != job_id]
            if len(kept) == len(raw):
                return False
            self._save(kept)
        return True

    def update_job(self, job_id: str, **changes) -> bool:
        with self._lock:
            raw = self._load()
            found = False
            for item in raw:
                if item.get("id") == job_id:
                    item.update(changes)
                    found = True
                    break
            if found:
                self._save(raw)
        return found

    def delete_by_conversation(self, conversation_id: str) -> int:
        with self._lock:
            raw = self._load()
            kept = [item for item in raw if item.get("conversation_id") != conversation_id]
            removed = len(raw) - len(kept)
            if removed:
                self._save(kept)
        return removed

    def delete_by_character(self, character_id: str) -> int:
        with self._lock:
            raw = self._load()
            kept = [item for item in raw if item.get("character_id") != character_id]
            removed = len(raw) - len(kept)
            if removed:
                self._save(kept)
        return removed
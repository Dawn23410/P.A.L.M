"""存储池元信息持久化。

分类配置（容量上限、清除规则）与文件索引统一存于 pool.json，
与磁盘上的真实文件分离，避免遍历文件系统统计。写入用临时文件 +
原子替换，防止中途崩溃留下半截 JSON 导致元信息丢失。
"""
from __future__ import annotations

import itertools
import json
import os
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field

# 落盘临时文件名自增序列：配合进程 pid 保证唯一，规避残留 .tmp 锁。
_SAVE_SEQ = itertools.count()


@dataclass
class CleanupRule:
    # 清除顺序固定从老到新（需求硬性要求），此处仅保留开关与阈值。
    order: str = "oldest_first"
    keep_min_count: int = 0
    # 超过该天数的文件优先清除（None 表示不按年龄裁剪）。
    max_age_days: float | None = None
    # 上传后若超出容量上限，自动触发清除腾出空间。
    auto: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "CleanupRule":
        return cls(
            order=d.get("order", "oldest_first"),
            keep_min_count=int(d.get("keep_min_count", 0)),
            max_age_days=d.get("max_age_days"),
            auto=bool(d.get("auto", True)),
        )


@dataclass
class CategoryMeta:
    name: str
    # 0 表示不限容量。
    capacity_bytes: int = 0
    cleanup: CleanupRule = field(default_factory=CleanupRule)
    created_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "capacity_bytes": self.capacity_bytes,
            "cleanup": self.cleanup.to_dict(),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CategoryMeta":
        return cls(
            name=d["name"],
            capacity_bytes=int(d.get("capacity_bytes", 0)),
            cleanup=CleanupRule.from_dict(d.get("cleanup", {})),
            created_at=float(d.get("created_at", 0.0)),
        )


@dataclass
class FileRecord:
    id: str
    category: str
    # 原始文件名（展示用）。
    name: str
    # 磁盘文件名（uuid + 扩展名，防冲突与路径穿越）。
    stored_name: str
    size: int
    # 入库时间戳（epoch 秒），用于「从老到新」排序。
    stored_at: float
    # 落盘时是否经本机 SM4 加密（用于加密状态检测）。
    encrypted: bool = False
    # 落盘时是否经 DEFLATE 无损压缩（用于压缩状态检测；旧记录无此字段默认 False，按明文读）。
    compressed: bool = False
    # 冷热分层（hot/warm/cold），默认热；旧记录无此字段默认热。
    tier: str = "hot"
    # 最近访问时间戳（epoch 秒），清理排序用；旧记录无此字段时回退到入库时间。
    last_access_at: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "FileRecord":
        return cls(
            id=d["id"],
            category=d["category"],
            name=d["name"],
            stored_name=d["stored_name"],
            size=int(d["size"]),
            stored_at=float(d["stored_at"]),
            encrypted=bool(d.get("encrypted", False)),
            compressed=bool(d.get("compressed", False)),
            tier=d.get("tier", "hot"),
            last_access_at=float(d.get("last_access_at", d.get("stored_at", 0.0))),
        )


# 当前固件（数据模型）版本；旧 pool.json 无此字段视为 1，加载后幂等迁移到 2。
SCHEMA_VERSION = 2


def default_tiers() -> dict:
    """冷热分层默认策略：热层不自动清理，温层超限自动清理，冷层归档不删。"""
    return {
        "hot": {"keep_max_bytes": 0, "auto_clean": False},
        "warm": {"keep_max_bytes": 0, "auto_clean": True},
        "cold": {"keep_max_bytes": 0, "auto_clean": False},
    }


@dataclass
class PoolState:
    categories: dict[str, CategoryMeta] = field(default_factory=dict)
    files: list[FileRecord] = field(default_factory=list)
    # 固件版本号；作为旧数据迁移入口，写入时始终为最新值。
    schema_version: int = SCHEMA_VERSION
    # 总字节配额（0=不限），对标 usage 砖的 token 配额，由管理芯片强制。
    quota_bytes: int = 0
    # 冷热分层默认策略（可被分类级策略覆盖）。
    tiers: dict = field(default_factory=default_tiers)
    # 审计事件环形队列（管理芯片写入，容量上限见审计模块 MAX_EVENTS）。
    events: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "quota_bytes": self.quota_bytes,
            "tiers": self.tiers,
            "events": self.events,
            "categories": {k: v.to_dict() for k, v in self.categories.items()},
            "files": [f.to_dict() for f in self.files],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PoolState":
        return cls(
            categories={
                k: CategoryMeta.from_dict(v) for k, v in d.get("categories", {}).items()
            },
            files=[FileRecord.from_dict(x) for x in d.get("files", [])],
            schema_version=int(d.get("schema_version", 1)),
            quota_bytes=int(d.get("quota_bytes", 0)),
            tiers=d.get("tiers") or default_tiers(),
            events=d.get("events") or [],
        )


def migrate_state(state: PoolState) -> PoolState:
    """幂等迁移旧 pool.json：补全 tier / last_access_at 默认，并把版本号抬到最新。

    旧文件记录缺 tier 时按热层处理；缺 last_access_at 时回退到入库时间，
    保证「从老到新」清理语义对存量文件依然成立。
    """
    for f in state.files:
        if not f.tier:
            f.tier = "hot"
        if not f.last_access_at:
            f.last_access_at = f.stored_at
    state.schema_version = SCHEMA_VERSION
    return state


class PoolStore:
    def __init__(self, root: str) -> None:
        self.root = root
        self._meta_path = os.path.join(root, "pool.json")
        self._lock = threading.Lock()
        self._state = self._load()

    def _load(self) -> PoolState:
        try:
            with open(self._meta_path, "r", encoding="utf-8") as f:
                return migrate_state(PoolState.from_dict(json.load(f)))
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            return PoolState()

    def _save(self) -> None:
        # 每次写用进程内唯一临时名，避免残留 .tmp 被外部进程锁定导致 PermissionError（Windows）。
        os.makedirs(self.root, exist_ok=True)
        tmp = f"{self._meta_path}.{os.getpid()}.{next(_SAVE_SEQ)}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._state.to_dict(), f, ensure_ascii=False, indent=2)
        os.replace(tmp, self._meta_path)

    # 进入即持锁，退出自动落盘：保证元信息与磁盘文件状态一致。
    @contextmanager
    def transaction(self):
        with self._lock:
            yield self._state
            self._save()

    def get_state(self) -> PoolState:
        # 只读访问内存中的最新状态，不触发落盘（供只读端点使用，避免无谓写与锁竞争）。
        return self._state

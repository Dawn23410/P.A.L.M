"""存储占比分析：把存储池（Data 目录）中各分类的实际占用按比例归类，供前端进度条展示。

浏览器无法扫盘，占比必须由后端计算。直接复用 PoolStore 的元信息（分类容量与文件索引），
按分类汇总已用空间，取代原先对整仓的语义扫描（软件/配置/对话…），使进度条只反映存储池本身。
"""
from __future__ import annotations

import time

from palm._core.config import settings
from palm._core.paths import fallback_dir, resolve_storage
from .pool import compute_stats
from .state import PoolStore

_CACHE_TTL = 30.0
_cache: dict = {"ts": 0.0, "data": None}


def compute_breakdown() -> dict:
    store = PoolStore(fallback_dir(settings.STORAGE_POOL_DIR, __file__))
    stats = compute_stats(store)
    segments = [{"key": c["name"], "bytes": c["used_bytes"]} for c in stats["categories"]]
    total_used = stats["total_used"]
    # 容量下限取各分类上限之和与实际已用二者较大值，保证未用空间不为负。
    capacity = max(stats["total_capacity"], total_used)
    free = capacity - total_used
    return {
        "capacity": capacity,
        "used": total_used,
        "free": free,
        "segments": segments,
    }


def get_breakdown() -> dict:
    # 元信息读取较频繁，加短时缓存避免每次打开设置都重算。
    now = time.time()
    if _cache["data"] is not None and now - _cache["ts"] < _CACHE_TTL:
        return _cache["data"]
    data = compute_breakdown()
    _cache["data"] = data
    _cache["ts"] = now
    return data
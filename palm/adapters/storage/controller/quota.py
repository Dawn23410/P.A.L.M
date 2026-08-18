"""管理芯片·配额引擎：字节配额（对标 token 配额），写入前预留、超额拒绝。

默认 quota_bytes=0 表示不限，确保重构后既有使用行为不变；仅当用户在面板设置配额后生效。
分类级容量上限（CategoryMeta.capacity_bytes）沿用既有清理机制，本引擎只负责全局字节配额。
"""
from __future__ import annotations

import time

from palm_sdk.bricks._shared.eventbus import STORAGE_QUOTA_EXCEEDED, emit
from ..controller.audit import record_event
from ..state import PoolStore


class StorageQuotaError(Exception):
    """写入将突破字节配额时抛出（调用方据此拒绝写入并记审计）。"""


def _total_used(state) -> int:
    return sum(f.size for f in state.files)


def reserve_bytes(store: PoolStore, size: int, category: str = "") -> None:
    """写入前预留字节；若突破全局配额则发布事件并抛 StorageQuotaError。

    分类级容量上限不在此处拦截（既有 cleanup.auto 机制负责腾挪），
    本函数只守全局配额这道硬闸，避免无限增长撑爆磁盘。
    """
    state = store.get_state()
    if store_quota := state.quota_bytes:
        used = _total_used(state)
        if used + size > store_quota:
            payload = {
                "category": category, "used_bytes": used,
                "quota_bytes": store_quota, "want_bytes": size,
            }
            emit(STORAGE_QUOTA_EXCEEDED, payload)
            record_event(store, "quota_exceeded", payload)
            raise StorageQuotaError(
                "存储配额不足：已用 %d / 限额 %d，本次需 %d" % (used, store_quota, size)
            )


def set_global_quota(store: PoolStore, quota_bytes: int) -> dict:
    """设置总字节配额（0=不限）；返回更新后的配额视图。"""
    with store.transaction() as state:
        state.quota_bytes = max(0, int(quota_bytes))
    return get_storage_quota(store)


def set_category_quota(store: PoolStore, name: str, capacity_bytes: int) -> dict | None:
    """设置分类级字节上限（覆盖既有 CategoryMeta.capacity_bytes）。分类不存在返回 None。"""
    with store.transaction() as state:
        meta = state.categories.get(name)
        if meta is None:
            return None
        meta.capacity_bytes = max(0, int(capacity_bytes))
    return {"name": name, "capacity_bytes": max(0, int(capacity_bytes))}


def get_storage_quota(store: PoolStore) -> dict:
    """配额总览：已用 / 限额 / 各分类占用。只读，不落盘。"""
    state = store.get_state()
    return {
        "used_bytes": _total_used(state),
        "quota_bytes": state.quota_bytes,
        "unlimited": state.quota_bytes == 0,
        "by_category": [
            {
                "name": c.name,
                "used_bytes": sum(f.size for f in state.files if f.category == c.name),
                "capacity_bytes": c.capacity_bytes,
            }
            for c in state.categories.values()
        ],
    }
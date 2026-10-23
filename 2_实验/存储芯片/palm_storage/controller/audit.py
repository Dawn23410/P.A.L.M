"""管理芯片·审计：存储事件环形队列（写/删/清理/配额拒绝/归档）。

事件持久化在 pool.json 的 events 字段，保留最近 MAX_EVENTS 条。record_event 经
transaction 落盘，调用方必须处于事务之外（避免持锁重入死锁）。
"""
from __future__ import annotations

import time

from ..state import PoolStore

# 环形队列容量上限：超过则丢弃最旧。
MAX_EVENTS = 500


def record_event(store: PoolStore, kind: str, payload: dict | None = None) -> None:
    """记录一条审计事件（带时间戳）；超额自动截断最旧条目。"""
    with store.transaction() as state:
        state.events.append({"ts": time.time(), "kind": kind, "payload": payload or {}})
        if len(state.events) > MAX_EVENTS:
            state.events = state.events[-MAX_EVENTS:]


def list_storage_events(store: PoolStore, limit: int = 100) -> list:
    """返回最近 limit 条审计事件（倒序，最新在前）；只读。"""
    events = store.get_state().events
    return list(reversed(events[-limit:]))

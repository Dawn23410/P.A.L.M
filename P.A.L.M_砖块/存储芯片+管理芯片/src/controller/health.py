"""管理芯片·健康监测（SMART 隐喻）：容量 / 剩余 / 加密覆盖 / 碎片率 / 最近错误。

只读聚合，不落盘，供前端「健康度」面板与 BIOS 自检消费。
"""
from __future__ import annotations

from ..state import PoolStore


def storage_health(store: PoolStore) -> dict:
    """返回存储健康快照：容量、剩余、加密覆盖率、碎片率、配额、最近异常。"""
    state = store.get_state()
    total_used = sum(f.size for f in state.files)
    total_capacity = sum(c.capacity_bytes for c in state.categories.values())
    encrypted = sum(1 for f in state.files if f.encrypted)
    file_count = len(state.files)
    category_count = len(state.categories)

    # 碎片率粗估：平均每个分类下的文件数（越多越碎）；仅作趋势指标。
    fragmentation = round(file_count / category_count, 2) if category_count else 0.0
    encryption_coverage = round(encrypted / file_count, 3) if file_count else 0.0

    # 最近异常：从审计事件里挑出含错误/拒绝语义的条目（最多 5 条）。
    recent_errors = [
        e for e in reversed(state.events)
        if e.get("kind") in ("quota_exceeded", "error")
    ][:5]

    # 综合健康灯：无最近异常且未突破总配额即视为健康（SMART 隐喻的整体结论）。
    quota_exceeded = bool(total_capacity) and total_used > total_capacity
    healthy = (not recent_errors) and (not quota_exceeded)

    return {
        "total_used": total_used,
        "total_capacity": total_capacity,
        "remaining": max(0, total_capacity - total_used) if total_capacity else None,
        "file_count": file_count,
        "category_count": category_count,
        "encrypted_count": encrypted,
        "encryption_coverage": encryption_coverage,
        "fragmentation": fragmentation,
        "quota_bytes": state.quota_bytes,
        "recent_errors": recent_errors,
        "healthy": healthy,
    }

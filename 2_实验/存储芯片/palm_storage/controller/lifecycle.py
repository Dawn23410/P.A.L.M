"""管理芯片·生命周期引擎：冷热分层 + vault 归档联动。

在既有容量/年龄清理（pool.cleanup_category）之上叠加分层策略：
- 热层（hot）：不自动清理；
- 温层（warm）：超限自动删除；
- 冷层（cold）：超限先归档到保险库（冗余层）再删除，保证可找回。

归档经本砖冗余层 vault（同砖内 `..redundancy`，非跨砖），best-effort 失败不阻断删除。
"""
from __future__ import annotations

from palm._core.eventbus import STORAGE_ARCHIVE, STORAGE_CLEANUP, emit
from ..controller.audit import record_event
from ..pool import _remove_disk, category_dir, category_used, cleanup_category
from ..redundancy import vault as _vault
from ..state import PoolStore


def set_tier_policy(store: PoolStore, tier: str, keep_max_bytes: int = 0, auto_clean: bool = False) -> dict:
    """设置某冷热分层的默认策略（keep_max_bytes / auto_clean）。"""
    with store.transaction() as state:
        policy = state.tiers.setdefault(tier, {"keep_max_bytes": 0, "auto_clean": False})
        policy["keep_max_bytes"] = max(0, int(keep_max_bytes))
        policy["auto_clean"] = bool(auto_clean)
    return {tier: state.tiers.get(tier)}


def set_category_tier(store: PoolStore, name: str, tier: str) -> bool:
    """把某分类下全部文件标记为指定分层（如把日志分类整体设为 cold 归档）。"""
    with store.transaction() as state:
        hit = False
        for f in state.files:
            if f.category == name:
                f.tier = tier
                hit = True
        return hit


def archive_file_to_vault(store: PoolStore, file_id: str) -> dict:
    """把指定文件归档到保险库（保留存储索引，仅副本兜底），供手动归档。"""
    state = store.get_state()
    rec = next((f for f in state.files if f.id == file_id), None)
    if not rec:
        return {"ok": False, "error": "文件不存在"}
    disk_path = category_dir(store, rec.category) + "/" + rec.stored_name
    meta = _vault.archive_before_delete(disk_path)
    emit(STORAGE_ARCHIVE, {"file_id": file_id, "category": rec.category})
    record_event(store, "archive", {"file_id": file_id, "category": rec.category, "name": rec.name})
    return {"ok": meta is not None, "meta": meta}


def _archive_and_remove(store: PoolStore, state, rec) -> None:
    """冷层文件：先归档副本到保险库，再删磁盘与索引（best-effort，归档失败也删）。

    注意：此函数在事务内调用，不得在此 emit/record（会持锁重入）；事件在事务外统一发。
    """
    disk_path = category_dir(store, rec.category) + "/" + rec.stored_name
    try:
        _vault.archive_before_delete(disk_path)
    except Exception:  # noqa: BLE001
        pass  # 归档失败不阻断删除，回收站仍是主兜底
    _remove_disk(store, rec)
    state.files.remove(rec)


def apply_cleanup_policy(store: PoolStore, name: str) -> list:
    """对分类执行清理：先既有容量/年龄清理，再按冷层策略归档后删。

    返回被移除的 FileRecord 列表（冷层移除项已先归档到保险库）。
    审计/事件在事务外统一发布，避免持锁重入死锁。
    """
    removed = cleanup_category(store, name)
    with store.transaction() as state:
        if name not in state.categories:
            return removed
        policy = state.tiers.get("cold") or {}
        if not policy.get("auto_clean") or not policy.get("keep_max_bytes", 0):
            return removed
        used = category_used(state, name)
        for f in sorted(
            [x for x in state.files if x.category == name],
            key=lambda x: x.last_access_at,
        ):
            if used <= policy["keep_max_bytes"]:
                break
            _archive_and_remove(store, state, f)
            removed.append(f)
            used -= f.size
    if removed:
        emit(STORAGE_CLEANUP, {"category": name, "removed": len(removed)})
        for f in removed:
            kind = "archive" if f.tier == "cold" else "cleanup"
            record_event(store, kind, {"file_id": f.id, "category": f.category, "name": f.name})
    return removed
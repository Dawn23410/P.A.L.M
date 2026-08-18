"""存储池核心逻辑：分类存储、容量约束、自适应清除。

所有写操作都在 PoolStore.transaction 内完成（持锁 + 落盘），
因此元信息与磁盘文件不会偏离。清除顺序固定「从老到新」。
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid

from .state import CategoryMeta, FileRecord, PoolStore
from .compression import compress_bytes, decompress_bytes
from .controller.quota import reserve_bytes, StorageQuotaError
from palm_sdk.bricks.base import registry

_DAY_SECONDS = 86400.0


def _crypto_capabilities() -> tuple[object | None, object | None]:
    # 经 registry 消费 crypto 砖暴露的加密能力，不跨砖 import 模块。
    brick = registry.get("crypto")
    if not brick:
        return (None, None)
    caps = getattr(brick, "capabilities", {}) or {}
    return (caps.get("encrypt_bytes"), caps.get("decrypt_bytes"))


def _is_storage_auto_cleanup_enabled() -> bool:
    # 存储自动清理为手动开关，默认关闭，避免静默删除用户文件。
    settings_brick = registry.get("settings")
    if not settings_brick:
        return False
    load_fn = (getattr(settings_brick, "capabilities", {}) or {}).get("load_app_settings")
    if not load_fn:
        return False
    try:
        return bool(load_fn().get("agentStorageAutoCleanup", False))
    except Exception:
        return False


def _is_encryption_enabled() -> bool:
    # 经 registry 消费 crypto 砖暴露的加密开关，不跨砖 import 模块。
    brick = registry.get("crypto")
    if not brick:
        return False
    fn = (getattr(brick, "capabilities", {}) or {}).get("is_enabled")
    return bool(fn()) if callable(fn) else False


def safe_category(name: str) -> str:
    # 去掉路径分隔与系统保留字符，避免分类名被用作目录穿越。
    cleaned = re.sub(r'[\\/:*?"<>|]', "_", name).strip()
    return cleaned[:64] or "default"


def category_dir(store: PoolStore, name: str) -> str:
    return os.path.join(store.root, safe_category(name))


def category_files(state, name: str) -> list[FileRecord]:
    files = [f for f in state.files if f.category == name]
    files.sort(key=lambda f: f.stored_at)
    return files


def category_used(state, name: str) -> int:
    return sum(f.size for f in state.files if f.category == name)


def _prepare_stored_bytes(content: bytes) -> tuple[bytes, bool, bool]:
    """明文→压缩→加密；返回(最终落盘字节, 是否压缩, 是否加密)。"""
    is_compressed = False
    processed = content
    if content:
        candidate = compress_bytes(content)
        if len(candidate) < len(content):
            processed = candidate
            is_compressed = True
    # 加密仅在该开关开启且能力可用时生效（记录 encrypted 供检测）。
    encrypt_fn, _ = _crypto_capabilities()
    is_encrypted = encrypt_fn is not None and _is_encryption_enabled()
    if is_encrypted:
        encrypted = encrypt_fn(processed)
        stored_bytes = encrypted if encrypted is not None else processed
    else:
        stored_bytes = processed
    return stored_bytes, is_compressed, is_encrypted


def _commit_stored_record(store, category, filename, record, dedupe_name) -> None:
    """事务内提交记录：去重清理 + 分类兜底 + 追加 + 容量清除。"""
    with store.transaction() as state:
        # 固定文件名覆盖（settings.json / 会话日志）：清掉同名旧副本，整段在单事务内完成，
        # 避免并发保存各自留副本导致文件无限累积（滑块拖动等高并发场景尤其明显）。
        if dedupe_name:
            for stale in [f for f in state.files if f.category == category and f.name == filename]:
                _remove_disk(store, stale)
                state.files.remove(stale)
        if category not in state.categories:
            # 未显式建分类时按不限容量兜底，保证「统一分类存储」始终可用。
            state.categories[category] = CategoryMeta(name=category, created_at=time.time())
        state.files.append(record)
        meta = state.categories[category]
        if meta.cleanup.auto and _is_storage_auto_cleanup_enabled():
            for removed in _collect_cleanup(state, meta):
                _remove_disk(store, removed)
                state.files.remove(removed)


def store_file(
    store: PoolStore, category: str, filename: str, content: bytes,
    dedupe_name: bool = False,
) -> FileRecord:
    os.makedirs(category_dir(store, category), exist_ok=True)
    fid = uuid.uuid4().hex[:12]
    ext = os.path.splitext(os.path.basename(filename) or "")[1]
    stored_name = f"{fid}{ext}"
    disk_path = os.path.join(category_dir(store, category), stored_name)
    # 写入前预留字节配额：突破全局配额则抛 StorageQuotaError（默认不限，行为不变）。
    reserve_bytes(store, len(content), category)
    stored_bytes, is_compressed, is_encrypted = _prepare_stored_bytes(content)
    with open(disk_path, "wb") as out:
        out.write(stored_bytes)
    record = FileRecord(
        id=fid,
        category=category,
        name=os.path.basename(filename) or "file",
        stored_name=stored_name,
        size=len(content),
        stored_at=time.time(),
        encrypted=is_encrypted,
        compressed=is_compressed,
        tier="hot",
        last_access_at=time.time(),
    )
    _commit_stored_record(store, category, filename, record, dedupe_name)
    return record


def delete_file(store: PoolStore, file_id: str) -> bool:
    with store.transaction() as state:
        target = next((f for f in state.files if f.id == file_id), None)
        if not target:
            return False
        _remove_disk(store, target)
        state.files.remove(target)
    return True


def delete_category(store: PoolStore, name: str) -> bool:
    with store.transaction() as state:
        if name not in state.categories:
            return False
        for f in [x for x in state.files if x.category == name]:
            _remove_disk(store, f)
            state.files.remove(f)
        del state.categories[name]
    cat_dir = category_dir(store, name)
    if os.path.isdir(cat_dir):
        # 删空目录避免残留；非空时不强制（理论上已清空）。
        try:
            os.rmdir(cat_dir)
        except OSError:
            pass
    return True


def cleanup_category(store: PoolStore, name: str) -> list[FileRecord]:
    with store.transaction() as state:
        meta = state.categories.get(name)
        if not meta:
            return []
        removed = _collect_cleanup(state, meta)
        for f in removed:
            _remove_disk(store, f)
            state.files.remove(f)
    return removed


def category_view(state, name: str) -> dict:
    meta = state.categories.get(name)
    if not meta:
        return {}
    return {
        "name": name,
        "capacity_bytes": meta.capacity_bytes,
        "used_bytes": category_used(state, name),
        "count": len([f for f in state.files if f.category == name]),
        "cleanup": meta.cleanup.to_dict(),
    }


def compute_stats(store: PoolStore) -> dict:
    # 只读统计：经 get_state() 取内存最新状态，不触发落盘（GET 端点不应写盘）。
    state = store.get_state()
    total_used = sum(f.size for f in state.files)
    total_capacity = sum(c.capacity_bytes for c in state.categories.values())
    per_category = [
        {
            "name": c.name,
            "used_bytes": category_used(state, c.name),
            "capacity_bytes": c.capacity_bytes,
            "count": len([f for f in state.files if f.category == c.name]),
            "over_capacity": c.capacity_bytes > 0
            and category_used(state, c.name) > c.capacity_bytes,
        }
        for c in state.categories.values()
    ]
    return {
            "total_used": total_used,
            "total_capacity": total_capacity,
            "total_count": len(state.files),
            "unlimited_categories": sum(
                1 for c in state.categories.values() if c.capacity_bytes == 0
            ),
            "categories": per_category,
        }


def _collect_cleanup(state, meta: CategoryMeta) -> list[FileRecord]:
    """返回应当被清除的文件（从老到新），不修改 state。"""
    files = category_files(state, meta.name)
    rule = meta.cleanup
    removed: list[FileRecord] = []

    # 1) 按年龄裁剪：超过 max_age_days 的文件优先清除（仍是老的在前）。
    if rule.max_age_days is not None:
        threshold = time.time() - rule.max_age_days * _DAY_SECONDS
        for f in files:
            if len(files) - len(removed) <= rule.keep_min_count:
                break
            if f.stored_at < threshold:
                removed.append(f)

    # 2) 按容量裁剪：仍超限则继续从老到新删除，直到低于上限或触及保底数量。
    if meta.capacity_bytes > 0:
        remain = [f for f in files if f not in removed]
        used = sum(f.size for f in remain)
        for f in remain:
            if used <= meta.capacity_bytes:
                break
            if len(remain) - len(removed) <= rule.keep_min_count:
                break
            removed.append(f)
            used -= f.size
    return removed


def _remove_disk(store: PoolStore, record: FileRecord) -> None:
    path = os.path.join(category_dir(store, record.category), record.stored_name)
    if os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass


def read_file_content(store: PoolStore, file_id: str) -> bytes | None:
    # 只读取元信息（不落盘）；解密/解压放锁外，加密文件经 crypto 能力还原、压缩文件经 zlib 还原。
    state = store.get_state()
    rec = next((f for f in state.files if f.id == file_id), None)
    if not rec:
        return None
    path = os.path.join(category_dir(store, rec.category), rec.stored_name)
    if not os.path.isfile(path):
        return None
    with open(path, "rb") as fh:
        raw = fh.read()
    data = raw
    if rec.encrypted:
        _, decrypt_fn = _crypto_capabilities()
        if not decrypt_fn:
            return None
        try:
            data = decrypt_fn(raw)
        except Exception:
            return None
    if rec.compressed:
        try:
            data = decompress_bytes(data)
        except Exception:
            return None
    return data


def _transform_record(store: PoolStore, record: FileRecord, to_encrypted: bool) -> None:
    # 单文件就地加/解密磁盘内容并翻转元信息标记；读取失败则跳过该文件。
    path = os.path.join(category_dir(store, record.category), record.stored_name)
    if not os.path.isfile(path):
        return
    encrypt_fn, decrypt_fn = _crypto_capabilities()
    with open(path, "rb") as fh:
        raw = fh.read()
    if to_encrypted:
        if encrypt_fn is None:
            return
        out = encrypt_fn(raw)
    else:
        if decrypt_fn is None:
            return
        try:
            out = decrypt_fn(raw)
        except Exception:
            return
    with open(path, "wb") as out_fh:
        if out is None:
            return  # 加解密失败，跳过该文件（如密钥变更后旧文件无法解密）
        out_fh.write(out)
    with store.transaction() as state:
        for r in state.files:
            if r.id == record.id:
                r.encrypted = to_encrypted
                break


def encrypt_all_plaintext_gen(store: PoolStore):
    # 逐文件加密所有明文记录并流式 yield 进度；用以在开启加密开关时全量处理存量。
    with store.transaction() as state:
        plaintext = [f for f in state.files if not f.encrypted]
    yield {"type": "start", "total": len(plaintext)}
    for i, rec in enumerate(plaintext):
        _transform_record(store, rec, to_encrypted=True)
        yield {"type": "progress", "processed": i + 1, "total": len(plaintext), "current": rec.name}


def decrypt_all_encrypted_gen(store: PoolStore):
    # 逐文件解密所有加密记录并流式 yield 进度；用以在关闭加密开关时全量回退明文。
    with store.transaction() as state:
        encrypted = [f for f in state.files if f.encrypted]
    yield {"type": "start", "total": len(encrypted)}
    for i, rec in enumerate(encrypted):
        _transform_record(store, rec, to_encrypted=False)
        yield {"type": "progress", "processed": i + 1, "total": len(encrypted), "current": rec.name}


def encryption_summary(store: PoolStore) -> dict:
    # 检测存储池文件加密状态：是否全量加密、各计数与加密能力可用性。
    _, encrypt_fn = _crypto_capabilities()
    state = store.get_state()
    total = len(state.files)
    encrypted = sum(1 for f in state.files if f.encrypted)
    return {
        "available": encrypt_fn is not None,
        "enabled": _is_encryption_enabled(),
        "encrypted_count": encrypted,
        "total_count": total,
        "all_encrypted": total > 0 and encrypted == total,
    }


def index_existing_file(store: PoolStore, category: str, filename: str, disk_path: str) -> FileRecord | None:
    # 登记已存在于磁盘的文件进索引（不重写内容），使绕过 store_file 直接落盘的产物
    # 也能被统计/删除/GC 追踪，避免成为无索引孤儿。已存在同名 stored_name 则跳过。
    if not os.path.isfile(disk_path):
        return None
    with store.transaction() as state:
        if category not in state.categories:
            # 未显式建分类时按不限容量兜底，保证登记始终可用。
            state.categories[category] = CategoryMeta(name=category, created_at=time.time())
        stored_name = os.path.basename(disk_path)
        if any(f.category == category and f.stored_name == stored_name for f in state.files):
            return None
        record = FileRecord(
            id=uuid.uuid4().hex[:12],
            category=category,
            name=os.path.basename(filename),
            stored_name=stored_name,
            size=os.path.getsize(disk_path),
            stored_at=time.time(),
            encrypted=False,
            compressed=False,
            tier="hot",
            last_access_at=time.time(),
        )
        state.files.append(record)
    return record


def find_config_file(store: PoolStore, category: str, filename: str) -> FileRecord | None:
    # 在指定分类下按文件名定位唯一配置记录（如 settings.json）；只读，不落盘。
    state = store.get_state()
    return next(
        (f for f in state.files if f.category == category and f.name == filename),
        None,
    )


def save_config_json(store: PoolStore, category: str, filename: str, payload: dict) -> None:
    # 以固定文件名存一份 canonical 配置 JSON；dedupe_name 在单事务内清掉同名旧副本，
    # 避免滑块拖动等高频并发保存各自留下新 uuid 副本而无限累积。
    store_file(
        store, category, filename,
        json.dumps(payload, ensure_ascii=False).encode("utf-8"), dedupe_name=True,
    )


def load_config_json(store: PoolStore, category: str, filename: str) -> dict | None:
    # 读回配置 JSON；加密文件经 crypto 能力还原；解析失败或损坏返回 None。
    rec = find_config_file(store, category, filename)
    if not rec:
        return None
    data = read_file_content(store, rec.id)
    if data is None:
        return None
    try:
        return json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None


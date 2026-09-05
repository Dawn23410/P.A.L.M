"""文件级兜底保险库：AI 删除文件前自动归档副本，供用户找回。

设计目标：
- 作为「AI 误删文件」的终极兜底：run_code 子进程内的破坏性删除（os.remove/shutil.rmtree 等）
  经 safe_delete 拦截、路由回收站之前，先在此处留一份副本。即使回收站被清空，副本仍在。
- 版本化：同一文件多次被删，每次都是独立副本（文件名带毫秒级时间戳），互不覆盖。
- 时间戳：每份副本与其元数据均带删除时间，便于追溯。
- 元数据：每份副本附带 .meta.json（原始路径 / 删除时间 / 大小 / 原修改时间 / 是否目录），
  找回时据此还原到原始位置。
- best-effort：归档失败（权限/超大/磁盘满）绝不阻断真实删除——回收站仍是主兜底。

路径解析：默认 %LOCALAPPDATA%/P.A.L.M/ai_delete_vault（与现有本地 trash 同源、可达性一致）；
可用环境变量 PALM_VAULT_DIR 覆盖（管理部署可指向 ProgramData 等双方可达的共享路径）。
注意：隔离账户模式下沙箱子进程以 sandbox_runner 身份运行，其写入的 vault 主进程未必可读
（与现有 trash 局限一致）；可通过 PALM_VAULT_DIR 指向双方可达的共享目录缓解。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import tempfile
from datetime import datetime

_LOGGER = logging.getLogger(__name__)

# 单份归档的体积上限（字节）：超过则跳过归档，避免大目录撑爆磁盘。默认 200MB。
VAULT_MAX_BYTES = int(os.environ.get("PALM_VAULT_MAX_BYTES", "200000000"))

# 目录归档时扫描文件数上限：超过则跳过归档（best-effort，避免遍历超大树卡死）。
VAULT_MAX_FILES = int(os.environ.get("PALM_VAULT_MAX_FILES", "5000"))


def resolve_vault_root() -> str:
    """解析保险库根目录：PALM_VAULT_DIR 优先，否则 %LOCALAPPDATA%/P.A.L.M/ai_delete_vault。"""
    env = os.environ.get("PALM_VAULT_DIR")
    if env:
        return env
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    return os.path.join(base, "P.A.L.M", "ai_delete_vault")


def _entry_id(original_path: str, vault_abs: str) -> str:
    """以原始路径 + 物理副本路径派生稳定唯一 id（同文件同毫秒删两次也不会冲突）。"""
    return hashlib.sha1(("%s|%s" % (original_path, vault_abs)).encode("utf-8")).hexdigest()[:16]


def _human_size(n: int) -> str:
    """字节数转人类可读（B/KB/MB/GB/TB）。"""
    f = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if f < 1024 or unit == "TB":
            return "%d%s" % (int(f), unit) if unit == "B" else "%.1f%s" % (f, unit)
        f /= 1024.0
    return "%.1fTB" % f


def _estimate_size(path: str) -> tuple[int, int]:
    """有界估算体积与文件数（目录递归，超阈值即停）。返回 (bytes, file_count)。"""
    if os.path.isfile(path) or os.path.islink(path):
        try:
            return os.path.getsize(path), 1
        except OSError:
            return 0, 1
    total = 0
    count = 0
    try:
        for root, _dirs, files in os.walk(path):
            for fn in files:
                if count >= VAULT_MAX_FILES:
                    return total, count
                fp = os.path.join(root, fn)
                try:
                    total += os.path.getsize(fp)
                except OSError as exc:
                    _LOGGER.debug("获取文件大小失败: %s", exc)
                count += 1
                if total >= VAULT_MAX_BYTES:
                    return total, count
    except OSError as exc:
        _LOGGER.debug("遍历目录失败: %s", exc)
    return total, count


def _build_vault_meta(src: str, dest: str, root: str, basename: str,
                      is_dir: bool, size: int, orig_mtime: str, now: datetime) -> dict:
    """构造保险库条目元数据（含稳定 id 与删除时间）。"""
    return {
        "id": _entry_id(src, dest),
        "original_path": src,
        "original_name": basename,
        "vault_rel": os.path.relpath(dest, root),
        "vault_abs": dest,
        "is_dir": is_dir,
        "size_bytes": int(size),
        "size_human": _human_size(int(size)),
        "deleted_at": now.isoformat(timespec="milliseconds"),
        "original_mtime": orig_mtime,
    }


def archive_before_delete(src_path: str) -> dict | None:
    """删除前归档一份副本到保险库。返回元数据 dict（失败返回 None，绝不抛异常）。

    - 文件名格式：{删除时间戳}__{原文件名}，带毫秒保证同文件多次删除互不覆盖。
    - 按日期分子目录：VAULT_ROOT/YYYY-MM-DD/...，便于翻找。
    - 同时写入 .meta.json 记录原始路径等元数据。
    """
    try:
        src = str(src_path)
        if not os.path.exists(src) and not os.path.islink(src):
            return None
        is_dir = os.path.isdir(src) and not os.path.islink(src)
        size, fcount = _estimate_size(src)
        if size > VAULT_MAX_BYTES or fcount > VAULT_MAX_FILES:
            return None  # 过大：跳过归档，回收站兜底

        now = datetime.now()
        # 时间戳不含冒号（Windows 文件名禁用），带毫秒。
        stamp = now.strftime("%Y%m%dT%H%M%S") + ("_%03d" % (now.microsecond // 1000))
        basename = os.path.basename(src.rstrip("/\\")) or "unnamed"
        dest_name = "%s__%s" % (stamp, basename)

        root = resolve_vault_root()
        date_dir = os.path.join(root, now.strftime("%Y-%m-%d"))
        os.makedirs(date_dir, exist_ok=True)
        dest = os.path.join(date_dir, dest_name)
        # 极端同名去重（同一毫秒删两个同名文件）
        while os.path.exists(dest) or os.path.exists(dest + ".meta.json"):
            dest += "_"

        if is_dir:
            shutil.copytree(src, dest, symlinks=False, ignore_dangling_symlinks=True)
        else:
            shutil.copy2(src, dest)  # copy2 保留原 mtime

        try:
            orig_mtime = datetime.fromtimestamp(
                os.stat(src).st_mtime
            ).isoformat(timespec="seconds")
        except OSError:
            orig_mtime = ""

        meta = _build_vault_meta(src, dest, root, basename, is_dir, size, orig_mtime, now)
        with open(dest + ".meta.json", "w", encoding="utf-8") as fh:
            json.dump(meta, fh, ensure_ascii=False, indent=2)
        return meta
    except Exception:
        return None


def list_vault() -> list[dict]:
    """列出全部保险库条目（按删除时间倒序）。"""
    root = resolve_vault_root()
    entries: list[dict] = []
    if not os.path.isdir(root):
        return entries
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            if not fn.endswith(".meta.json"):
                continue
            try:
                with open(os.path.join(dirpath, fn), encoding="utf-8") as fh:
                    entries.append(json.load(fh))
            except (OSError, ValueError):
                continue
    entries.sort(key=lambda e: e.get("deleted_at", ""), reverse=True)
    return entries


def get_vault_entry(entry_id: str) -> dict | None:
    """按 id 取单条保险库元数据。"""
    for entry in list_vault():
        if entry.get("id") == entry_id:
            return entry
    return None


def get_vault_stats() -> dict:
    """保险库统计：条目数、总体积、最新/最旧删除时间。"""
    entries = list_vault()
    total = sum(int(e.get("size_bytes", 0)) for e in entries)
    return {
        "count": len(entries),
        "total_bytes": int(total),
        "total_human": _human_size(int(total)),
        "newest": entries[0].get("deleted_at") if entries else None,
        "oldest": entries[-1].get("deleted_at") if entries else None,
    }


def restore_from_vault(entry_id: str, dest: str | None = None, overwrite: bool = False) -> dict:
    """从保险库恢复某条目到原始路径（或指定 dest）。返回 {ok, restored_to, error}。

    - 目标已存在且未要求覆盖：自动改名为 <目标>.restored-<短戳>，绝不静默覆盖用户当前文件。
    - 目录恢复同理（overwrite=True 时先删目标目录再拷回）。
    """
    entry = get_vault_entry(entry_id)
    if entry is None:
        return {"ok": False, "error": "未找到该保险库条目（可能已被清理）"}
    src = entry.get("vault_abs")
    if not src or not os.path.exists(src):
        return {"ok": False, "error": "保险库副本不存在（可能已被清理）"}

    target = dest or entry.get("original_path")
    if not target:
        return {"ok": False, "error": "缺少恢复目标路径"}
    target = str(target)

    if entry.get("is_dir"):
        if os.path.exists(target):
            if overwrite:
                shutil.rmtree(target)
            else:
                target = target.rstrip("/\\") + ".restored-" + datetime.now().strftime("%H%M%S")
        shutil.copytree(src, target)
    else:
        if os.path.exists(target) and not overwrite:
            target = target + ".restored-" + datetime.now().strftime("%H%M%S")
        shutil.copy2(src, target)
    return {"ok": True, "restored_to": target, "original_path": entry.get("original_path")}


def delete_vault_entry(entry_id: str) -> dict:
    """删除单条保险库副本（含元数据）。返回 {ok, removed}。"""
    entry = get_vault_entry(entry_id)
    if entry is None:
        return {"ok": False, "error": "未找到"}
    removed = 0
    for p in (entry.get("vault_abs"), entry.get("vault_abs") + ".meta.json"):
        if p and os.path.exists(p):
            try:
                if os.path.isdir(p):
                    shutil.rmtree(p)
                else:
                    os.remove(p)
                removed += 1
            except OSError as exc:
                _LOGGER.debug("删除保险库条目失败: %s", exc)
    return {"ok": True, "removed": removed}


def clear_vault() -> dict:
    """清空整个保险库（危险操作，UI 需二次确认）。返回 {ok, removed}。"""
    root = resolve_vault_root()
    if not os.path.isdir(root):
        return {"ok": True, "removed": 0}
    removed = 0
    for dirpath, dirs, files in os.walk(root):
        for fn in files + dirs:
            p = os.path.join(dirpath, fn)
            try:
                if os.path.isdir(p):
                    shutil.rmtree(p)
                else:
                    os.remove(p)
                removed += 1
            except OSError as exc:
                _LOGGER.debug("清空保险库条目失败: %s", exc)
    return {"ok": True, "removed": removed}

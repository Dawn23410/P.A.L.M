"""私有文件落盘助手：把「只有本用户能读」收敛到一处。

为什么单独成模块：密钥文件、密钥库、解出的明文都必须以最小权限落盘，而
"最小权限"在 POSIX 与 Windows 上是两套机制——散落在各处就会漏（本模块正是
把原先三处"默认权限落盘"的漏洞统一修掉）。

- POSIX：建文件时给 0o600/0o700，再用 `os.chmod` 兜底（chmod 是**系统调用**，微秒级）；
- Windows：权限来自父目录 ACL，`chmod` 只能切"只读"位，故用 `icacls` 切断继承、
  只授权当前用户。`icacls` 是**子进程**，实测每次 ≈15–22ms——不加处理它会主导整个
  写路径（1KB 写 0.13ms → 14.73ms、1MB 加密里占 64%）。

性能不是靠"少收紧"换来的，而是靠**不重复收紧同一个对象**：

- **目录**：`harden_dir_once()` 收紧一次，并给子项**继承位** `(OI)(CI)`；此后在同一
  自管目录里新建的文件天然继承这套受限 ACL，不必再逐个调 icacls。
- **文件**：进程内记「该路径已收紧」。缓存只在**确知文件对象没被换掉**时才复用——
  新建（`O_EXCL` 成功）的文件若不在自管目录内，**一律重新收紧**，杜绝
  "文件被外部删掉重建 → 缓存说已收紧 → 实际裸奔"。
- ⚠️ **绝不用目录级去收紧调用方给的任意目录**（如解密输出所在的桌面目录）：
  `/inheritance:r` 会清掉该目录原有的继承 ACE，属于越权副作用。目录级只用于
  `ensure_dir()` / 自管数据目录。

收紧是 **best-effort**：失败不抛错，但**如实返回 False**，且失败**不写缓存**
（下次仍会重试）。调用方必须如实对待返回值：False 表示"权限收紧没生效，实际保护
只取决于父目录 ACL"，不能当成成功。安全模块里，"以为收紧了"比"没收紧"更危险。
"""
from __future__ import annotations

import os
import subprocess
import threading

_MODE_FILE = 0o600
_MODE_DIR = 0o700
_ACL_TIMEOUT = 10
_CACHE_LIMIT = 8192          # 缓存条数上限；超了整体清空（只损失性能，不影响安全）

_LOCK = threading.RLock()
_MANAGED_DIRS: set[str] = set()      # 已确认收紧的自管目录（子项继承其 ACL）
# 文件 → 收紧时的**文件身份**（st_dev, st_ino）。存身份而非布尔：外部删除后重建
# 会拿到新身份 ⇒ 缓存自动失效，杜绝"缓存说已收紧、实际已换文件"的裸奔。
_HARDENED_FILES: dict[str, tuple[int, int]] = {}


def _posix_chmod(path: str, mode: int) -> bool:
    try:
        os.chmod(path, mode)
        return True
    except OSError:
        return False


def _windows_acl(path: str, inherit_children: bool = False) -> bool:
    """切断继承并只授权当前用户（icacls /inheritance:r /grant:r）。

    `inherit_children=True` 追加 `(OI)(CI)`（对象继承/容器继承），让**此后新建的
    子文件与子目录**直接继承这套受限 ACL —— 这是"每目录一次"取代"每文件一次"的关键。
    """
    user = os.environ.get("USERNAME") or os.environ.get("USER")
    if not user:
        return False
    grant = f"{user}:(OI)(CI)F" if inherit_children else f"{user}:(F)"
    try:
        proc = subprocess.run(
            ["icacls", os.path.abspath(path), "/inheritance:r", "/grant:r", grant],
            capture_output=True, timeout=_ACL_TIMEOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return proc.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def restrict(path: str, mode: int, inherit_children: bool | None = None) -> bool:
    """把已存在的路径权限收紧到 mode；返回是否**确实**收紧。

    **不走缓存**：显式调用即"现在就去做"，重复调用会重复执行（供审计与历史修复）。
    日常写路径请用 `harden_dir_once` / `harden_file_once`。
    """
    if os.name == "posix":
        return _posix_chmod(path, mode)
    if inherit_children is None:
        inherit_children = os.path.isdir(path)
    return _windows_acl(path, inherit_children=inherit_children)


def restrict_dir(path: str, mode: int = _MODE_DIR) -> bool:
    """收紧目录权限（默认 0o700；Windows 带子项继承位）。"""
    return restrict(path, mode, inherit_children=True)


def restrict_file(path: str, mode: int = _MODE_FILE) -> bool:
    """收紧文件权限（默认 0o600；Windows 不给子项继承位）。"""
    return restrict(path, mode, inherit_children=False)


def restrict_if_exists(path: str, mode: int = _MODE_FILE) -> bool:
    """路径存在才收紧（不存在视为"无事可做"，返回 True）。"""
    if not os.path.exists(path):
        return True
    return restrict(path, mode)


def _remember_dir(key: str) -> None:
    if len(_MANAGED_DIRS) >= _CACHE_LIMIT:
        _MANAGED_DIRS.clear()
    _MANAGED_DIRS.add(key)


def _remember_file(key: str, fid: tuple[int, int] | None) -> None:
    if fid is None:
        return
    if len(_HARDENED_FILES) >= _CACHE_LIMIT:
        _HARDENED_FILES.clear()
    _HARDENED_FILES[key] = fid


def _file_id(path: str) -> tuple[int, int] | None:
    """取文件身份（st_dev, st_ino）。取不到（不存在/无权限）返回 None —— 视为不可缓存。"""
    try:
        st = os.stat(path)
        return (st.st_dev, st.st_ino)
    except OSError:
        return None


def harden_dir_once(path: str, mode: int = _MODE_DIR) -> bool:
    """目录级一次性收紧（Windows 带继承位）；成功即进程内永久免重复。

    ⚠️ 只用于**本模块自管的目录**（密钥库 `.keys/`、数据目录）。不要拿它去收紧
    调用方给的任意目录——那会清掉该目录原有继承 ACE。
    """
    key = os.path.abspath(path)
    with _LOCK:
        if key in _MANAGED_DIRS:
            return True
        ok = restrict_dir(path, mode)
        if ok:
            _remember_dir(key)
        return ok


def harden_file_once(path: str, mode: int = _MODE_FILE) -> bool:
    """文件级一次性收紧（带缓存）；文件不存在视为"无事可做"，返回 True。"""
    if not os.path.exists(path):
        return True
    key = os.path.abspath(path)
    with _LOCK:
        fid = _file_id(key)
        if fid is not None and _HARDENED_FILES.get(key) == fid:
            return True
        ok = restrict_file(path, mode)
        if ok:
            _remember_file(key, fid)
        return ok


def ensure_dir(path: str, mode: int = _MODE_DIR) -> bool:
    """按需创建目录并收紧权限（登记为自管目录，子项从此继承）；返回是否确实收紧。"""
    os.makedirs(path, exist_ok=True)
    return harden_dir_once(path, mode)


def _open_for_write(path: str, mode: int) -> tuple[int, bool]:
    """打开写入句柄，并如实告知是**新建**还是覆盖（只有新建才谈得上"继承目录 ACL"）。"""
    base = os.O_WRONLY | os.O_CREAT
    try:
        return os.open(path, base | os.O_EXCL, mode), True
    except FileExistsError:
        return os.open(path, base | os.O_TRUNC, mode), False


def _protect_after_write(path: str, created: bool, mode: int) -> bool:
    """写完之后的权限收敛（热路径：缓存判断都在这里，命中即零子进程）。"""
    if os.name == "posix":
        return _posix_chmod(path, mode)
    key = os.path.abspath(path)
    fid = _file_id(key)
    with _LOCK:
        # 新建且落在自管目录里 → 已继承该目录的受限 ACL，无需再动它
        if created and os.path.dirname(key) in _MANAGED_DIRS:
            _remember_file(key, fid)
            return True
        # 同一文件对象、且此前确认过收紧 → 覆盖写不会改动它的 ACL
        if fid is not None and _HARDENED_FILES.get(key) == fid:
            return True
        ok = restrict_file(path, mode)
        if ok:
            _remember_file(key, fid)
        return ok


def write_private_bytes(path: str, data: bytes, mode: int = _MODE_FILE) -> bool:
    """以最小权限建文件并写入（已存在则截断重写）。返回是否确实收紧。"""
    fd, created = _open_for_write(path, mode)
    try:
        handle = os.fdopen(fd, "wb")
    except Exception:
        os.close(fd)
        raise
    with handle:
        handle.write(data)
    return _protect_after_write(path, created, mode)


def write_private_text(path: str, text: str, mode: int = _MODE_FILE) -> bool:
    """`write_private_bytes` 的文本版（UTF-8）。"""
    return write_private_bytes(path, text.encode("utf-8"), mode)


def harden_cache_stats() -> dict:
    """缓存状态（供审计/基准证伪"缓存是否真的生效"；不参与判定安全）。"""
    with _LOCK:
        return {"dirs": len(_MANAGED_DIRS), "files": len(_HARDENED_FILES)}


def reset_harden_cache() -> None:
    """清空进程内缓存（仅供测试：模拟"全新进程"或强制重收紧）。"""
    with _LOCK:
        _MANAGED_DIRS.clear()
        _HARDENED_FILES.clear()


__all__ = ["restrict", "restrict_dir", "restrict_file", "restrict_if_exists",
           "harden_dir_once", "harden_file_once",
           "ensure_dir", "write_private_bytes", "write_private_text",
           "harden_cache_stats", "reset_harden_cache"]

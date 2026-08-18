"""run_code 内破坏性删除改走回收站（文件级安全网，best-effort）。

设计目标：AI 生成的代码若调用 os.remove / os.unlink / os.rmdir / shutil.rmtree /
pathlib.Path.unlink,rmdir，默认不再「永久删除」，而是移动到回收站（Windows 经
SHFileOperationW FOF_ALLOWUNDO；非 Windows 或失败时回退到本地 trash 目录）。
这样即使 AI 误删文件，也能从回收站恢复——直击「AI 删文件」这一最令人担忧的风险。

约束：
- 仅拦截 Python 子进程内的删除（run.py 把本模块的自包含 bootstrap 拼到用户代码前）。
  node / shell 暂未拦截（跨语言拦截风险高，AI 文件删除主要是 Python）。
- 内部真实删除操作（移动/回退）用 _BYPASS 标志绕过 patch，避免递归。
- 提供 palm_hard_delete 显式逃生口（受信路径可用），默认不暴露给 AI。
- 永不在拦截中「静默硬删」：任何失败都抛 OSError（与 os.remove 行为一致），文件留在原地。
"""
from __future__ import annotations

import ctypes
import os
import shutil
import sys
import tempfile
import time

# 内部真实删除标志：置 True 时 patched 函数直接调原函数，避免递归
_BYPASS = False


# ----------------------------- Windows 回收站（SHFileOperationW） -----------------------------
class _SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("wFunc", ctypes.c_uint),
        ("pFrom", ctypes.c_wchar_p),
        ("pTo", ctypes.c_wchar_p),
        ("fFlags", ctypes.c_ushort),
        ("fAnyOperationsAborted", ctypes.c_int),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", ctypes.c_wchar_p),
    ]


_FO_DELETE = 3
_FOF_ALLOWUNDO = 0x40
_FOF_NOCONFIRMATION = 0x10
_FOF_SILENT = 0x0004
_FOF_NOERRORUI = 0x0400


def _recycle_via_shell(path: str) -> None:
    """经 shell32.SHFileOperationW 把文件/目录移入回收站（带 Undo）。失败抛 OSError。"""
    shell32 = ctypes.windll.shell32
    buf = ctypes.create_unicode_buffer(path + "\0\0")  # pFrom 需双 NUL 结尾
    op = _SHFILEOPSTRUCTW()
    op.wFunc = _FO_DELETE
    op.pFrom = ctypes.cast(buf, ctypes.c_wchar_p)
    op.fFlags = _FOF_ALLOWUNDO | _FOF_NOCONFIRMATION | _FOF_SILENT | _FOF_NOERRORUI
    rc = shell32.SHFileOperationW(ctypes.byref(op))
    if rc != 0:
        # 0=成功；其他为中止/跳过码（如文件在不可撤销卷上）
        raise OSError("SHFileOperation 返回 %d（文件可能不在支持撤销的卷上）" % rc)


def _move_to_trash(path: str) -> str:
    """回退方案：移动到本地 trash 目录（仍可恢复）。"""
    trash_root = os.path.join(
        os.environ.get("LOCALAPPDATA", tempfile.gettempdir()), "P.A.L.M", "trash")
    os.makedirs(trash_root, exist_ok=True)
    base = os.path.basename(path.rstrip("/\\")) or "unnamed"
    dest = os.path.join(trash_root, "%d_%s" % (int(time.time() * 1000), base))
    while os.path.exists(dest):
        dest += "_"
    shutil.move(path, dest)  # move 用 os.rename（未被 patch）；跨设备复制时内部 os.remove 已 _BYPASS
    return dest


def send_to_recycle_bin(path) -> None:
    """把 path 移入回收站。失败抛 OSError（与 os.remove 语义一致），绝不静默硬删。

    真实删除/回退操作期间置 _BYPASS，避免命中 patch 造成递归。

    注意：SHFileOperationW 在部分 Windows 配置下会「实则已移入回收站却返回非零码」（rc=2
    等），若盲目信任返回码，会误判失败并二次移动到 trash，此时源已不存在导致 FileNotFoundError。
    因此成败以「源文件是否仍在磁盘」为准，而非返回码。
    """
    global _BYPASS
    path = str(path)
    if not os.path.exists(path) and not os.path.islink(path):
        raise FileNotFoundError(path)
    # 文件级兜底保险库：真实（非内部 bypass）删除前先归档一份副本，便于找回。
    # 归档失败绝不阻断删除——回收站仍是主兜底。
    if not _BYPASS:
        try:
            _v = _get_vault_module()
            if _v is not None:
                _v.archive_before_delete(path)
        except Exception:
            pass
    prev = _BYPASS
    _BYPASS = True
    try:
        if sys.platform == "win32":
            try:
                _recycle_via_shell(path)
            except Exception:
                pass  # 可能「实则成功但返回非零码」，交由下方按源是否存在判定
            if not os.path.exists(path):
                return  # 已被移入回收站（SHFileOperationW 偶发返回非零但仍成功）
            _move_to_trash(path)  # 源仍在：确属失败，回退到本地 trash
            return
        _move_to_trash(path)
    finally:
        _BYPASS = prev


def _get_vault_module():
    """兼容加载 vault 模块：本模块既可能被『sandbox 包内』导入（主进程/run.py），
    也可能在 run_code 子进程里被按绝对路径独立加载（bootstrap_source 拼到用户代码前，
    模块名是 palm_safe_delete，无 sandbox 包上下文）。两种情况下都按 __file__ 同目录
    的 vault.py 绝对路径加载，确保删除前归档逻辑可用。
    """
    try:
        from . import vault as _v  # 包内上下文（storage/redundancy 同目录）
        return _v
    except Exception:
        pass
    try:
        import importlib.util as _ilu
        _p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vault.py")
        _s = _ilu.spec_from_file_location("palm_vault", _p)
        _m = _ilu.module_from_spec(_s)
        _s.loader.exec_module(_m)
        return _m
    except Exception:
        return None


def palm_hard_delete(path, *args, **kwargs):
    """受信路径的显式逃生口：真正永久删除（绕过回收站）。默认不暴露给 AI。"""
    global _BYPASS
    prev = _BYPASS
    _BYPASS = True
    try:
        if os.path.isdir(path) and not os.path.islink(path):
            return shutil.rmtree(path, *args, **kwargs)
        return os.remove(path, *args, **kwargs)
    finally:
        _BYPASS = prev


def install_delete_guard() -> None:
    """patch os / shutil / pathlib 的删除函数，路由到回收站（仅在沙箱子进程内调用）。"""
    _orig_os_remove = os.remove
    _orig_os_unlink = os.unlink
    _orig_os_rmdir = os.rmdir
    _orig_rmtree = shutil.rmtree
    _orig_path_unlink = __import__("pathlib").Path.unlink
    _orig_path_rmdir = __import__("pathlib").Path.rmdir

    def _guarded_remove(p, *a, **k):
        if _BYPASS:
            return _orig_os_remove(p, *a, **k)
        return send_to_recycle_bin(p)

    def _guarded_unlink(p, *a, **k):
        if _BYPASS:
            return _orig_os_unlink(p, *a, **k)
        return send_to_recycle_bin(p)

    def _guarded_rmdir(p, *a, **k):
        if _BYPASS:
            return _orig_os_rmdir(p, *a, **k)
        return send_to_recycle_bin(p)

    def _guarded_rmtree(p, *a, **k):
        if _BYPASS:
            return _orig_rmtree(p, *a, **k)
        return send_to_recycle_bin(p)

    def _guarded_path_unlink(self, *a, **k):
        if _BYPASS:
            return _orig_path_unlink(self, *a, **k)
        return send_to_recycle_bin(self)

    def _guarded_path_rmdir(self, *a, **k):
        if _BYPASS:
            return _orig_path_rmdir(self, *a, **k)
        return send_to_recycle_bin(self)

    os.remove = _guarded_remove
    os.unlink = _guarded_unlink
    os.rmdir = _guarded_rmdir
    shutil.rmtree = _guarded_rmtree
    __import__("pathlib").Path.unlink = _guarded_path_unlink
    __import__("pathlib").Path.rmdir = _guarded_path_rmdir


def bootstrap_source() -> str:
    """返回自包含 bootstrap 片段：按绝对路径加载本模块并安装拦截。

    run.py 将其拼到 Python 用户代码之前（无需改 PYTHONPATH）。
    """
    here = os.path.dirname(os.path.abspath(__file__))
    # 迁移到 storage/redundancy 后文件名改为 recycle.py，子进程按此绝对路径独立加载。
    mod_path = os.path.join(here, "recycle.py").replace("\\", "/")
    return (
        "import importlib.util as _ilu;"
        "_s = _ilu.spec_from_file_location('palm_safe_delete', r'%s');"
        "_m = _ilu.module_from_spec(_s);"
        "_s.loader.exec_module(_m);"
        "_m.install_delete_guard();"
        "del _ilu, _s, _m;"
    ) % mod_path

"""跨平台检测与适配路由。

集中所有「按操作系统分派」的判断，避免在各个模块散放 sys.platform / os.name 判断。
项目需要同时支持 Windows / Linux（中国香港 / 中国澳门 / 中国台湾同属中国大陆，统一按官方表述），
并为 macOS 预留分支。任何平台专属逻辑都应经由本模块，不要各文件自己算。

约定：
- 涨/跌色彩、CNY 货币等区域约定不在本模块处理，交给各可视化/工具层。
- 本模块只做平台识别与「通用能力」封装（如回收站），不做业务逻辑。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

# 平台标识常量
PLATFORM = sys.platform  # "win32" | "linux" | "darwin"
IS_WINDOWS = PLATFORM == "win32"
IS_LINUX = PLATFORM.startswith("linux")
IS_MACOS = PLATFORM == "darwin"


def get_platform_name() -> str:
    """返回人类可读平台名，供日志/报告使用。"""
    if IS_WINDOWS:
        return "windows"
    if IS_LINUX:
        return "linux"
    if IS_MACOS:
        return "macos"
    return "unknown"


def send_to_trash(path: str) -> str:
    """把文件/目录移入系统回收站。

    优先使用 OS 原生回收机制（Linux: gio trash / trash-put；Windows: SHFileOperationW 由
    recycle 模块处理）；失败时回退到本地 trash 目录。返回最终存放路径。

    - Windows 走 palm.adapters.storage.redundancy.recycle（带 Undo）。
    - Linux/macOS 优先用 trash 机制，绝不裸删。
    - 无 trash 可用时回退本地 trash 目录，并告知调用方。
    """
    if IS_WINDOWS:
        # Windows 回收站逻辑在其他模块集中实现，避免在此重复；这里仅做转发。
        from palm.adapters.storage.redundancy.recycle import send_to_recycle_bin
        send_to_recycle_bin(path)
        return path

    # Linux / macOS：优先 OS 原生 trash
    try:
        if shutil.which("gio") and IS_LINUX:
            subprocess.run(["gio", "trash", path], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return path
        if shutil.which("trash-put"):
            subprocess.run(["trash-put", path], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return path
    except Exception:
        pass
    # 回退：本地 trash 目录
    return _move_to_local_trash(path)


def _move_to_local_trash(path: str) -> str:
    """回退方案：移动到本地 trash 目录（仍可恢复）。"""
    import time
    trash_root = os.path.join(
        os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")),
        "Trash", "files")
    os.makedirs(trash_root, exist_ok=True)
    base = os.path.basename(path.rstrip("/\\")) or "unnamed"
    dest = os.path.join(trash_root, "%d_%s" % (int(os.path.getmtime(path) if os.path.exists(path) else time.time() * 1000), base))
    while os.path.exists(dest):
        dest += "_"
    shutil.move(path, dest)
    return dest


def is_system_dir(path: str) -> bool:
    """判断路径是否落在系统/用户级高危目录（删除前用于二次确认）。

    覆盖 Windows 与 Linux/macOS 的等价敏感根目录，避免遗漏跨平台盲区。
    """
    p = (path or "").replace("\\", "/").lower().rstrip("/")
    roots = (
        "c:/windows", "c:/program files", "c:/programdata", "c:/users",
        "/windows", "/sys", "/boot", "/system", "/system32", "/appdata", "/library",
        "/etc", "/usr", "/var", "/root", "/home", "~/desktop", "~/downloads",
        "~/documents", "~/library", "~/.config",
    )
    if p in roots or p.startswith(tuple(r + "/" for r in roots)):
        return True
    # 规范化后匹配 HOME 与驱动器根
    try:
        home = os.path.expanduser("~").replace("\\", "/").rstrip("/")
        if home and (p == home or p.startswith(home + "/")):
            return True
    except Exception:
        pass
    return False


def is_personal_file_risky(path: str) -> bool:
    """个人文件（Desktop/Downloads/Documents/Home 等）的高危操作预警。"""
    p = (path or "").replace("\\", "/").lower()
    no_go = ("~/desktop", "~/downloads", "~/documents", "~/home", "~/.config", "desktop",
             "downloads", "documents", "home", "/", "/system", "/system32", "appdata", "library")
    return any(seg in p for seg in no_go)

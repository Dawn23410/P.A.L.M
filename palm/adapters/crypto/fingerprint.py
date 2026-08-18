"""本机硬件指纹采集。

仅以主板标识作为硬件绑定要素：主板/系统标识确定、跨进程一致。
无法获取时抛 RuntimeError，防止密钥弱化。
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys

if sys.platform.startswith("win"):
    import winreg


def _read_windows_board() -> str | None:
    """Windows 主板标识：直接从 BIOS 注册表读取。

    wmic 在 Win11 已弃用且在子进程环境常失败，注册表值跨进程一致、确定。
    """
    if not sys.platform.startswith("win"):
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\BIOS") as k:
            v, _ = winreg.QueryValueEx(k, "SystemManufacturer")
            p, _ = winreg.QueryValueEx(k, "SystemProductName")
            if v and p:
                return f"{v}_{p}".replace(" ", "_")
    except Exception:
        pass
    return None


def _get_board_serial() -> str:
    """主板/系统标识，多层级回退。"""
    windows_serial = _read_windows_board()
    if windows_serial:
        return windows_serial

    # Linux dmidecode / sysfs
    try:
        out = subprocess.check_output(
            ["dmidecode", "-s", "baseboard-serial-number"],
            stderr=subprocess.DEVNULL, text=True, timeout=5,
        )
        serial = out.strip()
        if serial:
            return serial
    except Exception:
        pass
    board_file = "/sys/class/dmi/id/board_serial"
    if os.path.exists(board_file):
        with open(board_file) as f:
            serial = f.read().strip()
            if serial:
                return serial

    raise RuntimeError("无法获取主板序列号，请检查权限或硬件支持。")


def get_machine_fingerprint() -> str:
    """采集本机唯一硬件指纹，返回 SHA256 hex 摘要。

    仅基于主板标识，跨进程/启动方式确定一致。
    """
    serial = _get_board_serial()
    return hashlib.sha256(serial.encode("utf-8")).hexdigest()

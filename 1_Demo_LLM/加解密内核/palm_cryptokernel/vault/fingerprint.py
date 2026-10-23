"""本机硬件指纹采集（自 P.A.L.M `palm/adapters/crypto` 收敛而来）。

设计取舍（WHY）：指纹要同时满足两件事——
- **稳定**：跨进程、跨重启一致，否则密钥库自己都打不开；
- **唯一**：同型号的另一台机器不该算出同一指纹，否则把密钥库文件拷走就能离线解封。

原实现只用 BIOS 的「厂商_型号」——那是**型号级**标识：同型号机器的指纹完全相同，
与"仅本机可自动解封"的承诺不符。现按"唯一性从高到低"取**第一个**可用标识，并把
用了哪一级如实报出来（`fingerprint_strength()`）：

  1. 每套系统唯一：Windows MachineGuid / Linux /etc/machine-id、product_uuid
  2. 每台整机唯一：BIOS SerialNumber、主板序列号
  3. 仅同型号唯一（弱，兜底）：厂商_型号 —— 会被标为 `model-only` 并被日志告警

代价要说清：用系统级标识意味着**重装系统后指纹变化**，密钥库需用恢复密钥重新导入；
这是"更强隔离"换"更少便利"，本模块选前者，因为恢复密钥路径本来就有。
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys

if sys.platform.startswith("win"):
    import winreg

_WIN_BIOS = r"HARDWARE\DESCRIPTION\System\BIOS"
_WIN_CRYPTO = r"SOFTWARE\Microsoft\Cryptography"

_strength: str = "unknown"
_sources: tuple[str, ...] = ()


def fingerprint_strength() -> str:
    """上次采集所用标识的强度：`per-unit`（每台唯一）/ `model-only`（仅型号唯一）。"""
    return _strength


def fingerprint_sources() -> tuple[str, ...]:
    """上次采集到的全部候选来源名（按唯一性排序，供审计引用）。"""
    return _sources


def _win_reg(subkey: str, name: str) -> str | None:
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, subkey) as key:
            value, _ = winreg.QueryValueEx(key, name)
        text = str(value).strip() if value else ""
        return text or None
    except Exception:      # 键不存在/无权限：视为该来源不可用，继续下一个
        return None


def _windows_candidates() -> list[tuple[str, str, bool]]:
    """(来源名, 值, 是否每台唯一)，按唯一性从高到低。"""
    out: list[tuple[str, str, bool]] = []
    guid = _win_reg(_WIN_CRYPTO, "MachineGuid")
    if guid:
        out.append(("machine-guid", guid, True))
    serial = _win_reg(_WIN_BIOS, "SerialNumber")
    if serial:
        out.append(("bios-serial", serial, True))
    maker, model = _win_reg(_WIN_BIOS, "SystemManufacturer"), _win_reg(_WIN_BIOS, "SystemProductName")
    if maker and model:
        out.append(("board-model", f"{maker}_{model}".replace(" ", "_"), False))
    return out


def _linux_candidates() -> list[tuple[str, str, bool]]:
    out: list[tuple[str, str, bool]] = []
    for path, name in (("/etc/machine-id", "machine-id"),
                       ("/sys/class/dmi/id/product_uuid", "product-uuid"),
                       ("/sys/class/dmi/id/board_serial", "board-serial"),
                       ("/sys/class/dmi/id/product_serial", "product-serial")):
        try:
            with open(path) as fh:
                value = fh.read().strip()
        except OSError:
            continue
        if value:
            out.append((name, value, True))
    try:
        text = subprocess.check_output(
            ["dmidecode", "-s", "baseboard-serial-number"],
            stderr=subprocess.DEVNULL, text=True, timeout=5).strip()
        if text:
            out.append(("dmidecode-baseboard-serial", text, True))
    except Exception:
        pass
    try:
        with open("/sys/class/dmi/id/board_name") as fh:
            board = fh.read().strip()
        if board:
            out.append(("board-name", board, False))
    except OSError:
        pass
    return out


def _collect() -> list[tuple[str, str, bool]]:
    return _windows_candidates() if sys.platform.startswith("win") else _linux_candidates()


def get_machine_fingerprint() -> str:
    """采集本机硬件指纹，返回 SHA256 hex 摘要。

    只哈希**唯一性最高的那一个**标识（而非拼接全部），因为拼接会让任一标识变化
    （例如一次 BIOS 升级）都改变指纹、使密钥库失效。取不到任何标识时抛
    RuntimeError，绝不退回弱标识继续绑定。
    """
    global _strength, _sources
    candidates = _collect()
    if not candidates:
        raise RuntimeError("无法获取任何硬件/系统标识，已放弃指纹绑定（不弱化密钥）")
    per_unit = [c for c in candidates if c[2]]
    chosen = per_unit[0] if per_unit else candidates[0]
    _sources = tuple(c[0] for c in candidates)
    _strength = "per-unit" if chosen[2] else "model-only"
    return hashlib.sha256(chosen[1].encode("utf-8")).hexdigest()


__all__ = ["get_machine_fingerprint", "fingerprint_strength", "fingerprint_sources"]

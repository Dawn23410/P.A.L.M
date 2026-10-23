"""文件级加解密操作与路径安全检查（自 P.A.L.M `palm/adapters/crypto` 收敛而来）。"""
from __future__ import annotations

import os
from typing import Optional

from .. import _private_fs
from .operations import decrypt_data, encrypt_data


def _safe_path(path: str) -> str:
    """防路径遍历：拒绝 `..` 穿越，检查文件存在。"""
    norm = os.path.normpath(path)
    if ".." in norm.split(os.sep):
        raise ValueError("路径包含 '..' 是不允许的")
    abs_path = os.path.abspath(norm)
    if not os.path.exists(abs_path):
        raise FileNotFoundError(f"文件不存在: {abs_path}")
    return abs_path


def _safe_output(path: str) -> str:
    """输出路径安全检查：拒绝 `..` 穿越（目录不自动创建，缺失由 open 报错）。"""
    norm = os.path.normpath(path)
    if ".." in norm.split(os.sep):
        raise ValueError("输出路径包含 '..' 是不允许的")
    return os.path.abspath(norm)


def encrypt_file(file_path: str) -> str:
    """读取文件 → 加密 → 写出 .enc 文件（0600），返回路径。"""
    plain = _read_file(file_path)
    encrypted = encrypt_data(plain)
    enc_path = file_path + ".enc"
    _private_fs.write_private_bytes(enc_path, encrypted)
    return enc_path


def decrypt_file(
    enc_path: str, output_path: Optional[str] = None
) -> str:
    """读取 .enc → 解密 → 写出明文件（0600），返回路径。

    ⚠️ 落盘的是**明文**：权限收紧到仅本用户，但仍建议用完即删或置于受控目录。
    """
    pkg = _read_file(enc_path)
    plain = decrypt_data(pkg)
    if output_path is None:
        base = enc_path[:-4] if enc_path.endswith(".enc") else enc_path
        output_path = base + "_decrypted"
    target = _safe_output(output_path)
    _private_fs.write_private_bytes(target, plain)
    return target


def _read_file(path: str) -> bytes:
    """安全读取文件（包装异常）。"""
    safe = _safe_path(path)
    if os.path.isdir(safe):
        raise ValueError("路径指向目录，请指定文件")
    with open(safe, "rb") as f:
        return f.read()

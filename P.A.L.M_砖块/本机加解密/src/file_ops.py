"""文件级加解密操作与路径安全检查。"""
from __future__ import annotations

import os
from typing import Optional

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


def encrypt_file(file_path: str) -> str:
    """读取文件 → 加密 → 写出 .enc 文件，返回路径。"""
    plain = _read_file(file_path)
    encrypted = encrypt_data(plain)
    enc_path = file_path + ".enc"
    with open(enc_path, "wb") as f:
        f.write(encrypted)
    return enc_path


def decrypt_file(
    enc_path: str, output_path: Optional[str] = None
) -> str:
    """读取 .enc → 解密 → 写出明文件，返回路径。"""
    pkg = _read_file(enc_path)
    plain = decrypt_data(pkg)
    if output_path is None:
        base = enc_path[:-4] if enc_path.endswith(".enc") else enc_path
        output_path = base + "_decrypted"
    with open(output_path, "wb") as f:
        f.write(plain)
    return output_path


def _read_file(path: str) -> bytes:
    """安全读取文件（包装异常）。"""
    safe = _safe_path(path)
    if os.path.isdir(safe):
        raise ValueError("路径指向目录，请指定文件")
    with open(safe, "rb") as f:
        return f.read()

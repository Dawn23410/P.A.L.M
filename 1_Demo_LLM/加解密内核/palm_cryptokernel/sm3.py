"""国密 SM3 密码哈希函数（256 位，安全性对标 SHA-256）。

用于：内容指纹（稳定去重）、完整性校验标签。
底层经 backends：C 实现（tongsuopy/铜锁）优先、纯 Python gmssl 保底，
摘要值两后端逐位一致（已互操作验证），换后端不影响既有指纹。
"""
from __future__ import annotations

from typing import Union

from . import backends

BytesLike = Union[bytes, str]


def _to_bytes(data: BytesLike) -> bytes:
    return data.encode("utf-8") if isinstance(data, str) else data


def sm3_hash(data: BytesLike) -> str:
    """返回 SM3 十六进制摘要（64 字符 / 256 位）。"""
    return backends.sm3(_to_bytes(data)).hex()


def sm3_int(data: BytesLike) -> int:
    """SM3 摘要的整数形式（256 位），用于需要数值指纹的场景。"""
    return int.from_bytes(backends.sm3(_to_bytes(data)), "big")

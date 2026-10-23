"""族模块共用的小工具：str/bytes 归一、nonce/key 生成、长度断言。

WHY 集中一处：算法实现一律吃 bytes，但上层（记忆层、砖块、配置、UI）大量用 str。
若把归一散落到 9 个族模块，编码约定必然漂移；集中定义后，全内核语义一致，
且"nonce 该多长"只由算法自身的属性说了算，不靠调用方记忆。
"""
from __future__ import annotations

import os
from typing import Any, Union

BytesLike = Union[bytes, bytearray, memoryview, str]

TEXT_ENCODING = "utf-8"


def as_bytes(value: BytesLike, *, field: str = "数据") -> bytes:
    """把 str 按 UTF-8 归一为 bytes；其余字节类原样转 bytes。"""
    if isinstance(value, str):
        return value.encode(TEXT_ENCODING)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value)
    raise TypeError(f"{field} 必须是 str 或 bytes，得到 {type(value).__name__}")


def check_length(value: bytes, expected: int, *, field: str) -> None:
    """长度断言：nonce/key 长度是安全边界，不符必须早失败而非静默凑合。"""
    if expected and len(value) != expected:
        from ..errors import KeyFormatError
        raise KeyFormatError(
            f"{field} 长度应为 {expected} 字节，得到 {len(value)} 字节")


def random_nonce(size: int) -> bytes:
    """随机 nonce（CSPRNG）；size=0 表示该模式不需要 nonce，返回空串。"""
    return os.urandom(size) if size else b""


def new_nonce(algo: Any) -> bytes:
    """按算法声明生成 nonce，长度由算法自述，调用方无需记忆。"""
    return random_nonce(int(getattr(algo, "nonce_size", 0) or 0))


def new_key(algo: Any) -> bytes:
    """按算法声明生成随机密钥（取族默认键长）。"""
    size = 0
    key_size = getattr(algo, "key_size", None)
    if callable(key_size):
        size = int(key_size() or 0)
    if not size:
        from ..errors import KeyFormatError
        raise KeyFormatError(f"{algo.name} 未声明密钥长度，无法自动生成")
    return os.urandom(size)


__all__ = ["BytesLike", "TEXT_ENCODING", "as_bytes", "check_length",
           "random_nonce", "new_nonce", "new_key"]

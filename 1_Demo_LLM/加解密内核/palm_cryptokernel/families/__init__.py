"""算法族薄模块：调用方最常用的入口层。

每个模块只做三件事——**str 归一**、**参数校验**、**转交注册表**，
不实现任何密码学逻辑（逻辑在 `providers/*`），也不做算法选择（选择在注册表）。

    族模块                用途                              最低要求
    ────────────────────────────────────────────────────────────────
    hash      摘要 / 短指纹                        任何后端
    mac       消息认证码（常量时间校验）          任何后端
    kdf       口令派生 / 密钥扩展                 任何后端
    cipher    对称加密（**无认证**，慎用）        cryptodome / gmssl
    aead      认证加密（落盘/传输首选）           cryptodome
    pubkey    公钥加密（仅短数据）                 cryptodome / gmssl
    envelope  公钥信封（pubkey + AEAD，发加密数据）cryptodome / gmssl
"""
from __future__ import annotations

from . import (aead, cipher, envelope, hash, kdf, mac, pubkey)

FAMILIES = ("hash", "mac", "kdf", "cipher", "aead", "pubkey")

# 族标识 → 模块（供 CryptoSuite / UI 做通用枚举，避免硬编码 if-else 链）
MODULES = {
    "hash": hash,
    "mac": mac,
    "kdf": kdf,
    "cipher": cipher,
    "aead": aead,
    "pubkey": pubkey,
}

__all__ = [
    "aead", "cipher", "envelope", "hash", "kdf", "mac",
    "pubkey", "FAMILIES", "MODULES",
]

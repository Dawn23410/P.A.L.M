"""对称加密族（**无认证**）：CBC/CTR/CFB/OFB/ECB、ChaCha20、Salsa20、SM4-CBC。

⚠️ 安全提示（WHY 本模块 docstring 必须写这句）：本族**不提供完整性保护**，
密文被篡改无法察觉。用于落盘/传输时，请优先选 `aead` 族；确需本族时，
必须自行叠加 MAC（先加密后 MAC）或改用 `aead`。
"""
from __future__ import annotations

from typing import Optional

from ..registry import registry
from ._util import (BytesLike, as_bytes, check_length, new_key, new_nonce)

FAMILY = "cipher"
DEFAULT = "aes-256-cbc"


def names(*, include_legacy: bool = True) -> list[str]:
    """可用对称算法名；ECB / RC4 / DES 等已标 legacy。"""
    all_names = registry.names(FAMILY)
    if include_legacy:
        return all_names
    return [n for n in all_names if not registry.get(FAMILY, n).legacy]


def nonce_size(name: str) -> int:
    """所需 nonce/IV 长度；0 表示该模式不用（如 ECB）。"""
    return registry.get(FAMILY, name).nonce_size


def key_size(name: str) -> int:
    """族默认密钥长度。"""
    return registry.get(FAMILY, name).key_size()


def generate_key(name: str) -> bytes:
    return new_key(registry.get(FAMILY, name))


def new_iv(name: str) -> bytes:
    """按算法声明生成随机 IV/nonce。"""
    return new_nonce(registry.get(FAMILY, name))


def encrypt(name: str, key: BytesLike, nonce: BytesLike,
            plaintext: BytesLike) -> bytes:
    """加密；返回**纯密文**（不含 IV），填充由 provider 内部统一处理。"""
    algo = registry.get(FAMILY, name)
    n = as_bytes(nonce, field=f"{name} nonce")
    check_length(n, algo.nonce_size, field=f"{name} nonce")
    return algo.encrypt(as_bytes(key, field="密钥"), n, as_bytes(plaintext))


def decrypt(name: str, key: BytesLike, nonce: BytesLike,
            ciphertext: BytesLike) -> bytes:
    """解密；填充非法抛 KeyFormatError。"""
    algo = registry.get(FAMILY, name)
    n = as_bytes(nonce, field=f"{name} nonce")
    check_length(n, algo.nonce_size, field=f"{name} nonce")
    return algo.decrypt(as_bytes(key, field="密钥"), n,
                        as_bytes(ciphertext, field="密文"))


def encrypt_packed(name: str, plaintext: BytesLike,
                   key: Optional[BytesLike] = None) -> bytes:
    """便捷封装：返回 `nonce ‖ 密文` 并自动生成密钥/IV——调用方需自行保存密钥。"""
    algo = registry.get(FAMILY, name)
    k = new_key(algo) if key is None else as_bytes(key, field="密钥")
    iv = new_nonce(algo)
    return iv + encrypt(name, k, iv, plaintext)


def decrypt_packed(name: str, key: BytesLike, packed: BytesLike) -> bytes:
    """`encrypt_packed` 的逆操作。"""
    algo = registry.get(FAMILY, name)
    blob = as_bytes(packed, field="打包密文")
    size = algo.nonce_size
    if size and len(blob) <= size:
        from ..errors import KeyFormatError
        raise KeyFormatError(f"{name} 打包密文过短，缺少 nonce")
    return decrypt(name, key, blob[:size], blob[size:])


def recommended() -> str:
    """推荐算法：AES-256-CBC（通用）；国密场景请显式取 `sm4-cbc`。"""
    existing = registry.names(FAMILY)
    return DEFAULT if DEFAULT in existing else (existing[0] if existing else DEFAULT)


__all__ = ["FAMILY", "DEFAULT", "names", "nonce_size", "key_size", "generate_key",
           "new_iv", "encrypt", "decrypt", "encrypt_packed", "decrypt_packed",
           "recommended"]

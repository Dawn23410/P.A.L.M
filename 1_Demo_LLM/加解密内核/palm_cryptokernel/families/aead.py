"""AEAD 族薄接口：认证加密（推荐给一切"落盘/传输"场景的默认选择）。

语义约定（与 provider 无关，全族一致）：
- `seal(...)` 返回 `密文 ‖ 认证标签`，**不含 nonce**；
- `open(...)` 认证失败抛 `AEADError`，**绝不返回"看起来正常"的假明文**。
AAD 不加密但参与认证（如记录 ID、表名、版本号），用于绑定上下文防重放/错位。
"""
from __future__ import annotations

from ..registry import registry
from ._util import BytesLike, as_bytes, check_length, new_key, new_nonce

FAMILY = "aead"
DEFAULT = "aes-256-gcm"


def names() -> list[str]:
    """可用 AEAD 算法名。"""
    return registry.names(FAMILY)


def nonce_size(name: str) -> int:
    """所需 nonce 长度（GCM 12、CCM 13、OCB 15、SIV 16…）。"""
    return registry.get(FAMILY, name).nonce_size


def key_size(name: str) -> int:
    """族默认密钥长度（AES-SIV 是 64 = 双密钥）。"""
    return registry.get(FAMILY, name).key_size()


def tag_size(name: str) -> int:
    """认证标签长度（字节）。"""
    return registry.get(FAMILY, name).tag_size


def generate_key(name: str) -> bytes:
    return new_key(registry.get(FAMILY, name))


def new_nonce_for(name: str) -> bytes:
    """按算法声明生成随机 nonce（长度由算法自述）。"""
    return new_nonce(registry.get(FAMILY, name))


def seal(name: str, key: BytesLike, nonce: BytesLike, plaintext: BytesLike,
         aad: BytesLike = b"") -> bytes:
    """加密并认证，返回 `密文 ‖ 标签`。"""
    algo = registry.get(FAMILY, name)
    n = as_bytes(nonce, field=f"{name} nonce")
    check_length(n, algo.nonce_size, field=f"{name} nonce")
    return algo.seal(as_bytes(key, field="密钥"), n, as_bytes(plaintext),
                     as_bytes(aad, field="AAD"))


def open(name: str, key: BytesLike, nonce: BytesLike, sealed: BytesLike,
         aad: BytesLike = b"") -> bytes:
    """验签后解密；认证失败抛 AEADError。"""
    algo = registry.get(FAMILY, name)
    n = as_bytes(nonce, field=f"{name} nonce")
    check_length(n, algo.nonce_size, field=f"{name} nonce")
    return algo.open(as_bytes(key, field="密钥"), n,
                     as_bytes(sealed, field="密文"), as_bytes(aad, field="AAD"))


def seal_packed(name: str, key: BytesLike, plaintext: BytesLike,
                aad: BytesLike = b"") -> bytes:
    """便捷封装：返回 `nonce ‖ 密文 ‖ 标签`（nonce 随包走，便于单列落盘）。"""
    algo = registry.get(FAMILY, name)
    n = new_nonce(algo)
    return n + seal(name, key, n, plaintext, aad)


def open_packed(name: str, key: BytesLike, packed: BytesLike,
                aad: BytesLike = b"") -> bytes:
    """`seal_packed` 的逆操作。"""
    algo = registry.get(FAMILY, name)
    blob = as_bytes(packed, field="打包密文")
    size = algo.nonce_size
    if size and len(blob) < size + algo.tag_size:
        from ..errors import KeyFormatError
        raise KeyFormatError(f"{name} 打包密文过短，缺少 nonce 或标签")
    return open(name, key, blob[:size], blob[size:], aad)


def recommended() -> str:
    """推荐算法：AES-256-GCM（通用硬件加速）；无 AES 场景退 ChaCha20-Poly1305。"""
    existing = registry.names(FAMILY)
    for candidate in (DEFAULT, "chacha20-poly1305"):
        if candidate in existing:
            return candidate
    if not existing:
        from ..errors import AlgorithmNotFound
        raise AlgorithmNotFound(FAMILY, DEFAULT)
    return existing[0]


__all__ = ["FAMILY", "DEFAULT", "names", "nonce_size", "key_size", "tag_size",
           "generate_key", "new_nonce_for", "seal", "open", "seal_packed",
           "open_packed", "recommended"]

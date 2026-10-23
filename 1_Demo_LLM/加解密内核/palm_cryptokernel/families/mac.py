"""MAC 族薄接口：消息认证码的计算与**常量时间**校验。

覆盖面：HMAC-SHA2/SHA3/SM3、CMAC-AES、GMAC、KMAC、Poly1305。
校验一律走 provider 的 verify（内部用常量时间比较），调用方不该自己比 tag。
"""
from __future__ import annotations

from typing import Optional

from ..registry import registry
from ._util import BytesLike, as_bytes, check_length, random_nonce

FAMILY = "mac"
DEFAULT = "hmac-sha256"


def names(*, include_legacy: bool = True) -> list[str]:
    """可用 MAC 算法名。"""
    all_names = registry.names(FAMILY)
    if include_legacy:
        return all_names
    return [n for n in all_names if not registry.get(FAMILY, n).legacy]


def compute(name: str, key: BytesLike, data: BytesLike,
            nonce: Optional[BytesLike] = None) -> bytes:
    """计算 MAC；仅 GMAC 一类需要 nonce，其余传 None 即可。"""
    algo = registry.get(FAMILY, name)
    n = None if nonce is None else as_bytes(nonce, field="nonce")
    if n is not None:
        check_length(n, algo.nonce_size, field=f"{name} nonce")
    return algo.compute(as_bytes(key, field="密钥"), as_bytes(data), n)


def verify(name: str, key: BytesLike, data: BytesLike, tag: BytesLike,
           nonce: Optional[BytesLike] = None) -> bool:
    """常量时间校验 MAC；不抛异常，统一返回布尔。"""
    algo = registry.get(FAMILY, name)
    n = None if nonce is None else as_bytes(nonce, field="nonce")
    return algo.verify(as_bytes(key, field="密钥"), as_bytes(data),
                       as_bytes(tag, field="标签"), n)


def tag_size(name: str) -> int:
    """标签长度（字节）。"""
    return registry.get(FAMILY, name).mac_size


def nonce_size(name: str) -> int:
    """所需 nonce 长度；0 表示不需要。"""
    return registry.get(FAMILY, name).nonce_size


def generate_key(name: str) -> bytes:
    """按算法声明生成随机密钥；键长自由的算法（HMAC/KMAC）取 256 位默认值。"""
    sizes = getattr(registry.get(FAMILY, name), "key_sizes", ())
    return random_nonce(sizes[0] if sizes else 32)


def recommended() -> str:
    """推荐算法：HMAC-SHA256。"""
    existing = registry.names(FAMILY)
    return DEFAULT if DEFAULT in existing else (existing[0] if existing else DEFAULT)


__all__ = ["FAMILY", "DEFAULT", "names", "compute", "verify", "tag_size",
           "nonce_size", "generate_key", "recommended"]

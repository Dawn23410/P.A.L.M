"""哈希族薄接口：一行拿到摘要 / 指纹。

实现方（Cryptodome、OpenSSL、纯 Python gmssl）由注册表择优，调用方只写算法名；
故"SM3 走 C 后端还是纯 Python"这类换装对上层完全不可见。
"""
from __future__ import annotations

import hmac as _hmac
from ..errors import AlgorithmNotFound
from ..registry import registry
from ._util import BytesLike, as_bytes

FAMILY = "hash"
DEFAULT = "sha256"


def names(*, include_legacy: bool = True) -> list[str]:
    """可用哈希算法名；`include_legacy=False` 滤掉带 legacy 标记的弱算法。

    该参数是**接口契约**（能力清单/审计按它过滤），予以保留；当前摘要族里已无 legacy
    档（md5/sha1 于 v0.5.2 移除），故两种取法结果相同，一旦将来重新登记兼容档即生效。
    """
    all_names = registry.names(FAMILY)
    if include_legacy:
        return all_names
    return [n for n in all_names if not registry.get(FAMILY, n).legacy]


def digest(name: str, data: BytesLike) -> bytes:
    """原始摘要字节。"""
    return registry.get(FAMILY, name).digest(as_bytes(data))


def hexdigest(name: str, data: BytesLike) -> str:
    """十六进制摘要（落库/展示用）。"""
    return digest(name, data).hex()


def fingerprint(data: BytesLike, *, algorithm: str = DEFAULT,
                size: int = 8) -> str:
    """短指纹：取十六进制摘要前 `size` 字节（内容寻址、去重键的常用形态）。"""
    algo = registry.get(FAMILY, algorithm)
    raw = algo.digest(as_bytes(data))
    if size <= 0 or size > algo.digest_size:
        from ..errors import KeyFormatError
        raise KeyFormatError(
            f"指纹长度应在 1~{algo.digest_size} 字节，得到 {size}")
    return raw[:size].hex()


def matches(name: str, data: BytesLike, expected: bytes) -> bool:
    """常量时间比对摘要，避免时序侧信道（校验完整性务必用它，别用 ==）。"""
    return _hmac.compare_digest(digest(name, data), bytes(expected))


def digest_size(name: str) -> int:
    """摘要输出长度（字节）。"""
    return registry.get(FAMILY, name).digest_size


def recommended() -> str:
    """推荐算法：优先 SHA-256（通用），无则退到可用列表首个。"""
    existing = registry.names(FAMILY)
    if DEFAULT in existing:
        return DEFAULT
    if not existing:
        raise AlgorithmNotFound(FAMILY, DEFAULT)
    return existing[0]


__all__ = ["FAMILY", "DEFAULT", "names", "digest", "hexdigest",
           "fingerprint", "matches", "digest_size", "recommended"]

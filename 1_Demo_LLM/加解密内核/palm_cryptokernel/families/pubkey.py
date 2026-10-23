"""公钥加密族薄接口：RSA-OAEP / RSA-PKCS1v1.5 / SM2。

⚠️ 两条硬约束（写在这里省得踩）：
1. 本族**只能加密短数据**（明文上限 ≈ 模长 − 填充开销，RSA-2048 约 190 字节）。
   长数据请用 `envelope` 族（公钥封装数据密钥 + AEAD 加密正文）。
2. **不要用** `rsa-pkcs1v15` 做新业务（已标 legacy，存在 Bleichenbacher 类风险）。
"""
from __future__ import annotations

from ..registry import registry
from ._util import BytesLike, as_bytes

FAMILY = "pubkey"
DEFAULT = "rsa-oaep"
DEFAULT_GM = "sm2"


def names(*, include_legacy: bool = True) -> list[str]:
    """可用公钥加密算法名。"""
    all_names = registry.names(FAMILY)
    if include_legacy:
        return all_names
    return [n for n in all_names if not registry.get(FAMILY, n).legacy]


def generate(name: str) -> tuple[bytes, bytes]:
    """生成密钥对，返回 (公钥 bytes, 私钥 bytes)。"""
    return registry.get(FAMILY, name).generate()


def encrypt(name: str, public_key: BytesLike, plaintext: BytesLike) -> bytes:
    """公钥加密（仅限短明文）。"""
    return registry.get(FAMILY, name).encrypt(
        as_bytes(public_key, field="公钥"), as_bytes(plaintext))


def decrypt(name: str, secret_key: BytesLike, ciphertext: BytesLike) -> bytes:
    """私钥解密；密钥或密文非法抛 KeyFormatError。"""
    return registry.get(FAMILY, name).decrypt(
        as_bytes(secret_key, field="私钥"), as_bytes(ciphertext, field="密文"))


def max_plaintext(name: str, public_key: BytesLike) -> int:
    """该密钥下明文长度上限（字节）——超限请改用 envelope。"""
    algo = registry.get(FAMILY, name)
    probe = getattr(algo, "max_plaintext", None)
    if callable(probe):
        return int(probe(as_bytes(public_key, field="公钥")))
    return 0   # 未提供上界估算（如 SM2 定长分量），返回 0 表示"未知"


def recommended(*, guomi: bool = False) -> str:
    """推荐算法：默认 RSA-OAEP；`guomi=True` 取 SM2。"""
    existing = registry.names(FAMILY)
    candidate = DEFAULT_GM if guomi else DEFAULT
    if candidate in existing:
        return candidate
    if not existing:
        from ..errors import AlgorithmNotFound
        raise AlgorithmNotFound(FAMILY, candidate)
    return existing[0]


__all__ = ["FAMILY", "DEFAULT", "DEFAULT_GM", "names", "generate", "encrypt",
           "decrypt", "max_plaintext", "recommended"]

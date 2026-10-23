"""提供方：gmssl —— 国密 SM2 / SM3 / SM4（纯 Python，零第三方依赖兜底）。

为什么保留：这是**纯 Python 兜底通道**——即使 OpenSSL 不含 sm3、Cryptodome 不可用，
国密能力仍在。实现直接复用本包的既有模块（`sm3` / `sm4` / `sm2`）与其底层
`backends`，因此**字节格式与历史数据完全一致**（存量密文不受影响）。
SM3 与 OpenSSL 通道互为对拍，见 tests/test_providers.py。
"""
from __future__ import annotations

from ..abcs import (
    Algorithm,
    CipherAlgorithm,
    HashAlgorithm,
    PublicKeyCipher,
)
from ..errors import KeyFormatError

PROVIDER = "gmssl"
REQUIRES = "gmssl"

_SM2_PRIV_LEN = 32   # 私钥 32 字节（gmssl 以 hex 表示）
_SM2_PUB_LEN = 64    # 公钥 64 字节 = x‖y（gmssl 以 hex 表示）


class _Sm3(HashAlgorithm):
    """SM3（GB/T 32905-2016，256 位）。"""

    name, provider, standard = "sm3", PROVIDER, "GB/T 32905-2016"
    digest_size, block_size = 32, 64

    def digest(self, data: bytes) -> bytes:
        from ..sm3 import sm3_hash
        return bytes.fromhex(sm3_hash(data))


class _Sm4Cbc(CipherAlgorithm):
    """SM4-CBC + PKCS7（GB/T 32907-2016）。与非 ABC 的 `Sm4Cipher` 共用底层。"""

    name, provider, standard = "sm4-cbc", PROVIDER, "GB/T 32907-2016"
    key_sizes, nonce_size = (16,), 16

    def encrypt(self, key: bytes, nonce: bytes, plaintext: bytes) -> bytes:
        from .. import backends
        if len(key) != 16 or len(nonce) != 16:
            raise KeyFormatError("SM4 需要 16 字节密钥与 16 字节 IV")
        return backends.sm4_cbc_encrypt(key, nonce, plaintext)

    def decrypt(self, key: bytes, nonce: bytes, ciphertext: bytes) -> bytes:
        from .. import backends
        try:
            return backends.sm4_cbc_decrypt(key, nonce, ciphertext)
        except ValueError as exc:
            raise KeyFormatError(f"sm4-cbc 解密失败：{exc}") from exc


class _Sm2PubKey(PublicKeyCipher):
    """SM2 公钥加密（GB/T 32918）—— 密钥信封用。密钥在 ABC 层为原始字节，内部转 hex。"""

    name, provider, standard = "sm2", PROVIDER, "GB/T 32918"

    def generate(self) -> tuple[bytes, bytes]:
        from ..sm2 import Sm2Key
        k = Sm2Key.generate()
        return bytes.fromhex(k.public_key), bytes.fromhex(k.private_key)

    def encrypt(self, public_key: bytes, plaintext: bytes) -> bytes:
        from ..sm2 import Sm2Key
        if len(public_key) != _SM2_PUB_LEN:
            raise KeyFormatError(f"SM2 公钥应为 {_SM2_PUB_LEN} 字节")
        return Sm2Key(public_key=public_key.hex()).encrypt(plaintext)

    def decrypt(self, secret_key: bytes, ciphertext: bytes) -> bytes:
        from ..sm2 import Sm2Key
        if len(secret_key) != _SM2_PRIV_LEN:
            raise KeyFormatError(f"SM2 私钥应为 {_SM2_PRIV_LEN} 字节")
        try:
            return Sm2Key(private_key=secret_key.hex()).decrypt(ciphertext)
        except Exception as exc:  # gmssl 解密失败会抛裸异常，此处归一
            raise KeyFormatError(f"sm2 解密失败：{exc}") from exc


def build() -> list[Algorithm]:
    import gmssl  # noqa: F401  (可用性由加载器前置校验)
    return [_Sm3(), _Sm4Cbc(), _Sm2PubKey()]


MANIFEST: tuple[tuple[str, str], ...] = (
    ("hash", "sm3"), ("cipher", "sm4-cbc"), ("pubkey", "sm2"),
)

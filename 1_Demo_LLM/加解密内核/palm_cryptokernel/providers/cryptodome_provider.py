"""提供方：Cryptodome（pycryptodomex，C 加速）—— 对称加密 / 认证加密 / 密钥派生。

本文件只做一件事：把 Cryptodome 的能力**适配**成 abcs 的族接口。
不含协议组合逻辑（信封见 families/envelope.py），也不引用其它 provider——
provider 之间互不依赖，任一库缺失只影响它自己那几族。

保留范围（够用即止）：
- `cipher`  对称加密：`aes-256-cbc`（国际常规）+ 由 gmssl 提供的 `sm4-cbc`（国密）
- `aead`    认证加密：`aes-256-gcm`（默认）+ `chacha20-poly1305`（无 AES 加速的机器上更快）
- `kdf`     密钥派生：`hkdf`（高熵密钥扩展）+ `pbkdf2`（口令派生，vault 现用）

刻意**不登记**的东西：CMAC/GMAC/KMAC/Poly1305、CCM/EAX/OCB/SIV、DES/3DES/RC4/
Blowfish/CAST/AES-ECB、SHAKE/BLAKE2/KangarooTwelve、scrypt/bcrypt/KBKDF。
理由统一是"本项目没有调用点"——能力清单越小越可审计，安全模块不需要摆设。
"""
from __future__ import annotations

from typing import Any, Optional

from ..abcs import AEADAlgorithm, Algorithm, CipherAlgorithm, KDFAlgorithm
from ..errors import AEADError, KeyFormatError

PROVIDER = "cryptodome"
REQUIRES = "Cryptodome"

# (规范名, Cryptodome.Cipher 模块, 模式, 密钥字节, nonce 字节, 标准, 是否仅兼容)
_CIPHERS = (
    ("aes-256-cbc", "AES", "CBC", 32, 16, "FIPS 197 / SP 800-38A", False),
)

# (规范名, AEAD 种类, 密钥字节, nonce 字节, 标准)
_AEADS = (
    ("aes-256-gcm", "gcm", 32, 12, "NIST SP 800-38D"),
    ("chacha20-poly1305", "chacha20poly1305", 32, 12, "RFC 8439"),
)

# (规范名, 种类, 标准, 是否抗 GPU)
_KDFS = (
    ("hkdf", "hkdf", "RFC 5869", False),
    ("pbkdf2", "pbkdf2", "RFC 8018", True),
)

# KDF 允许的哈希原语（与 hash 族保留的集合一致，避免出现"清单外原语"）
_SHA_MODULE = {"sha256": "SHA256", "sha512": "SHA512"}


def _sha_mod(name: str) -> Any:
    from Cryptodome import Hash
    if name not in _SHA_MODULE:
        raise KeyFormatError(f"不支持的哈希原语：{name}")
    return getattr(Hash, _SHA_MODULE[name])


def _pkcs7_pad(data: bytes) -> bytes:
    """PKCS7 填充（RFC 5652）：补到 16 字节整数倍，满块时补一整块。"""
    n = 16 - len(data) % 16
    return data + bytes([n]) * n


def _pkcs7_unpad(data: bytes) -> bytes:
    """PKCS7 去填充；长度/填充字节非法一律抛 KeyFormatError（不静默截断）。"""
    if not data or len(data) % 16:
        raise KeyFormatError("无效的填充长度（密文非 16 字节整数倍）")
    n = data[-1]
    if not 1 <= n <= 16 or data[-n:] != bytes([n]) * n:
        raise KeyFormatError("无效的 PKCS7 填充（密钥错误或密文被篡改）")
    return data[:-n]


class _CyKDF(KDFAlgorithm):
    """`kind` 决定调用 Cryptodome.Protocol.KDF 的哪个函数。"""

    def __init__(self, name: str, kind: str, standard: str, memory_hard: bool):
        self.name, self._kind = name, kind
        self.provider, self.standard = PROVIDER, standard
        self._memory_hard = memory_hard

    @property
    def memory_hard(self) -> bool:
        return self._memory_hard

    def derive(self, secret: bytes, length: int, *, salt: Optional[bytes] = None,
               info: Optional[bytes] = None, **params: Any) -> bytes:
        if self._kind == "pbkdf2":
            from Cryptodome.Protocol.KDF import PBKDF2
            return PBKDF2(secret, salt or b"", length,
                          count=int(params.get("iterations", 200_000)),
                          hmac_hash_module=_sha_mod(params.get("hash", "sha256")))
        if self._kind == "hkdf":
            from Cryptodome.Protocol.KDF import HKDF
            return HKDF(secret, length, salt or b"",
                        _sha_mod(params.get("hash", "sha256")), context=info)
        raise KeyFormatError(f"未知 KDF 类型：{self._kind}")


class _CyCipher(CipherAlgorithm):
    """分组密码包装；密文一律不含 nonce。

    填充：Cryptodome 的 CBC **不自动填充**（直接喂非整块长度会报错），
    故本包装在 CBC 上自行做 PKCS7，与 sm4-cbc 的语义保持一致。
    """

    def __init__(self, name: str, mod: str, mode: str, key_size: int,
                 nonce_size: int, standard: str, legacy: bool):
        self.name, self._mod, self._mode = name, mod, mode
        self.key_sizes, self.nonce_size = (key_size,), nonce_size
        self.provider, self.standard, self.legacy = PROVIDER, standard, legacy

    def _new(self, key: bytes, nonce: bytes) -> Any:
        import importlib
        m = importlib.import_module(f"Cryptodome.Cipher.{self._mod}")
        return m.new(key, getattr(m, "MODE_" + self._mode), iv=nonce)

    def encrypt(self, key: bytes, nonce: bytes, plaintext: bytes) -> bytes:
        return self._new(key, nonce).encrypt(_pkcs7_pad(plaintext))

    def decrypt(self, key: bytes, nonce: bytes, ciphertext: bytes) -> bytes:
        try:
            out = self._new(key, nonce).decrypt(ciphertext)
        except ValueError as exc:
            raise KeyFormatError(f"{self.name} 解密失败：{exc}") from exc
        return _pkcs7_unpad(out)


class _CyAEAD(AEADAlgorithm):
    """GCM / ChaCha20-Poly1305 统一为 seal/open（密文与标签拼在一起返回）。"""

    def __init__(self, name: str, kind: str, key_size: int, nonce_size: int,
                 standard: str):
        self.name, self._kind = name, kind
        self.key_sizes, self.nonce_size = (key_size,), nonce_size
        self.provider, self.standard = PROVIDER, standard

    def _ctor(self, key: bytes, nonce: bytes) -> Any:
        if self._kind == "chacha20poly1305":
            from Cryptodome.Cipher import ChaCha20_Poly1305
            return ChaCha20_Poly1305.new(key=key, nonce=nonce)
        from Cryptodome.Cipher import AES
        return AES.new(key, AES.MODE_GCM, nonce=nonce)

    def seal(self, key: bytes, nonce: bytes, plaintext: bytes, aad: bytes = b"") -> bytes:
        cipher = self._ctor(key, nonce)
        try:
            if aad:
                cipher.update(aad)
            ct, tag = cipher.encrypt_and_digest(plaintext)
        except ValueError as exc:
            raise AEADError(f"{self.name} 加密失败：{exc}") from exc
        return ct + tag

    def open(self, key: bytes, nonce: bytes, sealed: bytes, aad: bytes = b"") -> bytes:
        if len(sealed) < self.tag_size:
            raise AEADError(f"{self.name} 密文过短，缺少认证标签")
        ct, tag = sealed[:-self.tag_size], sealed[-self.tag_size:]
        try:
            cipher = self._ctor(key, nonce)
            if aad:
                cipher.update(aad)
            return cipher.decrypt_and_verify(ct, tag)
        except ValueError as exc:
            raise AEADError(f"{self.name} 认证失败（密文/AAD/密钥不匹配）") from exc


def build() -> list[Algorithm]:
    """装配本提供方的全部算法（Cryptodome 可用性已由加载器前置校验）。"""
    out: list[Algorithm] = []
    for name, kind, ks, ns, std in _AEADS:
        out.append(_CyAEAD(name, kind, ks, ns, std))
    for name, mod, mode, ks, ns, std, legacy in _CIPHERS:
        out.append(_CyCipher(name, mod, mode, ks, ns, std, legacy))
    for name, kind, std, mh in _KDFS:
        out.append(_CyKDF(name, kind, std, mh))
    return out


MANIFEST: tuple[tuple[str, str], ...] = (
    tuple(("aead", n) for n, *_ in _AEADS)
    + tuple(("cipher", n) for n, *_ in _CIPHERS)
    + tuple(("kdf", n) for n, *_ in _KDFS)
)

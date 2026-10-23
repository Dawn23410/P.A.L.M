"""算法抽象基类（端口定义）—— 加解密内核的可插拔契约。

设计要点（WHY）
--------------
- 每个**算法族**一个 ABC，只描述"能力"，不绑定任何具体库的调用形态；
  换库 / 加库只新增 `providers/*.py`，上层（记忆层、砖块、UI）零改动。
- 所有族共用 `Algorithm` 根类，统一暴露 `name / family / provider / standard`，
  使能力清单、审计报告、算法优选都能靠同一套元信息工作。
- 明文、密文、密钥一律 **bytes 进出**：str 归一由族模块负责，避免隐式编码差异；
  密钥的 bytes 形态约定见 `KeyLike`（RSA/EC 用 DER，SM2 用原始字节）。
- 安全语义内建：认证类接口（AEAD）失败时**抛本内核异常**，
  不返回"看起来正常"的假明文——库的原始异常由 provider 归一。

范围边界（WHY）：本内核只做**机密性 + 完整性**，不做**不可否认 / 来源认证**，
也不做**后量子 / 密钥协商**。单机单用户场景下签名没有需求方，密钥封装与协商
也找不到调用方，故这三类端口一律不设：

    签名（RSA-PSS/ECDSA/Ed25519/ML-DSA…）   → 完整性由 HMAC（mac 族）承担
    后量子 KEM（ML-KEM/McEliece/HQC/NTRU）  → 常规公钥加密（pubkey 族）已够用
    密钥协商（ECDH/X25519/DH）              → 单机无对端可协商

少一族端口就少一片攻击面与审计面：安全模块不需要"能力陈列室"。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

# 密钥的可移植形态：RSA/EC 为 DER（SubjectPublicKeyInfo / PKCS#8），
# SM2 为原始字节。provider 也可额外接受其原生密钥对象。
KeyLike = bytes


# ─────────────────────────── 根类 ───────────────────────────

class Algorithm(ABC):
    """一切算法的公共元信息契约（族 ABC 均继承它）。"""

    name: str = ""          # 规范名：小写连字符，如 "aes-256-gcm"
    family: str = ""        # 族标识：hash/mac/kdf/cipher/aead/pubkey
    provider: str = ""      # 实现方标识，如 "cryptodome" / "gmssl" / "hashlib"
    standard: str = ""      # 标准出处，如 "FIPS 197"，供审计引用
    legacy: bool = False    # 是否属"仅兼容"的弱算法（如 RSA-PKCS1v15 这类旧填充）

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.name} via {self.provider}>"

    @property
    def spec(self) -> dict[str, Any]:
        """元信息快照：能力清单与审计报告的唯一数据源。"""
        return {
            "name": self.name,
            "family": self.family,
            "provider": self.provider,
            "standard": self.standard,
            "legacy": self.legacy,
        }


# ─────────────────────── 哈希 / MAC / KDF ───────────────────────

class HashAlgorithm(Algorithm):
    """密码学摘要。用于内容指纹、完整性标签、HMAC/KDF 的哈希原语。"""

    family = "hash"
    digest_size: int = 0    # 输出字节数
    block_size: int = 64    # 分组字节数（HMAC RFC 2104 与部分 KDF 需要）

    @abstractmethod
    def digest(self, data: bytes) -> bytes:
        """返回原始摘要字节。"""

    def hexdigest(self, data: bytes) -> str:
        """十六进制摘要（便于落库/展示）。"""
        return self.digest(data).hex()


class MACAlgorithm(Algorithm):
    """消息认证码。`nonce_size=0` 表示不需要 nonce（HMAC/CMAC/KMAC）。"""

    family = "mac"
    mac_size: int = 0
    key_sizes: tuple[int, ...] = ()   # 合法密钥长度（字节）；空元组 = 任意
    nonce_size: int = 0

    @abstractmethod
    def compute(self, key: bytes, data: bytes,
                nonce: Optional[bytes] = None) -> bytes:
        """计算 MAC。"""

    def verify(self, key: bytes, data: bytes, tag: bytes,
               nonce: Optional[bytes] = None) -> bool:
        """常量时间校验（默认实现；provider 可覆盖）。"""
        import hmac as _hmac
        return _hmac.compare_digest(self.compute(key, data, nonce), tag)


class KDFAlgorithm(Algorithm):
    """密钥派生函数。口令类（argon2/scrypt/bcrypt/pbkdf2）与密钥扩展类（hkdf/kbkdf）。"""

    family = "kdf"

    @abstractmethod
    def derive(self, secret: bytes, length: int, *, salt: Optional[bytes] = None,
               info: Optional[bytes] = None, **params: Any) -> bytes:
        """从 secret 派生出 length 字节密钥。口令类需 salt；hkdf 需 salt+info。"""

    @property
    def memory_hard(self) -> bool:
        """是否抗 GPU 暴力破解（argon2/scrypt/bcrypt 为 True）。"""
        return False


# ───────────────────────── 对称密码 ─────────────────────────

class SymmetricAlgorithm(Algorithm):
    """对称族公共属性。"""

    key_sizes: tuple[int, ...] = ()   # 合法密钥长度（字节）；空 = 由 key 长度决定
    nonce_size: int = 0               # 期望 nonce 长度（字节）；0 = 不需要

    def key_size(self) -> int:
        """族默认密钥长度（取第一个声明值，供推荐/优选使用）。"""
        return self.key_sizes[0] if self.key_sizes else 0


class CipherAlgorithm(SymmetricAlgorithm):
    """无认证的对称加密（CBC/CTR/…）。调用方需自行保证完整性。"""

    family = "cipher"

    @abstractmethod
    def encrypt(self, key: bytes, nonce: bytes, plaintext: bytes) -> bytes:
        """加密（各 provider 内部统一处理填充，密文不含 nonce）。"""

    @abstractmethod
    def decrypt(self, key: bytes, nonce: bytes, ciphertext: bytes) -> bytes:
        """解密；填充/格式非法时抛 KeyFormatError。"""


class AEADAlgorithm(SymmetricAlgorithm):
    """带关联数据的认证加密（AES-GCM / ChaCha20-Poly1305…）。"""

    family = "aead"
    tag_size: int = 16

    @abstractmethod
    def seal(self, key: bytes, nonce: bytes, plaintext: bytes,
             aad: bytes = b"") -> bytes:
        """加密并认证，返回「密文 ‖ 认证标签」。"""

    @abstractmethod
    def open(self, key: bytes, nonce: bytes, sealed: bytes,
             aad: bytes = b"") -> bytes:
        """校验认证标签后解密；失败抛 AEADError（绝不返回假明文）。"""


# ───────────────────────── 非对称族 ─────────────────────────

class _KeyPairAlgorithm(Algorithm):
    """有密钥对的族公共方法：密钥生成统一返回 (公钥字节, 私钥字节)。"""

    @abstractmethod
    def generate(self) -> tuple[bytes, bytes]:
        """生成密钥对，返回 (public, secret)。"""


class PublicKeyCipher(_KeyPairAlgorithm):
    """公钥加解密（RSA-OAEP / RSA-PKCS1v1.5 / SM2）。

    ⚠️ 只用于**短数据**（RSA-2048 上限约 190 字节，见 provider 的 `max_plaintext`）。
    任意长数据请走 `envelope` 族（公钥封装数据密钥 + AEAD 加密正文）。
    """

    family = "pubkey"

    @abstractmethod
    def encrypt(self, public_key: KeyLike, plaintext: bytes) -> bytes: ...

    @abstractmethod
    def decrypt(self, secret_key: KeyLike, ciphertext: bytes) -> bytes: ...


__all__ = [
    "KeyLike",
    "Algorithm",
    "HashAlgorithm",
    "MACAlgorithm",
    "KDFAlgorithm",
    "SymmetricAlgorithm",
    "CipherAlgorithm",
    "AEADAlgorithm",
    "PublicKeyCipher",
]

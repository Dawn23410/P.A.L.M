"""统一门面 CryptoSuite：按「族 + 规范名」取算法，并可枚举/推荐能力。

三层分工（这是本内核可插拔的核心）：
    abcs（端口）  ←  providers（各库的适配实现）  ←  registry（择优装配）
                                  ↑
                          CryptoSuite（调用方唯一入口）

调用方只说"我要 aes-256-gcm"，不需要知道它来自 Cryptodome 还是别的库；
换库、加库、某库缺失，对调用方都是透明的。
"""
from __future__ import annotations

from typing import Optional

from .abcs import (
    AEADAlgorithm,
    Algorithm,
    CipherAlgorithm,
    HashAlgorithm,
    KDFAlgorithm,
    MACAlgorithm,
    PublicKeyCipher,
)
from .capabilities import FAMILY_LABELS, absent, report
from .registry import registry

# 各族默认推荐（算法择优的最小实现）：优先选"现代、无已知弱点"的那档
_PREFERRED = {
    "hash": ("sha256", "sm3"),
    "mac": ("hmac-sha256", "hmac-sm3"),
    "kdf": ("argon2id", "pbkdf2", "hkdf"),
    "cipher": ("aes-256-cbc", "sm4-cbc"),
    "aead": ("aes-256-gcm", "chacha20-poly1305"),
    "pubkey": ("rsa-oaep", "sm2"),
}


class CryptoSuite:
    """算法族统一入口；所有取用都走注册表，故能力随 provider 增减自动变化。"""

    # ── 通用 ──
    def get(self, family: str, name: str) -> Algorithm:
        """按族取算法（未注册抛 AlgorithmNotFound）。"""
        return registry.get(family, name)

    def names(self, family: str) -> list[str]:
        """某族可用规范名列表。"""
        return registry.names(family)

    def families(self) -> list[str]:
        """全部族标识。"""
        return registry.families()

    def labels(self) -> dict[str, str]:
        """族标识 → 中文标签。"""
        return dict(FAMILY_LABELS)

    def capabilities(self) -> dict:
        """完整能力报告（可用矩阵 + 缺口 + provider 状态）。"""
        return report()

    def gaps(self) -> list[dict]:
        """当前不可用的算法与原因。"""
        return absent()

    def recommended(self, family: str) -> str:
        """该族的推荐算法名：按预设优先序取第一个可用的，全不可用则报错。"""
        for candidate in _PREFERRED.get(family, ()):
            if candidate in registry.names(family):
                return candidate
        names = registry.names(family)
        if not names:
            from .errors import AlgorithmNotFound
            raise AlgorithmNotFound(family, "<any>")
        return names[0]

    def describe(self, family: str, name: str) -> dict:
        """单条算法的详细描述：元信息 + 全部实现方 + 是否为本族推荐。"""
        primary = registry.get(family, name)
        providers = [a.provider for a in registry.all_of(family) if a.name == name]
        return dict(primary.spec, providers=providers,
                    implementation_count=len(providers),
                    recommended=(self.recommended(family) == name))

    # ── 各族带类型的取用 ──
    def hashing(self, name: Optional[str] = None) -> HashAlgorithm:
        return self.get("hash", name or self.recommended("hash"))  # type: ignore[return-value]

    def mac(self, name: Optional[str] = None) -> MACAlgorithm:
        return self.get("mac", name or self.recommended("mac"))  # type: ignore[return-value]

    def kdf(self, name: Optional[str] = None) -> KDFAlgorithm:
        return self.get("kdf", name or self.recommended("kdf"))  # type: ignore[return-value]

    def cipher(self, name: Optional[str] = None) -> CipherAlgorithm:
        return self.get("cipher", name or self.recommended("cipher"))  # type: ignore[return-value]

    def aead(self, name: Optional[str] = None) -> AEADAlgorithm:
        return self.get("aead", name or self.recommended("aead"))  # type: ignore[return-value]

    def pubkey(self, name: Optional[str] = None) -> PublicKeyCipher:
        return self.get("pubkey", name or self.recommended("pubkey"))  # type: ignore[return-value]


suite = CryptoSuite()

# 模块级便捷函数（薄封装，便于 `from palm_cryptokernel import aead` 式书写）
hashing = suite.hashing
mac = suite.mac
kdf = suite.kdf
cipher = suite.cipher
aead = suite.aead
pubkey = suite.pubkey

__all__ = [
    "CryptoSuite", "suite",
    "hashing", "mac", "kdf", "cipher", "aead", "pubkey",
]

"""palm_cryptokernel 的类型化异常层级。

为什么要有独立层级：算法族有多个、提供方（库）可插拔，上层（记忆层/砖块）
需要按**语义**而非按库的原始异常来做分支——例如"认证失败"应当统一捕获，
而不是分别去 catch Cryptodome 的 ValueError 与 gmssl 的异常。
"""
from __future__ import annotations


class CryptoError(Exception):
    """本内核一切错误的基类。"""


class AlgorithmNotFound(CryptoError, KeyError):
    """按名取算法时未命中（名字拼错，或该族无此算法）。"""

    def __init__(self, family: str, name: str):
        super().__init__(f"未注册的算法：family={family!r} name={name!r}")
        self.family = family
        self.name = name


class ProviderUnavailable(CryptoError):
    """所需密码学库缺失（可选提供方未安装）。"""


class KeyFormatError(CryptoError):
    """密钥/公钥格式非法或长度不符。"""


class AEADError(CryptoError):
    """AEAD 认证失败（密文被篡改 / AAD 不符 / 密钥或 nonce 不对）。"""


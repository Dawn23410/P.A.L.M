"""palm_cryptokernel —— P.A.L.M 加解密内核（可插拔多后端 + 国密 + 国际算法）。

定位：把"用什么密码学库"从上层代码里彻底拿掉。上层只说算法名（`aes-256-gcm`、
`sm3`、`aes-256-gcm`），由注册表按 provider 优先级择优实现；换库、加库、某库缺失
对调用方透明（缺失会如实进 `capabilities` 的缺口清单，不搞假可用）。

范围边界（WHY）
----------------
只做**机密性 + 完整性**：对称/公钥加密、哈希、MAC、KDF。
**不做数字签名**（单机单用户没有不可否认需求，完整性用 HMAC-SM3 已足够）、
**不做后量子**（常规公钥加密已够用，且少一片攻击面）、
**不做密钥协商**（单机无对端可协商）。详见 abcs 的端口清单。

分层（自下而上，层间单向依赖）
--------------------------------
    providers/*   各密码学库的适配实现（Cryptodome / hashlib+OpenSSL / gmssl /
                  argon2cffi）——只实现 abcs，互不调用
    registry      规范名 → 实现择优 + 加载失败记账
    capabilities  能力矩阵 / 缺口披露 / provider 状态（安全模块的诚实性出口）
    families/*    族薄接口（hash/mac/kdf/cipher/aead/pubkey/envelope）
    suite         CryptoSuite 门面（按族取算法、推荐择优）

三套常用入口
------------
1. 门面对象（推荐，可枚举/推荐）::

       from palm_cryptokernel import suite
       aead = suite.aead()                    # 族推荐算法
       key  = aead.key_size()
       blob = aead.seal(key, nonce, b"正文")
       print(suite.capabilities()["counts"])

2. 族薄函数（最省事，一行一动作）::

       from palm_cryptokernel import families as f
       f.hash.hexdigest("sm3", b"内容")
       blob = f.envelope.seal(pk, b"任意长正文", aad=b"记录ID=42")

3. 底层对象（要精细控制时）::

       from palm_cryptokernel.registry import registry
       algo = registry.get("aead", "aes-256-gcm")
       print(algo.provider, algo.standard)

向后兼容
--------
旧接口（`sm3_hash` / `sm3_int` / `Sm4Cipher` / `Sm2Key` / `MemoryCipher` /
`vault`）**逐一原样保留**，且 `Sm4Cipher` 与 `MemoryCipher` 的密文格式未变——
存量落盘数据（记忆正文、密钥库）不受本次重构影响。
"""
from __future__ import annotations

from . import backends, families, vault  # noqa: F401  后端探测 + 族薄接口 + 密钥库
from .abcs import (  # noqa: F401  端口定义，供第三方写新 provider
    AEADAlgorithm,
    Algorithm,
    CipherAlgorithm,
    HashAlgorithm,
    KDFAlgorithm,
    MACAlgorithm,
    PublicKeyCipher,
)
from .errors import (  # noqa: F401  统一异常层级
    AEADError,
    AlgorithmNotFound,
    CryptoError,
    KeyFormatError,
    ProviderUnavailable,
)
from .registry import registry  # noqa: F401
from .suite import CryptoSuite, suite  # noqa: F401

# ── 旧接口（兼容层，不要删：app/.palm 存量调用依赖它们）──
from .cipher import MemoryCipher
from .sm2 import Sm2Key
from .sm3 import sm3_hash, sm3_int
from .sm4 import Sm4Cipher

__version__ = "0.5.2"   # 0.5.2：移除 md5/sha1 弱摘要槽位（矩阵 18→16 条，零消费者）

__all__ = [
    # 内核门面
    "suite",
    "CryptoSuite",
    "registry",
    "families",
    "backends",
    # 端口定义
    "Algorithm",
    "HashAlgorithm",
    "MACAlgorithm",
    "KDFAlgorithm",
    "CipherAlgorithm",
    "AEADAlgorithm",
    "PublicKeyCipher",
    # 异常
    "CryptoError",
    "AlgorithmNotFound",
    "ProviderUnavailable",
    "KeyFormatError",
    "AEADError",
    # 兼容层（旧接口）
    "sm3_hash",
    "sm3_int",
    "Sm4Cipher",
    "Sm2Key",
    "MemoryCipher",
    "vault",
]

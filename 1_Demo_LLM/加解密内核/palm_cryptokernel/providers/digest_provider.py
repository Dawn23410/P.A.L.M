"""提供方：hashlib / OpenSSL —— 摘要与 HMAC（C 加速，零第三方依赖）。

登记的每一档都有明确位置：
- `sm3`    国密内容指纹（GB/T 32905-2016）——**由 OpenSSL 3.x 走 C**，与 gmssl 纯
           Python 实现互为对拍（见 tests/test_kernel.py 的跨实现一致性用例）；
- `sha256` 通用指纹 / 派生原语；
- `sha512` 更高强度档，且是 HMAC-SHA512 的原语。

不再登记 SHA-3 全家族、BLAKE2、SHAKE、RIPEMD —— 它们在本项目里没有任何调用点，
留着只增审计面（"宁可缺，不可假"，也不需要无用项）。

🔴 **md5 / sha1 已于 v0.5.2 移除**（它们原先挂 `legacy=True` 作为"读旧数据"的兼容档）：
该假设经复核**不成立** —— 存量指纹全部由 sm3 / sha256 / sha512 产生，没有任何历史数据
需要弱摘要来解；且内核里**零消费者**。而 `legacy` 只是个标记、**并不阻止调用**，
弱算法槽位一旦留在安全面里就迟早会被用上；清掉比留着标记更安全。
需要弱哈希的**非安全**场景（缓存键、分桶索引、去重）请直接 `import hashlib` 用，
不要把它接回内核的安全面。
"""
from __future__ import annotations

import hashlib
from typing import Optional

from ..abcs import Algorithm, HashAlgorithm, MACAlgorithm
from ..errors import KeyFormatError

PROVIDER = "hashlib"
REQUIRES = "hashlib"   # 标准库，恒可用

# (规范名, hashlib 名, 标准, 是否仅兼容) —— 摘要长度运行期读取，避免写错
# 第 4 列保留 `legacy` 位（能力清单/审计按它过滤），当前摘要族里恒为 False。
_PLAIN = (
    ("sm3", "sm3", "GB/T 32905-2016", False),
    ("sha256", "sha256", "FIPS 180-4", False),
    ("sha512", "sha512", "FIPS 180-4", False),
)

# HMAC 原语（与上面的摘要集保持一致，不多不少）
_HMAC = ("sm3", "sha256", "sha512")


class _LibHash(HashAlgorithm):
    def __init__(self, name: str, algo: str, standard: str, legacy: bool):
        self.name, self._algo = name, algo
        self.provider, self.standard, self.legacy = PROVIDER, standard, legacy
        probe = hashlib.new(algo)
        self.digest_size = probe.digest_size
        self.block_size = probe.block_size or 64

    def digest(self, data: bytes) -> bytes:
        return hashlib.new(self._algo, data).digest()


class _LibHMAC(MACAlgorithm):
    """HMAC（RFC 2104）走标准库 hmac —— 含 HMAC-SM3 这一国密组合。"""

    def __init__(self, hash_name: str, algo: str):
        self.name = f"hmac-{hash_name}"
        self.provider, self.standard = PROVIDER, "RFC 2104"
        self._algo = algo
        self.mac_size = hashlib.new(algo).digest_size

    def compute(self, key: bytes, data: bytes, nonce: Optional[bytes] = None) -> bytes:
        import hmac
        try:
            # digestmod 传算法名即可，标准库自行解析（含 sm3）
            return hmac.new(key, data, self._algo).digest()
        except (ValueError, TypeError) as exc:
            raise KeyFormatError(f"{self.name} 计算失败：{exc}") from exc


def build() -> list[Algorithm]:
    out: list[Algorithm] = []
    available = hashlib.algorithms_available
    for name, algo, std, legacy in _PLAIN:
        if algo in available:
            out.append(_LibHash(name, algo, std, legacy))
    # HMAC 只登记哈希原语确实可用的组合
    for algo in _HMAC:
        if algo in available:
            out.append(_LibHMAC(algo, algo))
    return out


MANIFEST: tuple[tuple[str, str], ...] = (
    tuple(("hash", n) for n, *_ in _PLAIN)
    + tuple(("mac", f"hmac-{a}") for a in _HMAC)
)

"""国密 SM2 椭圆曲线公钥密码（ECC，256 位，对标 RSA-2048 安全强度）。

用途：密钥信封（envelope）——用 SM2 公钥加密 SM4 对称密钥后随数据落库，私钥离线保管，
实现"密钥与数据分离"的强落盘安全。

不做签名：本内核的完整性由 HMAC（mac 族）承担，SM2 只作为公钥加密原语使用。

注意：gmssl 的 CryptSM2 需在构造时同时传入公私钥；公钥由私钥经椭圆曲线标量乘法
（k·G）派生，这里复用 gmssl 内置的 `_kg` 参考实现完成密钥生成。
"""
from __future__ import annotations

import os

from gmssl import sm2


class Sm2Key:
    def __init__(self, private_key: str = "", public_key: str = ""):
        self._priv = private_key
        self._pub = public_key

    @classmethod
    def generate(cls) -> "Sm2Key":
        """随机生成 SM2 密钥对（私钥 32 字节 hex，公钥 64 字节 hex = x∥y）。"""
        return cls.from_private(os.urandom(32).hex())

    @classmethod
    def from_private(cls, private_key: str) -> "Sm2Key":
        """由私钥派生公钥（k·G）。生成密钥对时用，也使只持私钥的调用方补齐公钥。"""
        s = sm2.CryptSM2(private_key=private_key, public_key="")
        pub = s._kg(int(private_key, 16), s.ecc_table["g"])
        return cls(private_key=private_key, public_key=pub)

    @property
    def private_key(self) -> str:
        return self._priv

    @property
    def public_key(self) -> str:
        return self._pub

    def _obj(self, need_priv: bool = False) -> "sm2.CryptSM2":
        """构造 gmssl 对象并**绕开其公钥前导裁剪缺陷**。

        gmssl 的 `CryptSM2.__init__` 用 `public_key.lstrip("04")` 去掉未压缩点前缀，
        但 `lstrip` 删的是**所有**前导 '0'/'4' 字符——实测约 0.43% 的 SM2 公钥
        （x 坐标恰以 0x04 开头）会被截短，导致验签 / 解密**静默失败**。
        这里先用空公钥构造，再直接赋值，完全避开该路径。
        """
        obj = sm2.CryptSM2(
            public_key="",
            private_key=self._priv if need_priv else "",
        )
        obj.public_key = self._pub
        return obj

    def encrypt(self, data: bytes) -> bytes:
        if not self._pub:
            raise ValueError("缺少 SM2 公钥，无法加密")
        return self._obj().encrypt(data)

    def decrypt(self, data: bytes) -> bytes:
        if not self._priv:
            raise ValueError("缺少 SM2 私钥，无法解密")
        return self._obj(need_priv=True).decrypt(data)

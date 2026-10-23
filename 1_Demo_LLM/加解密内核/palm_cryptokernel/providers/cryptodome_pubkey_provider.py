"""提供方：Cryptodome（pycryptodomex）—— RSA 公钥加密。

只登记两档，各自在 pubkey 族里有明确位置：
- `rsa-oaep`      推荐档（OAEP-SHA256 + MGF1），对选择密文攻击有安全归约；
- `rsa-pkcs1v15`  **仅兼容**档（legacy=True）：v1.5 填充对 Bleichenbacher 类
                  选择密文攻击有已知风险，只用于读存量，不要用于新业务。

本模块**不做签名**（签名族已按范围边界移除）；完整性由 HMAC 承担。
密钥形态：公钥 = DER SubjectPublicKeyInfo，私钥 = DER PKCS#8（见 abcs.KeyLike）。
"""
from __future__ import annotations

from typing import Any

from ..abcs import Algorithm, PublicKeyCipher
from ..errors import KeyFormatError

PROVIDER = "cryptodome"
REQUIRES = "Cryptodome"

# (规范名, 密钥位数, 填充种类, 标准, 是否仅兼容)
_KEYS = (
    ("rsa-oaep", 2048, "OAEP", "RFC 8017", False),
    ("rsa-pkcs1v15", 2048, "PKCS1_v1_5", "RFC 8017", True),
)

# OAEP 用的摘要（SHA-256 → hLen = 32）；上界口径与 max_plaintext 绑定
_OAEP_HLEN = 32

# 解密失败一律报同一句：不让调用方（或攻击者）从文案区分"密钥不对"与"密文被改"
_DECRYPT_FAILED = "解密失败（密钥或密文不匹配）"

# 唯一标记对象：充当 v1.5 的 sentinel。非 bytes 类型，故不会与任何真实明文混淆
_FAIL = object()


class _RsaCipher(PublicKeyCipher):
    """RSA 公钥加解密；填充细节交给库，异常一律归一为 KeyFormatError。

    WHY 三条实现细节（都由实测确定，不是照抄文档）：
    - 公钥/私钥解析失败与填充失败的文案**分开**：前者是调用方传参问题（可修），
      后者才涉及密文——但两者都不含密钥内容或明文字节；
    - v1.5 的失败信号**不是**文档写的 sentinel：实测（pycryptodomex，30/30）
      填充校验不过时返回**空字节**；密文长度不符或 c ≥ n 时才抛 ValueError。
      两条路径都不抛异常，故必须显式判空 + 归一 ValueError，否则会把
      "填充错误"当成成功解出（等于把随机垃圾当明文返回）；
    - 空字节与"合法空明文"在 v1.5 下本来不可区分，故 encrypt 侧**禁止空明文**，
      让空输出唯一地表示失败——这是消除歧义，不是绕过检查。
    """

    def __init__(self, name: str, bits: int, padding: str,
                 standard: str, legacy: bool):
        self.name, self._bits, self._padding = name, bits, padding
        self.provider, self.standard, self.legacy = PROVIDER, standard, legacy

    def _pad(self, key_obj: Any) -> Any:
        from Cryptodome.Cipher import PKCS1_OAEP, PKCS1_v1_5
        if self._padding == "OAEP":
            from Cryptodome.Hash import SHA256
            return PKCS1_OAEP.new(key_obj, hashAlgo=SHA256)
        return PKCS1_v1_5.new(key_obj)

    def generate(self) -> tuple[bytes, bytes]:
        from Cryptodome.PublicKey import RSA
        k = RSA.generate(self._bits)
        return k.public_key().export_key(format="DER"), k.export_key(format="DER")

    def max_plaintext(self, public_key: bytes) -> int:
        """明文上限：OAEP = k − 2·hLen − 2；v1.5 = k − 11。密钥不可解析时返回 0。"""
        from Cryptodome.PublicKey import RSA
        try:
            k = RSA.import_key(public_key).size_in_bytes()
        except (ValueError, IndexError, TypeError):
            return 0
        if self._padding == "OAEP":
            return k - 2 * _OAEP_HLEN - 2
        return k - 11

    def encrypt(self, public_key: bytes, plaintext: bytes) -> bytes:
        from Cryptodome.PublicKey import RSA
        if self._padding == "PKCS1_v1_5" and not plaintext:
            raise KeyFormatError(f"{self.name} 不接受空明文（与 v1.5 的失败信号同形）")
        try:
            pub = RSA.import_key(public_key)
        except (ValueError, IndexError, TypeError) as exc:
            raise KeyFormatError(f"{self.name} 公钥不是合法 DER 编码") from exc
        try:
            return self._pad(pub).encrypt(plaintext)
        except ValueError as exc:
            raise KeyFormatError(f"{self.name} 加密失败（明文超过本密钥上限）") from exc

    def decrypt(self, secret_key: bytes, ciphertext: bytes) -> bytes:
        from Cryptodome.PublicKey import RSA
        try:
            priv = RSA.import_key(secret_key)
        except (ValueError, IndexError, TypeError) as exc:
            raise KeyFormatError(f"{self.name} 私钥不是合法 DER 编码") from exc
        pad = self._pad(priv)
        if self._padding == "OAEP":
            try:
                return pad.decrypt(ciphertext)
            except ValueError as exc:
                raise KeyFormatError(f"{self.name} {_DECRYPT_FAILED}") from exc
        try:
            out = pad.decrypt(ciphertext, _FAIL)
        except ValueError as exc:                # 长度不符 / c ≥ n
            raise KeyFormatError(f"{self.name} {_DECRYPT_FAILED}") from exc
        if out is _FAIL or not out:              # 填充失败（本版本返回空字节）
            raise KeyFormatError(f"{self.name} {_DECRYPT_FAILED}")
        return out


def build() -> list[Algorithm]:
    """装配 RSA 两档（Cryptodome 可用性已由加载器前置校验）。"""
    return [_RsaCipher(*spec) for spec in _KEYS]


MANIFEST: tuple[tuple[str, str], ...] = tuple(("pubkey", n) for n, *_ in _KEYS)

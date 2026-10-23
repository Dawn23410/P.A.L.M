"""国密 SM4 对称分组密码（128 位分组/密钥，对标 AES-128）。

默认 CBC 模式 + PKCS7 填充 + **每次加密新随机 IV** 前置；提供 base64 文本接口
便于直接落库（ChromaDB 文档/metadata 均为字符串）。

两条边界（都是有意为之，务必知情）：
- **CBC 无认证**：本类不做完整性校验。要抗篡改请用 `MemoryCipher`（带摘要标签）
  或 `vault.encrypt_data`（HMAC-SM3，加密后认证）。
- **解密失败原样返回入参**：为兼容历史明文数据，`decrypt_text` 在 base64/解密
  失败时把输入当作明文返回。这意味着"密文"与"解密失败的密文"不可区分，
  调用方不能把返回非空当成功——需要可判定的失败请用上面两条带认证的路径。
"""
from __future__ import annotations

import base64
import os
from . import backends

_IV_LEN = 16


class Sm4Cipher:
    def __init__(self, key: bytes):
        """只接受密钥：IV 由每次 encrypt 内部随机生成，**不开放给调用方**。

        WHY：曾有一个被完全忽略的 `iv` 形参——调用方以为能固定 IV，实际无效。
        固定 IV 会直接废掉 CBC 的语义安全，所以宁可让它 TypeError，也不留这种坑。
        """
        if len(key) != _IV_LEN:
            raise ValueError("SM4 密钥必须为 16 字节（128 位）")
        self._key = key

    @classmethod
    def from_hex(cls, key_hex: str) -> "Sm4Cipher":
        return cls(bytes.fromhex(key_hex))

    @staticmethod
    def random_key() -> bytes:
        return os.urandom(_IV_LEN)

    # ---- 字节级 ----
    def encrypt_bytes(self, plaintext: bytes) -> bytes:
        iv = os.urandom(_IV_LEN)
        # 底层后端（C 铜锁优先 / 纯 Python gmssl 保底）已含 PKCS7，密文不含 iv
        return iv + backends.sm4_cbc_encrypt(self._key, iv, plaintext)

    def decrypt_bytes(self, ciphertext: bytes) -> bytes:
        iv = ciphertext[:_IV_LEN]
        body = ciphertext[_IV_LEN:]
        return backends.sm4_cbc_decrypt(self._key, iv, body)

    # ---- 文本级（base64，便于落库）----
    def encrypt_text(self, text: str) -> str:
        return base64.b64encode(self.encrypt_bytes(text.encode("utf-8"))).decode("ascii")

    def decrypt_text(self, text: str) -> str:
        try:
            raw = base64.b64decode(text)
            return self.decrypt_bytes(raw).decode("utf-8")
        except Exception:
            # 兼容旧明文数据：base64 解码/解密失败即原样返回
            return text

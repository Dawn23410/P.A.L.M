"""国密 SM2 测试：加解密 / 密钥信封 / 缺钥守卫。

SM2 在本内核只作**公钥加密原语**（密钥信封）使用，不做签名——签名侧的用例
（sign_with_sm3 / verify_with_sm3）已随"不做签名"的范围收缩移除。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from palm_cryptokernel import Sm2Key, Sm4Cipher  # noqa: E402


class Sm2KeyTest(unittest.TestCase):
    def test_generated_key_sizes(self):
        k = Sm2Key.generate()
        self.assertEqual(len(k.private_key), 64, "私钥应为 32 字节 hex")
        self.assertEqual(len(k.public_key), 128, "公钥应为 64 字节 hex（x‖y）")

    def test_encrypt_decrypt_roundtrip(self):
        k = Sm2Key.generate()
        data = b"envelope secret"
        ct = k.encrypt(data)
        self.assertNotEqual(ct, data)
        self.assertEqual(k.decrypt(ct), data)

    def test_from_private_recovers_public_key(self):
        k = Sm2Key.generate()
        self.assertEqual(Sm2Key.from_private(k.private_key).public_key, k.public_key)


class Sm2KeyGuardTest(unittest.TestCase):
    def setUp(self):
        self.full = Sm2Key.generate()

    def test_missing_private_key_raises(self):
        pub_only = Sm2Key(public_key=self.full.public_key)
        with self.assertRaises(ValueError):
            pub_only.decrypt(b"x")

    def test_missing_public_key_raises(self):
        priv_only = Sm2Key(private_key=self.full.private_key)
        with self.assertRaises(ValueError):
            priv_only.encrypt(b"x")


class Sm2EnvelopeTest(unittest.TestCase):
    def test_wrap_and_unwrap_sm4_key(self):
        # 密钥信封：SM2 公钥加密 SM4 密钥，随数据落库；私钥离线保管
        sm2k = Sm2Key.generate()
        sm4_key = Sm4Cipher.random_key()
        wrapped = sm2k.encrypt(sm4_key)
        self.assertEqual(sm2k.decrypt(wrapped), sm4_key)
        # 还原出的 SM4 密钥可正常加解密
        self.assertEqual(Sm4Cipher(sm4_key).decrypt_text(Sm4Cipher(sm4_key).encrypt_text("t")), "t")


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""国密 SM4 测试：GB/T 32907-2016 标准向量 + CBC/base64 接口契约。

标准向量校验法：CBC 在**全零 IV** 下首块密文 == ECB(首块明文)，
故可复用 CBC 接口对拍国标单块 ECB 向量，无需额外暴露 ECB 入口。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from palm_cryptokernel import Sm4Cipher, backends  # noqa: E402

# ── GB/T 32907-2016 附录 A.1 单块标准向量 ──
STD_KEY = bytes.fromhex("0123456789abcdeffedcba9876543210")
STD_PT = bytes.fromhex("0123456789abcdeffedcba9876543210")
STD_CT = bytes.fromhex("681edf34d206965e86b3e94f536e4246")


class Sm4StandardVectorTest(unittest.TestCase):
    def test_single_block_matches_gb_vector(self):
        ct = backends.sm4_cbc_encrypt(STD_KEY, b"\x00" * 16, STD_PT)
        self.assertEqual(
            ct[:16], STD_CT, "SM4 原语与国标 GB/T 32907-2016 向量不符"
        )


class Sm4CipherTest(unittest.TestCase):
    def test_key_must_be_16_bytes(self):
        with self.assertRaises(ValueError):
            Sm4Cipher(b"short")

    def test_random_key_length(self):
        self.assertEqual(len(Sm4Cipher.random_key()), 16)

    def test_from_hex_equivalent_to_raw_key(self):
        enc = Sm4Cipher(STD_KEY).encrypt_text("hello")
        self.assertEqual(Sm4Cipher.from_hex(STD_KEY.hex()).decrypt_text(enc), "hello")

    def test_bytes_roundtrip(self):
        c = Sm4Cipher(Sm4Cipher.random_key())
        self.assertEqual(c.decrypt_bytes(c.encrypt_bytes(b"secret payload")), b"secret payload")

    def test_ciphertext_layout_iv_prefixed(self):
        c = Sm4Cipher(Sm4Cipher.random_key())
        pt = b"0123456789abcdef0123456789abcdef"
        ct = c.encrypt_bytes(pt)
        self.assertNotIn(pt, ct, "密文不应包含明文")
        self.assertGreater(len(ct), 16, "应有 IV 前缀")
        self.assertEqual(len(ct) % 16, 0, "IV + 密文总长应为 16 的整数倍")

    def test_text_roundtrip_unicode(self):
        c = Sm4Cipher(Sm4Cipher.random_key())
        text = "用户偏好：喜欢猫娘 🐱"
        self.assertEqual(c.decrypt_text(c.encrypt_text(text)), text)

    def test_random_iv_yields_distinct_ciphertext(self):
        c = Sm4Cipher(Sm4Cipher.random_key())
        self.assertNotEqual(c.encrypt_text("same"), c.encrypt_text("same"))

    def test_decrypt_text_passes_through_plaintext(self):
        c = Sm4Cipher(Sm4Cipher.random_key())
        self.assertEqual(c.decrypt_text("这不是密文"), "这不是密文")

    def test_wrong_key_does_not_recover_plaintext(self):
        enc = Sm4Cipher(Sm4Cipher.random_key()).encrypt_text("data")
        c2 = Sm4Cipher(Sm4Cipher.random_key())
        self.assertNotEqual(c2.decrypt_text(enc), "data")


if __name__ == "__main__":
    unittest.main(verbosity=2)

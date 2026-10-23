"""MemoryCipher 测试：记忆层落盘加密适配器。

覆盖：四种密钥来源（from_key/from_env/from_key_file/generate）、完整性标签往返、
篡改检测、content_hash 跨进程稳定、旧明文向后兼容。
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from palm_cryptokernel import MemoryCipher  # noqa: E402

KEY = b"0123456789abcdef"  # 16 字节、无 NUL，便于作环境变量往返
ENV = "PALM_CRYPTO_TEST_KEY"


class MemoryCipherConstructTest(unittest.TestCase):
    def test_from_key_requires_16_bytes(self):
        with self.assertRaises(ValueError):
            MemoryCipher.from_key(b"short")

    def test_from_env_hex_form(self):
        os.environ[ENV] = KEY.hex()  # 32 位 hex
        try:
            c = MemoryCipher.from_env(ENV)
            self.assertEqual(c.decrypt_text(c.encrypt_text("x")), "x")
        finally:
            os.environ.pop(ENV, None)

    def test_from_env_raw_form(self):
        os.environ[ENV] = KEY.decode("latin-1")  # 16 字节原始串
        try:
            c = MemoryCipher.from_env(ENV)
            self.assertEqual(c.decrypt_text(c.encrypt_text("x")), "x")
        finally:
            os.environ.pop(ENV, None)

    def test_from_env_missing_raises(self):
        os.environ.pop(ENV, None)
        with self.assertRaises(RuntimeError):
            MemoryCipher.from_env(ENV)

    def test_from_key_file_hex_and_raw_interchangeable(self):
        with tempfile.TemporaryDirectory() as d:
            p_hex = os.path.join(d, "k.hex")
            Path(p_hex).write_text(KEY.hex())
            p_raw = os.path.join(d, "k.bin")
            Path(p_raw).write_bytes(KEY)
            c_hex = MemoryCipher.from_key_file(p_hex)
            c_raw = MemoryCipher.from_key_file(p_raw)
            # 同一密钥的两种落盘形态 → 可互相解密
            self.assertEqual(c_raw.decrypt_text(c_hex.encrypt_text("z")), "z")

    def test_from_key_file_bad_length_raises(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "bad")
            Path(p).write_bytes(b"abc")
            with self.assertRaises(ValueError):
                MemoryCipher.from_key_file(p)

    def test_generate_writes_hex_key_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "mem.key")
            MemoryCipher.generate(key_file=p)
            self.assertEqual(len(Path(p).read_text().strip()), 32)


class MemoryCipherTextTest(unittest.TestCase):
    def setUp(self):
        self.c = MemoryCipher.from_key(KEY)

    def test_roundtrip_with_integrity_tag(self):
        text = "用户偏好：喜欢猫娘"
        enc = self.c.encrypt_text(text)
        self.assertTrue(enc.startswith(MemoryCipher.TAG))
        self.assertEqual(self.c.decrypt_text(enc), text)

    def test_no_tag_when_integrity_disabled(self):
        c = MemoryCipher.from_key(KEY, integrity=False)
        enc = c.encrypt_text("text")
        self.assertFalse(enc.startswith(MemoryCipher.TAG))
        self.assertEqual(c.decrypt_text(enc), "text")

    def test_tampered_ciphertext_returns_empty(self):
        enc = self.c.encrypt_text("important")
        tag, _, blob = enc.partition(":")
        tampered = tag + ":" + blob[:-4] + "AAAA"
        self.assertEqual(self.c.decrypt_text(tampered), "", "篡改密文应返回空串")

    def test_tampered_digest_returns_empty(self):
        enc = self.c.encrypt_text("important")
        tag, _, blob = enc.partition(":")
        digest = tag[len(MemoryCipher.TAG):]
        wrong = "00000000" if digest != "00000000" else "11111111"
        self.assertEqual(self.c.decrypt_text(MemoryCipher.TAG + wrong + ":" + blob), "")

    def test_content_hash_stable_and_in_63bit_range(self):
        h1 = self.c.content_hash("同一段文本")
        self.assertEqual(h1, self.c.content_hash("同一段文本"))
        self.assertGreaterEqual(h1, 0)
        self.assertLess(h1, 1 << 63)
        self.assertNotEqual(self.c.content_hash("a"), self.c.content_hash("b"))

    def test_decrypt_passes_through_untagged_plaintext(self):
        self.assertEqual(self.c.decrypt_text("旧明文数据"), "旧明文数据")


if __name__ == "__main__":
    unittest.main(verbosity=2)

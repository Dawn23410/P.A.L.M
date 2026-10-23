"""palm_cryptokernel.backends 测试：后端探测 + 原语契约 + PKCS7 填充。

后端无关：C（tongsuopy/铜锁）与纯 Python（gmssl）行为一致，用例对两者都成立。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from palm_cryptokernel import backends  # noqa: E402
from palm_cryptokernel.vault import operations  # noqa: E402


class BackendContractTest(unittest.TestCase):
    def test_backend_name_and_flag_consistent(self):
        name = backends.backend_name()
        self.assertTrue(name, "后端应被探测出名称")
        self.assertIsInstance(backends.is_c_backend(), bool)
        if backends.is_c_backend():
            self.assertIn("tongsuo", name.lower())
        else:
            self.assertIn("gmssl", name.lower())

    def test_gmssl_layer_available(self):
        # backends 任一后端可用即视为国密底座就绪（vault 启动前置条件）
        self.assertTrue(operations.is_gmssl_available())

    def test_sm3_returns_32_bytes(self):
        self.assertEqual(len(backends.sm3(b"")), 32)
        self.assertEqual(len(backends.sm3(b"hello")), 32)


class HmacSm3Test(unittest.TestCase):
    def test_contract(self):
        k, m = b"key", b"message"
        mac = backends.hmac_sm3(k, m)
        self.assertEqual(len(mac), 32)
        self.assertEqual(mac, backends.hmac_sm3(k, m), "同输入应确定")
        self.assertNotEqual(mac, backends.sm3(m), "HMAC 不应等于裸哈希")
        self.assertNotEqual(mac, backends.hmac_sm3(b"key2", m), "应对密钥敏感")
        self.assertNotEqual(mac, backends.hmac_sm3(k, b"message2"), "应对消息敏感")

    def test_long_key_exceeding_block(self):
        # key 超块长（64B）时应先哈希压缩
        self.assertEqual(len(backends.hmac_sm3(b"k" * 100, b"m")), 32)


class Pkcs7Test(unittest.TestCase):
    def test_roundtrip_all_lengths(self):
        for n in (0, 1, 15, 16, 17, 31, 32, 33):
            data = bytes(range(256))[:n]
            self.assertEqual(backends._pkcs7_unpad(backends._pkcs7_pad(data)), data)

    def test_full_block_adds_whole_block(self):
        self.assertEqual(len(backends._pkcs7_pad(b"x" * 16)), 32)

    def test_unpad_rejects_invalid(self):
        with self.assertRaises(ValueError):
            backends._pkcs7_unpad(b"")
        with self.assertRaises(ValueError):
            backends._pkcs7_unpad(b"short")  # 非 16 倍数
        with self.assertRaises(ValueError):
            backends._pkcs7_unpad(b"\x00" * 16)  # 填充字节取 0 非法


if __name__ == "__main__":
    unittest.main(verbosity=2)

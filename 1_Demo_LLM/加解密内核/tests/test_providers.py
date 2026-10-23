"""公钥族与信封族测试：RSA/SM2 公钥加密 + 公钥信封 + 兼容档摘要 + 缺陷回归。

两条有来历的测试（都对应实现里修过的真实缺陷，改动时别删）：
1. `test_sm2_public_key_starting_with_04` —— gmssl 用 `lstrip("04")` 去前缀，
   会截坏约 0.43% 的 SM2 公钥（x 坐标以 0x04 开头），导致解密静默失败；
2. `test_pkcs1v15_failure_raises_not_returns_none` —— PKCS1_v1_5 解密失败
   **返回 sentinel 而不抛异常**，照抄 try/except 会把随机垃圾当明文返回。

后量子（KEM/ML-KEM）与签名已按范围边界**整体移除**：对应实现、provider、族模块
均已删除，不是"跳过"而是"不存在"。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from palm_cryptokernel import families as f  # noqa: E402
from palm_cryptokernel.errors import AEADError, CryptoError, KeyFormatError  # noqa: E402


class Sm2DefectRegressionTest(unittest.TestCase):
    """SM2 公钥截短缺陷的回归（详见模块 docstring）。"""

    @staticmethod
    def _find_key_with_04_prefix(limit: int = 30000):
        """找一个派生公钥恰以 "04" 开头的私钥（概率约 0.43%）。"""
        from palm_cryptokernel.sm2 import Sm2Key
        for i in range(limit):
            priv = "%064x" % (0x1000000000000000000000000000000000000000000000000000000000000000 + i)
            key = Sm2Key.from_private(priv)
            if key.public_key.startswith("04"):
                return key
        return None

    def test_sm2_public_key_starting_with_04(self):
        """回归：gmssl 的 lstrip("04") 会截短此类公钥，导致解密静默失败。"""
        key = self._find_key_with_04_prefix()
        if key is None:
            self.skipTest("未能在给定范围内构造出 04 前缀公钥")
        pub, sec = bytes.fromhex(key.public_key), bytes.fromhex(key.private_key)
        self.assertEqual(len(pub), 64, "公钥应保持 64 字节未被 lstrip 截短")
        self.assertEqual(
            f.pubkey.decrypt("sm2", sec, f.pubkey.encrypt("sm2", pub, b"short")), b"short")


class PublicKeyCipherTest(unittest.TestCase):
    def test_roundtrip_all(self):
        for name in ("rsa-oaep", "rsa-pkcs1v15", "sm2"):
            with self.subTest(algorithm=name):
                pub, sec = f.pubkey.generate(name)
                self.assertEqual(
                    f.pubkey.decrypt(name, sec, f.pubkey.encrypt(name, pub, b"short")), b"short")

    def test_rsa_plaintext_bound_matches_padding(self):
        """OAEP-SHA256 上限 = k−66，PKCS#1 v1.5 = k−11（k=256 时为 190 / 245）。"""
        self.assertEqual(f.pubkey.max_plaintext("rsa-oaep", f.pubkey.generate("rsa-oaep")[0]), 190)
        self.assertEqual(
            f.pubkey.max_plaintext("rsa-pkcs1v15", f.pubkey.generate("rsa-pkcs1v15")[0]), 245)

    def test_oversized_plaintext_rejected(self):
        pub, _ = f.pubkey.generate("rsa-oaep")
        with self.assertRaises(KeyFormatError):
            f.pubkey.encrypt("rsa-oaep", pub, b"x" * 200)

    def test_pkcs1v15_failure_is_normalized_to_error(self):
        """回归：v1.5 的失败**不抛异常**（实测返回空字节；长度不符才抛 ValueError）——
        两条路径都必须归一成 KeyFormatError，绝不能把垃圾当明文返回。"""
        pub_a, sec_a = f.pubkey.generate("rsa-pkcs1v15")
        ct = f.pubkey.encrypt("rsa-pkcs1v15", pub_a, b"secret")
        cases = {
            "篡改密文": (sec_a, ct[:-1] + bytes([ct[-1] ^ 1])),
            "密文过短": (sec_a, ct[:-1]),
        }
        for label, (sk, bad) in cases.items():
            with self.subTest(case=label):
                with self.assertRaises(KeyFormatError):
                    f.pubkey.decrypt("rsa-pkcs1v15", sk, bad)
        # 错私钥：可能走空字节路径，也可能走 ValueError（c ≥ n），二者都要归一
        for _ in range(4):
            _, sec_b = f.pubkey.generate("rsa-pkcs1v15")
            with self.assertRaises(KeyFormatError):
                f.pubkey.decrypt("rsa-pkcs1v15", sec_b, ct)

    def test_pkcs1v15_rejects_empty_plaintext(self):
        """空明文与失败信号同形，故 encrypt 侧直接拒绝——这是消除歧义。"""
        pub, _ = f.pubkey.generate("rsa-pkcs1v15")
        with self.assertRaises(KeyFormatError):
            f.pubkey.encrypt("rsa-pkcs1v15", pub, b"")

    def test_bad_der_key_rejected(self):
        with self.assertRaises(KeyFormatError):
            f.pubkey.encrypt("rsa-oaep", b"not-a-der-key", b"x")

    def test_sm2_key_length_enforced(self):
        with self.assertRaises(KeyFormatError):
            f.pubkey.encrypt("sm2", b"short", b"x")


class EnvelopeTest(unittest.TestCase):
    """公钥信封：公钥封装数据密钥 + AEAD 加密正文。"""

    TEXT = "混合信封的正文可以任意长".encode()
    AAD = "记录ID=42".encode()

    def test_default_pair_roundtrip(self):
        pub, sec = f.envelope.generate()
        blob = f.envelope.seal(pub, self.TEXT, aad=self.AAD)
        self.assertEqual(f.envelope.open(sec, blob, aad=self.AAD), self.TEXT)

    def test_header_is_self_describing(self):
        pub, _ = f.envelope.generate()
        head = f.envelope.peek(f.envelope.seal(pub, b"x"))
        self.assertEqual((head["version"], head["pubkey"], head["aead"]),
                         (2, "sm2", "aes-256-gcm"))
        self.assertEqual(head["sealed_size"], 1 + 16)   # 明文 1 字节 + GCM 标签

    def test_mixed_pair_with_rsa_still_opens(self):
        pub, sec = f.envelope.generate("rsa-oaep")
        blob = f.envelope.seal(pub, b"pq", pubkey="rsa-oaep", aead="chacha20-poly1305")
        self.assertEqual(f.envelope.open(sec, blob), b"pq")
        self.assertEqual(f.envelope.peek(blob)["pubkey"], "rsa-oaep")

    def test_data_key_and_nonce_are_per_message(self):
        """同一公钥连发两条：数据密钥与 nonce 都必须不同（防复用）。"""
        import struct
        pub, sec = f.envelope.generate()
        b1, b2 = f.envelope.seal(pub, b"same"), f.envelope.seal(pub, b"same")
        h1, h2 = f.envelope.peek(b1), f.envelope.peek(b2)
        self.assertNotEqual(b1, b2)
        # nonce 在「头(8B) + pubkey 名 + aead 名」之后，按真实偏移比对
        off = struct.calcsize(">4sBBBB") + len("sm2") + len('aes-256-gcm')
        n1 = b1[off:off + h1["nonce_size"]]
        n2 = b2[off:off + h2["nonce_size"]]
        self.assertEqual(len(n1), h1["nonce_size"])
        self.assertNotEqual(n1, n2, "两条报文的 nonce 不得相同")
        # 封装后的数据密钥也必须不同（SM2 密文含随机量）
        w_off = off + h1["nonce_size"] + 2
        w1 = b1[w_off:w_off + h1["wrapped_key_size"]]
        w2 = b2[w_off:w_off + h2["wrapped_key_size"]]
        self.assertNotEqual(w1, w2, "两条报文封装的数据密钥不得相同")
        self.assertEqual(f.envelope.open(sec, b1), f.envelope.open(sec, b2))

    def test_negatives(self):
        pub, sec = f.envelope.generate()
        blob = f.envelope.seal(pub, b"x", aad=b"A")
        with self.assertRaises(AEADError):
            f.envelope.open(sec, blob, aad=b"B")             # AAD 不符
        with self.assertRaises(CryptoError):
            f.envelope.open(f.envelope.generate()[1], blob)  # 错私钥
        with self.assertRaises(KeyFormatError):
            f.envelope.open(sec, b"NOTPKEN" + b"\x00" * 16)  # magic 不符
        with self.assertRaises(CryptoError):
            f.envelope.open(sec, blob[:20])                  # 截断
        with self.assertRaises(CryptoError):
            f.envelope.open(sec, blob[:-1])                  # 尾部截断

    def test_recommend_pair_shape(self):
        pair = f.envelope.recommend_pair()
        self.assertEqual(set(pair), {"pubkey", "aead"})
        self.assertEqual(pair["pubkey"], "sm2")              # 默认国密


class DigestSetTest(unittest.TestCase):
    """摘要集：sm3 / sha256 / sha512；弱摘要槽位已移除（v0.5.2）。"""

    def test_weak_digests_removed(self):
        from palm_cryptokernel.errors import AlgorithmNotFound
        for name in ("md5", "sha1"):
            with self.subTest(algorithm=name):
                self.assertNotIn(name, f.hash.names())
                with self.assertRaises(AlgorithmNotFound):
                    f.hash.digest(name, b"abc")

    def test_registered_digests_match_stdlib(self):
        import hashlib
        for name, data in (("sha256", b"abc"), ("sha512", b"abc")):
            with self.subTest(algorithm=name):
                self.assertEqual(f.hash.digest(name, data), hashlib.new(name, data).digest())


class LegacyCompatibilityTest(unittest.TestCase):
    """旧接口必须原样可用（app 侧 v0.2 调用面回归）。"""

    def test_legacy_exports_present(self):
        import palm_cryptokernel as p
        for attr in ("sm3_hash", "sm3_int", "Sm4Cipher", "Sm2Key",
                     "MemoryCipher", "vault", "backends"):
            self.assertTrue(hasattr(p, attr), f"旧接口 {attr} 丢失")
            self.assertIn(attr, p.__all__)
        self.assertEqual(p.__version__, "0.5.2")

    def test_legacy_memory_cipher_roundtrip(self):
        from palm_cryptokernel import MemoryCipher
        c = MemoryCipher.from_key(b"0" * 16)
        self.assertEqual(c.decrypt_text(c.encrypt_text("记忆正文")), "记忆正文")
        # 篡改正文应被完整性标签拦下（返回空串而非错误内容）
        blob = c.encrypt_text("记忆正文")
        self.assertEqual(c.decrypt_text(blob[:-4] + "AAAA"), "")

    def test_legacy_sm4_cipher_roundtrip(self):
        from palm_cryptokernel import Sm4Cipher
        key = Sm4Cipher.random_key()
        c = Sm4Cipher(key)
        self.assertEqual(c.decrypt_text(c.encrypt_text("落盘正文")), "落盘正文")

    def test_new_api_and_legacy_share_bytes(self):
        """新旧路径对同一 (key, iv, 明文) 必须产出相同密文，否则存量数据会读不回。"""
        from palm_cryptokernel import backends
        key, iv, data = b"k" * 16, b"i" * 16, b"legacy-compatible"
        self.assertEqual(
            f.cipher.encrypt("sm4-cbc", key, iv, data),
            backends.sm4_cbc_encrypt(key, iv, data))


if __name__ == "__main__":
    unittest.main(verbosity=2)

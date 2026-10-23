"""内核契约测试：ABC 端口 / 注册表 / 能力清单 / 六族的正负样本。

与既有 test_sm2|sm3|sm4|vault 的分工：那几本管**国密算法的正确性**（国标向量），
本本管**内核架构的契约**——族与 ABC 的对应关系、择优规则、能力披露的诚实性、
以及各族接口的往返与"必须被拒绝"的负样本。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from palm_cryptokernel import capabilities  # noqa: E402
from palm_cryptokernel import families as f  # noqa: E402
from palm_cryptokernel import suite  # noqa: E402
from palm_cryptokernel.abcs import (  # noqa: E402
    AEADAlgorithm,
    CipherAlgorithm,
    HashAlgorithm,
    KDFAlgorithm,
    MACAlgorithm,
    PublicKeyCipher,
)
from palm_cryptokernel.errors import AEADError, AlgorithmNotFound, CryptoError  # noqa: E402
from palm_cryptokernel.registry import registry  # noqa: E402

# 族标识 → 该族必须实现的 ABC（架构契约的唯一真源）
FAMILY_ABC = {
    "hash": HashAlgorithm,
    "mac": MACAlgorithm,
    "kdf": KDFAlgorithm,
    "cipher": CipherAlgorithm,
    "aead": AEADAlgorithm,
    "pubkey": PublicKeyCipher,
}


class AbcContractTest(unittest.TestCase):
    """每个注册项都必须是对应族 ABC 的实例，且元信息自洽。"""

    def test_all_registered_are_family_instances(self):
        for family, abc in FAMILY_ABC.items():
            impls = registry.all_of(family)
            self.assertTrue(impls, f"{family} 族无任何实现")
            for algo in impls:
                self.assertIsInstance(algo, abc, f"{algo.name} 未实现 {abc.__name__}")
                self.assertEqual(algo.family, family)
                self.assertTrue(algo.name and algo.provider and algo.standard,
                                f"{algo.name} 元信息不完整：{algo.spec}")

    def test_spec_has_audit_fields(self):
        spec = registry.get("aead", "aes-256-gcm").spec
        self.assertEqual(set(spec), {"name", "family", "provider", "standard", "legacy"})

    def test_labels_cover_every_family(self):
        labels = suite.labels()
        for family in registry.families():
            self.assertIn(family, labels, f"{family} 缺中文标签")


class RegistryTest(unittest.TestCase):
    def test_unknown_algorithm_raises(self):
        with self.assertRaises(AlgorithmNotFound):
            registry.get("aead", "aes-1024-gcm")

    def test_unknown_family_raises(self):
        with self.assertRaises(AlgorithmNotFound):
            registry.get("nonsense", "whatever")

    def test_priority_prefers_c_backend(self):
        """同一算法多实现时，择优结果必须是优先级最高的 provider。"""
        for family in registry.families():
            for name in registry.names(family):
                impls = [a for a in registry.all_of(family) if a.name == name]
                winner = registry.get(family, name)
                self.assertEqual(winner, impls[0], f"{family}/{name} 未按优先级择优")
        # SM3 同时有 hashlib(80) 与 gmssl(50) 两条通道，应优选 hashlib
        self.assertEqual(registry.provider_of("hash", "sm3"), "hashlib")

    def test_names_sorted_and_stable(self):
        names = registry.names("hash")
        self.assertEqual(names, sorted(names))
        self.assertEqual(names, registry.names("hash"))

    def test_all_families_loaded(self):
        self.assertEqual(set(registry.families()), set(FAMILY_ABC))


class CapabilitiesTest(unittest.TestCase):
    def test_counts_match_available_matrix(self):
        report = suite.capabilities()
        for family, entries in report["available"].items():
            self.assertEqual(report["counts"][family], len(entries))
        self.assertEqual(report["total"], sum(report["counts"].values()))

    def test_names_are_deduplicated_across_providers(self):
        """同一算法多 provider 只能算一条——否则"算法数"会被重复实现灌水。"""
        for family, entries in suite.capabilities()["available"].items():
            names = [e["name"] for e in entries]
            self.assertEqual(len(names), len(set(names)), f"{family} 存在重名条目")
            for entry in entries:
                self.assertEqual(len(entry["providers"]), entry["total_implementations"])

    def test_providers_status_reports_availability(self):
        status = suite.capabilities()["providers"]
        self.assertIn("cryptodome", status)
        self.assertIn("hashlib", status)          # 标准库，必定可用
        self.assertTrue(status["hashlib"]["available"])
        for name, entry in status.items():
            if not entry["available"]:
                self.assertTrue(entry["reason"], f"{name} 不可用但未说明原因")

    def test_capability_export_shape(self):
        cap = capabilities.capability()
        self.assertEqual(cap["module"], "palm_cryptokernel")
        self.assertGreater(cap["algorithm_count"], 0)
        self.assertEqual(cap["absent_count"], len(suite.gaps()))

    def test_recommended_is_available(self):
        for family in registry.families():
            name = suite.recommended(family)
            self.assertIn(name, registry.names(family))


class HashFamilyTest(unittest.TestCase):
    def test_sha256_standard_vector(self):
        self.assertEqual(
            f.hash.hexdigest("sha256", b"abc"),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")

    def test_sm3_standard_vector(self):
        """GB/T 32905-2016 附录 A 示例：SM3("abc")。"""
        self.assertEqual(
            f.hash.hexdigest("sm3", b"abc"),
            "66c7f0f462eeedd9d1f2d46bdc10e4e24167c4875cf2f7a2297da02b8f4ba8e0")

    def test_cross_provider_agreement(self):
        """同一算法不同 provider 必须逐字节一致（换后端不影响存量指纹）。"""
        from palm_cryptokernel.registry import registry as reg
        impls = [a for a in reg.all_of("hash") if a.name == "sm3"]
        self.assertGreaterEqual(len(impls), 2, "SM3 应有两条独立通道作对拍")
        digests = {a.digest(b"cross-provider") for a in impls}
        self.assertEqual(len(digests), 1, f"SM3 各通道结果不一致：{digests}")

    def test_str_and_bytes_equivalent(self):
        self.assertEqual(f.hash.digest("sm3", "同源"), f.hash.digest("sm3", "同源".encode()))

    def test_fingerprint_length_and_rejection(self):
        self.assertEqual(len(f.hash.fingerprint(b"x", size=8)), 16)   # 8 字节 → 16 hex
        from palm_cryptokernel.errors import KeyFormatError
        with self.assertRaises(KeyFormatError):
            f.hash.fingerprint(b"x", algorithm="sha256", size=999)

    def test_matches_is_constant_time_compare(self):
        good = f.hash.digest("sha256", b"a")
        self.assertTrue(f.hash.matches("sha256", b"a", good))
        self.assertFalse(f.hash.matches("sha256", b"b", good))

    def test_weak_digests_absent(self):
        """弱摘要（md5/sha1）已整体移除：宁可缺，也不留一个"迟早会被调用"的槽位。"""
        self.assertNotIn("md5", f.hash.names())
        self.assertNotIn("sha1", f.hash.names())
        self.assertIsNone(registry.provider_of("hash", "md5"))
        self.assertIsNone(registry.provider_of("hash", "sha1"))
        with self.assertRaises(AlgorithmNotFound):
            f.hash.digest("md5", b"abc")
        self.assertFalse(registry.get("hash", "sha256").legacy)

    def test_include_legacy_is_still_a_contract(self):
        """`include_legacy` 参数保留为接口契约：当前无 legacy 档，两种取法结果相同。"""
        self.assertEqual(sorted(f.hash.names()),
                         sorted(f.hash.names(include_legacy=False)))
        self.assertTrue(all(not registry.get("hash", n).legacy for n in f.hash.names()))


class MacFamilyTest(unittest.TestCase):
    def test_hmac_sha256_rfc4231_case1(self):
        tag = f.mac.compute("hmac-sha256", b"\x0b" * 20, b"Hi There")
        self.assertEqual(
            tag.hex(),
            "b0344c61d8db38535ca8afceaf0bf12b881dc200c9833da726e9376c2e32cff7")

    def test_hmac_sm3_matches_legacy_backend(self):
        """与既有 backends.hmac_sm3 对拍，确保内核换装不改变历史 MAC。"""
        from palm_cryptokernel import backends
        key, msg = b"k" * 32, b"payload"
        self.assertEqual(f.mac.compute("hmac-sm3", key, msg), backends.hmac_sm3(key, msg))

    def test_verify_rejects_tampered_tag(self):
        tag = f.mac.compute("hmac-sm3", b"k" * 32, b"m")
        self.assertTrue(f.mac.verify("hmac-sm3", b"k" * 32, b"m", tag))
        self.assertFalse(f.mac.verify("hmac-sm3", b"k" * 32, b"m", bytes(32)))
        self.assertFalse(f.mac.verify("hmac-sm3", b"k" * 32, b"m!", tag))


class KdfFamilyTest(unittest.TestCase):
    def test_hkdf_deterministic_and_salt_sensitive(self):
        a = f.kdf.derive("hkdf", b"secret", 32, salt=b"s" * 16, info=b"i")
        self.assertEqual(a, f.kdf.derive("hkdf", b"secret", 32, salt=b"s" * 16, info=b"i"))
        self.assertNotEqual(a, f.kdf.derive("hkdf", b"secret", 32, salt=b"t" * 16, info=b"i"))
        self.assertNotEqual(a, f.kdf.derive("hkdf", b"secret", 32, salt=b"s" * 16, info=b"j"))

    def test_password_kdfs_are_memory_hard(self):
        for name in ("argon2id", "pbkdf2"):
            self.assertTrue(f.kdf.is_memory_hard(name), f"{name} 应判为抗 GPU")

    def test_password_kdfs_honour_requested_length(self):
        for name in ("argon2id", "pbkdf2"):
            with self.subTest(kdf=name):
                self.assertEqual(len(f.kdf.derive(name, b"pw", 32, salt=b"s" * 16)), 32)

    def test_password_kdf_is_salt_sensitive(self):
        a = f.kdf.derive("argon2id", b"pw", 32, salt=b"s" * 16)
        self.assertNotEqual(a, f.kdf.derive("argon2id", b"pw", 32, salt=b"t" * 16))

    def test_expansion_kdf_not_memory_hard(self):
        self.assertFalse(f.kdf.is_memory_hard("hkdf"))


class CipherFamilyTest(unittest.TestCase):
    MODES = ("aes-256-cbc", "sm4-cbc")

    def test_roundtrip_all_modes(self):
        for name in self.MODES:
            with self.subTest(mode=name):
                key, iv = f.cipher.generate_key(name), f.cipher.new_iv(name)
                data = b"x" * 40
                self.assertEqual(
                    f.cipher.decrypt(name, key, iv, f.cipher.encrypt(name, key, iv, data)),
                    data)

    def test_cbc_padding_applied(self):
        """CBC 必须自行 PKCS7——非整块长度不该报错，且密文补齐到 16 字节倍数。"""
        ct = f.cipher.encrypt("aes-256-cbc", b"k" * 32, b"i" * 16, b"short")
        self.assertEqual(len(ct) % 16, 0)
        self.assertEqual(f.cipher.decrypt("aes-256-cbc", b"k" * 32, b"i" * 16, ct), b"short")

    def test_packed_roundtrip_and_short_input(self):
        packed = f.cipher.encrypt_packed("sm4-cbc", "中文正文".encode())
        from palm_cryptokernel.errors import KeyFormatError
        self.assertEqual(len(packed) % 16, 0)
        with self.assertRaises(KeyFormatError):
            f.cipher.decrypt_packed("sm4-cbc", b"k" * 16, b"\x00")

    def test_iv_length_enforced(self):
        from palm_cryptokernel.errors import KeyFormatError
        with self.assertRaises(KeyFormatError):
            f.cipher.encrypt("aes-256-cbc", b"k" * 32, b"iv", b"x")


class AeadFamilyTest(unittest.TestCase):
    MODES = ("aes-256-gcm", "chacha20-poly1305")

    def test_roundtrip_all_modes_with_aad(self):
        for name in self.MODES:
            with self.subTest(mode=name):
                key = f.aead.generate_key(name)
                nonce = f.aead.new_nonce_for(name)
                sealed = f.aead.seal(name, key, nonce, b"payload", aad=b"ctx")
                self.assertEqual(f.aead.open(name, key, nonce, sealed, aad=b"ctx"), b"payload")

    def test_sealed_excludes_nonce(self):
        key, nonce = f.aead.generate_key("aes-256-gcm"), f.aead.new_nonce_for("aes-256-gcm")
        sealed = f.aead.seal("aes-256-gcm", key, nonce, b"abc")
        self.assertEqual(len(sealed), len(b"abc") + f.aead.tag_size("aes-256-gcm"))

    def test_rejects_tampered_ciphertext(self):
        key, nonce = b"k" * 32, b"0" * 12
        sealed = f.aead.seal("aes-256-gcm", key, nonce, b"payload")
        with self.assertRaises(AEADError):
            f.aead.open("aes-256-gcm", key, nonce, sealed[:-1] + bytes([sealed[-1] ^ 1]))

    def test_rejects_wrong_aad_and_wrong_key(self):
        sealed = f.aead.seal("aes-256-gcm", b"k" * 32, b"0" * 12, b"payload", aad=b"A")
        for key, aad in ((b"k" * 32, b"B"), (b"z" * 32, b"A")):
            with self.subTest(key=key[:1], aad=aad):
                with self.assertRaises(AEADError):
                    f.aead.open("aes-256-gcm", key, b"0" * 12, sealed, aad=aad)

    def test_short_sealed_rejected(self):
        with self.assertRaises(AEADError):
            f.aead.open("aes-256-gcm", b"k" * 32, b"0" * 12, b"too-short")

    def test_packed_roundtrip(self):
        packed = f.aead.seal_packed("chacha20-poly1305", b"k" * 32, "正文".encode())
        self.assertEqual(
            f.aead.open_packed("chacha20-poly1305", b"k" * 32, packed), "正文".encode())


if __name__ == "__main__":
    unittest.main(verbosity=2)

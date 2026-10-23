"""palm_cryptokernel.vault 测试：密钥库装配 / 数据与文件加解密 / 指纹密封 / 篡改拒绝。

设计：
- 数据目录重钉到**临时目录**，不污染 ~/.加解密内核；
- 主密钥直接 set_master_key() 注入，使加解密用例**不依赖真实硬件指纹**；
- boot() 依赖本机指纹，取不到时整体跳过（打印 SKIP，不误报红）。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from palm_cryptokernel import vault  # noqa: E402
from palm_cryptokernel.vault import file_ops, operations  # noqa: E402

TEST_MASTER = b"0123456789abcdef"


class VaultBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="palmcrypto_vault_")
        self._saved_dir = vault.get_data_dir()
        self._saved_master = vault.get_master_key()
        vault.set_data_dir(self.tmp)
        vault.set_master_key(TEST_MASTER)

    def tearDown(self):
        vault.set_master_key(self._saved_master)
        vault.set_data_dir(self._saved_dir)
        shutil.rmtree(self.tmp, ignore_errors=True)


class DataCryptoTest(VaultBase):
    def test_roundtrip(self):
        payload = b"\x00\x01 \xe6\x9c\xba\xe5\xaf\x86 payload"
        ct = vault.encrypt_data(payload)
        self.assertNotEqual(ct, payload)
        self.assertEqual(vault.decrypt_data(ct), payload)

    def test_package_layout(self):
        # iv(16) + 密文(16 倍数) + hmac_sm3(32)
        ct = vault.encrypt_data(b"x" * 10)
        self.assertGreaterEqual(len(ct), 16 + 16 + 32)
        self.assertEqual((len(ct) - 16 - 32) % 16, 0)

    def test_tamper_rejected(self):
        ct = bytearray(vault.encrypt_data(b"important"))
        ct[-1] ^= 0xFF  # 破坏尾部 HMAC
        with self.assertRaises(ValueError):
            vault.decrypt_data(bytes(ct))

    def test_too_short_rejected(self):
        with self.assertRaises(ValueError):
            vault.decrypt_data(b"short")

    def test_requires_master_key(self):
        vault.set_master_key(None)
        with self.assertRaises(RuntimeError):
            vault.encrypt_data(b"x")


class KeystoreSealTest(VaultBase):
    def test_seal_unseal_roundtrip(self):
        fp = "test-fingerprint"
        pkg = operations.seal_keystore(b"\x01" * 16, fp)
        self.assertEqual(operations.unseal_keystore(pkg, fp), b"\x01" * 16)

    def test_unseal_rejects_wrong_fingerprint(self):
        pkg = operations.seal_keystore(b"\x02" * 16, "fp-A")
        with self.assertRaises(ValueError):
            operations.unseal_keystore(pkg, "fp-B")  # 换机 → 校验失败

    def test_unseal_rejects_too_short(self):
        with self.assertRaises(ValueError):
            operations.unseal_keystore(b"short", "fp")

    def test_derive_key_deterministic_and_salt_sensitive(self):
        k1 = operations.derive_key("fp", b"salt" * 4)
        self.assertEqual(k1, operations.derive_key("fp", b"salt" * 4))
        self.assertEqual(len(k1), 16)
        self.assertNotEqual(k1, operations.derive_key("fp", b"other-salt00"))

    def test_recovery_checksum_is_8_hex_and_stable(self):
        cs = vault.recovery_checksum()
        self.assertEqual(len(cs), 8)
        self.assertTrue(all(c in "0123456789abcdef" for c in cs))
        self.assertEqual(cs, vault.recovery_checksum())


class FileCryptoTest(VaultBase):
    def test_file_roundtrip_default_output(self):
        src = os.path.join(self.tmp, "secret.txt")
        Path(src).write_bytes("file content 机密".encode("utf-8"))
        enc = vault.encrypt_file(src)
        self.assertTrue(enc.endswith(".enc"))
        self.assertNotEqual(Path(enc).read_bytes(), "file content 机密".encode("utf-8"))
        out = vault.decrypt_file(enc)
        self.assertEqual(Path(out).read_bytes(), "file content 机密".encode("utf-8"))

    def test_file_roundtrip_explicit_output(self):
        src = os.path.join(self.tmp, "a.bin")
        Path(src).write_bytes(b"\x00\x01\x02")
        enc = vault.encrypt_file(src)
        out = os.path.join(self.tmp, "restored.bin")
        vault.decrypt_file(enc, out)
        self.assertEqual(Path(out).read_bytes(), b"\x00\x01\x02")

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            vault.encrypt_file(os.path.join(self.tmp, "nope.txt"))

    def test_path_traversal_rejected(self):
        # 相对路径的前导 .. 不会被 normpath 消解 → 触发守卫
        with self.assertRaises(ValueError):
            file_ops._safe_path(os.path.join("..", "..", "no_such_file"))

    def test_directory_rejected(self):
        sub = os.path.join(self.tmp, "adir")
        os.makedirs(sub, exist_ok=True)
        with self.assertRaises(ValueError):
            vault.encrypt_file(sub)


class BootTest(VaultBase):
    def test_boot_binds_and_encrypts(self):
        vault.boot()
        if not vault.is_bound():
            self.skipTest("硬件指纹不可用（boot 降级）—— 跳过绑定用例")
        self.assertEqual(len(vault.fingerprint_prefix()), 16)
        self.assertFalse(vault.is_enabled(), "加密开关默认关闭")
        self.assertEqual(vault.decrypt_data(vault.encrypt_data(b"xyz")), b"xyz")

    def test_set_enabled_persists(self):
        keys_dir = os.path.join(self.tmp, ".keys")
        os.makedirs(keys_dir, exist_ok=True)
        vault.set_enabled(True)
        self.assertTrue(vault.is_enabled())
        state = json.loads(Path(keys_dir, ".crypto_state.json").read_text(encoding="utf-8"))
        self.assertTrue(state["enabled"], "开关状态应落盘")
        vault.set_enabled(False)
        self.assertFalse(vault.is_enabled())


if __name__ == "__main__":
    unittest.main(verbosity=2)

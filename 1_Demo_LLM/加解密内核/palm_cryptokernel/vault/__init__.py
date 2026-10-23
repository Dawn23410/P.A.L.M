"""palm_cryptokernel.vault —— 密钥库/文件级加解密/硬件指纹（统一加解密模块）。

自 P.A.L.M `palm/adapters/crypto` 收敛而来，与国密原语（sm2/sm3/sm4）同包：
- operations  ：主密钥 SM4-CBC + HMAC-SM3 完整性；密钥库密封/解封
- keystore    ：主密钥装配生命周期（boot/is_bound/is_locked/is_enabled）
- fingerprint ：主板级硬件指纹（密钥库密封要素）
- file_ops    ：文件级 encrypt_file/decrypt_file（含路径安全检查）

数据位置：PALM_CRYPTO_HOME（env）或 ~/.palm_cryptokernel；set_data_dir() 可重钉。
"""
from __future__ import annotations

from .file_ops import decrypt_file, encrypt_file
from .fingerprint import get_machine_fingerprint
from .keystore import (
    boot,
    fingerprint_prefix,
    is_bound,
    is_enabled,
    is_locked,
    set_enabled,
)
from .operations import (
    decrypt_data,
    derive_key,
    encrypt_data,
    ensure_checksum,
    get_data_dir,
    get_master_key,
    is_gmssl_available,
    recovery_checksum,
    seal_keystore,
    set_data_dir,
    set_master_key,
    unseal_keystore,
)

__all__ = [
    # operations
    "encrypt_data", "decrypt_data", "seal_keystore", "unseal_keystore",
    "derive_key", "set_master_key", "get_master_key", "is_gmssl_available",
    "ensure_checksum", "recovery_checksum", "set_data_dir", "get_data_dir",
    # keystore
    "boot", "is_bound", "is_locked", "is_enabled", "set_enabled", "fingerprint_prefix",
    # fingerprint
    "get_machine_fingerprint",
    # file_ops
    "encrypt_file", "decrypt_file",
]

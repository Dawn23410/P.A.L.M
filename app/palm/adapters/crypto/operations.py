"""薄桥接层：SM4 加解密原语 —— 实现已并入独立包 palm_crypto（`palm_crypto.vault.operations`）。

统一加解密模块收敛后本文件仅做再导出；真实实现（主密钥 SM4-CBC + HMAC-SM3 完整性 +
密钥库密封/解封）见 palm-crypto/palm_crypto/vault/operations.py。
"""
from __future__ import annotations

import palm_boot  # noqa: E402,F401  自举：挂载内嵌项目
from palm_crypto.vault.operations import (  # noqa: F401
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

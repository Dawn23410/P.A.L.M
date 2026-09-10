"""薄桥接层：加密芯片密钥库 —— 实现已并入独立包 palm_crypto（`palm_crypto.vault.keystore`）。

统一加解密模块收敛后本文件仅做再导出；真实实现（主密钥装配生命周期：boot /
is_bound / is_locked / is_enabled / set_enabled / fingerprint_prefix）见
palm-crypto/palm_crypto/vault/keystore.py。
"""
from __future__ import annotations

import palm_boot  # noqa: E402,F401  自举：挂载内嵌项目
from palm_crypto.vault.keystore import (  # noqa: F401
    boot,
    fingerprint_prefix,
    is_bound,
    is_enabled,
    is_locked,
    set_enabled,
)

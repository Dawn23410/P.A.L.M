"""薄桥接层：文件级加解密 —— 实现已并入独立包 palm_crypto（`palm_crypto.vault.file_ops`）。"""
from __future__ import annotations

import palm_boot  # noqa: E402,F401  自举：挂载内嵌项目
from palm_crypto.vault.file_ops import decrypt_file, encrypt_file  # noqa: F401

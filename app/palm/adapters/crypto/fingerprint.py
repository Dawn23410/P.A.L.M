"""薄桥接层：本机硬件指纹采集 —— 实现已并入独立包 palm_crypto（`palm_crypto.vault.fingerprint`）。"""
from __future__ import annotations

import palm_boot  # noqa: E402,F401  自举：挂载内嵌项目
from palm_crypto.vault.fingerprint import get_machine_fingerprint  # noqa: F401

"""薄桥接层：实现已并入内嵌独立项目 palm-crypto（`palm_crypto.vault`）。

统一加解密模块收敛：本目录原是「密钥库 + 文件级加解密 + 硬件指纹」的砖内实现，
现已整体并入主目录下的内嵌项目 `palm-crypto/`（与国密 SM2/SM3/SM4 原语同项目），
由 `palm_boot` 自动挂载。本目录仅剩再导出 shim，历史
`from palm.adapters.crypto import operations / keystore` 调用面不变。

数据位置：沿用「密钥库随砖内聚于 .keys/」约定 —— set_data_dir 钉回本砖目录，
保持"砖可整体移动"语义（此前未生成过任何密钥文件，无迁移问题）。
"""
from __future__ import annotations

import palm_boot  # noqa: F401  自举：挂载 palm-crypto/ 等内嵌项目

from palm._core.paths import brick_local  # noqa: E402  数据位置钉回砖内
from palm_crypto.vault import operations as _ops  # noqa: E402

_ops.set_data_dir(brick_local(__file__))

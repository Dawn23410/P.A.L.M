"""安全芯片插槽契约（chip 插槽，焊死核心）。

隐喻映射：本 ABC 即焊死在主板上的加密芯片（类比 TPM/加密协处理器）——
实现 CryptoPort 的模块不可热拔，负责加解密/密钥绑定/离线恢复。
依赖铁律：零实现、零依赖（仅标准库），其他层只经 ports/__init__.py 引用。
"""

from abc import ABC, abstractmethod
from typing import Any


class CryptoPort(ABC):
    """加密芯片插槽：SM4 加解密/硬件指纹密钥绑定/离线恢复。

    实现方（crypto_engine/key_binding/key_recovery）必须全部覆盖；
    依赖缺失（如 gmssl）时实现方应优雅降级为禁用态，不得阻塞启动。
    """

    @abstractmethod
    def encrypt_bytes(self, data: bytes, key_id: str = "default") -> bytes:
        """加密：按密钥标识对原始字节做对称加密（SM4），返回密文。"""

    @abstractmethod
    def decrypt_bytes(self, blob: bytes, key_id: str = "default") -> bytes:
        """解密：按密钥标识还原明文；密钥不符抛异常由调用方归一。"""

    @abstractmethod
    def bind_fingerprint(self) -> str:
        """硬件指纹：读取/生成绑定本机的指纹标识，作为密钥派生种子。"""

    @abstractmethod
    def recover(self, seed: str) -> dict[str, Any]:
        """离线恢复：凭恢复种子重建密钥材料，返回恢复结果与可用状态。"""

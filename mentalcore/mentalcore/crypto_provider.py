"""加密适配器：复用 palm crypto/operations 的 SM4-CBC + HMAC-SM3 国密原语。

微核心自管主密钥（而非 palm 密钥库），保证独立部署时也能真正加密：
- 优先用配置传入的 32 位 hex 主密钥（MENTALCORE_MASTER_KEY）；
- 否则生成本地主密钥落盘，并打印恢复密钥（32 hex），换机可用恢复密钥解密。
- gmssl 缺失 / 主密钥不可用 → 明文降级（加 TXT: 前缀），明确告警但不阻断。
"""
import os

from .logging_setup import get_logger

_logger = get_logger()

try:
    from palm.adapters.crypto import operations
    _HAS_PALM_CRYPTO = True
except Exception:  # palm 不可导入时优雅降级
    operations = None
    _HAS_PALM_CRYPTO = False

_PLAIN_PREFIX = "TXT:"
_ENC_PREFIX = "SM4:"


class CryptoProvider:
    """对称加密封装；available 为 False 时以明文落盘并告警。"""

    def __init__(self, enabled: bool = True, master_key_hex: str = "",
                 key_file: str = "mentalcore_data/.master_key"):
        self.available = False
        self._key_file = key_file
        if not enabled or not _HAS_PALM_CRYPTO:
            if enabled and not _HAS_PALM_CRYPTO:
                _logger.warning("palm crypto 不可导入，加密关闭，将以明文存储")
            return
        if not operations.is_gmssl_available():
            _logger.warning("gmssl 国密库缺失，加密关闭，将以明文存储")
            return
        try:
            key = self._load_or_create_key(master_key_hex)
            operations.set_master_key(key)
            self.available = True
        except Exception as exc:
            _logger.warning("SM4 初始化失败，将以明文存储：%s", exc)

    def _load_or_create_key(self, master_key_hex: str) -> bytes:
        if master_key_hex:
            return bytes.fromhex(master_key_hex)
        if os.path.exists(self._key_file):
            with open(self._key_file, "rb") as f:
                data = f.read(16)
            if len(data) == 16:
                return data
        key = os.urandom(16)
        os.makedirs(os.path.dirname(self._key_file) or ".", exist_ok=True)
        with open(self._key_file, "wb") as f:
            f.write(key)
        _logger.info("已生成本地 SM4 主密钥；恢复密钥(32hex)=%s（请离线备份）",
                     key.hex())
        return key

    def encrypt_text(self, text: str) -> str:
        if not self.available:
            return _PLAIN_PREFIX + text
        blob = operations.encrypt_data(text.encode("utf-8")).hex()
        return _ENC_PREFIX + blob

    def decrypt_text(self, blob: str) -> str:
        if blob.startswith(_PLAIN_PREFIX):
            return blob[len(_PLAIN_PREFIX):]
        if blob.startswith(_ENC_PREFIX):
            blob = blob[len(_ENC_PREFIX):]
        if not self.available:
            # 降级环境下可能收到旧密文，尽力回退
            return blob
        try:
            return operations.decrypt_data(bytes.fromhex(blob)).decode("utf-8")
        except Exception:
            return blob

    def status(self) -> str:
        if self.available:
            return "SM4 国密已启用（CBC+HMAC-SM3）"
        return "明文降级（未启用加密）"

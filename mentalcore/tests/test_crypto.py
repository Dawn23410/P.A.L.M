"""加密适配器测试：明文降级 + （若可用）SM4 真实加解密往返。"""
import os
import tempfile

from mentalcore.crypto_provider import CryptoProvider


def test_plaintext_fallback_roundtrip():
    cp = CryptoProvider(enabled=False)
    assert cp.available is False
    enc = cp.encrypt_text("你好世界")
    assert enc.startswith("TXT:")
    assert cp.decrypt_text(enc) == "你好世界"


def test_sm4_roundtrip_when_available():
    # 仅在 palm 可导入且 gmssl 已安装时验证真实加密
    try:
        from palm.adapters.crypto import operations
    except Exception:
        return
    if not operations.is_gmssl_available():
        return
    with tempfile.TemporaryDirectory() as tmp:
        key_file = os.path.join(tmp, ".master_key")
        cp = CryptoProvider(enabled=True, master_key_hex="", key_file=key_file)
        assert cp.available is True
        enc = cp.encrypt_text("机密内容")
        assert enc.startswith("SM4:")
        assert cp.decrypt_text(enc) == "机密内容"

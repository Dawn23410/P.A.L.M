"""crypto operations 单元测试：gmssl 可用性检测与加密 round-trip。"""
import pytest

from .operations import encrypt_data, decrypt_data, is_gmssl_available


def test_gmssl_check():
    """gmssl 可用性检查不应抛异常。"""
    result = is_gmssl_available()
    assert isinstance(result, bool)


def test_encrypt_decrypt_roundtrip():
    """加密/解密 round-trip（依赖 master key，gmssl 不可用时跳过）。"""
    if not is_gmssl_available():
        pytest.skip("gmssl 模块不可用，跳过加解密测试")
    from .operations import _master_key
    if _master_key is None:
        pytest.skip("主密钥未初始化（crypto 砖未绑定），跳过")
    plain = "Hello, P.A.L.M! 测试中文。".encode("utf-8")
    enc = encrypt_data(plain)
    assert enc != plain
    dec = decrypt_data(enc)
    assert dec == plain

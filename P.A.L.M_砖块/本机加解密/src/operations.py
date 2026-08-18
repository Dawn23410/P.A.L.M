"""SM4 加解密原语：主密钥 + 硬件指纹密封密钥库。

设计要点：
- 所有加密使用持久化的「主密钥」(16 字节 = SM4 密钥长度)，与硬件指纹解耦，
  因此用户凭「恢复密钥」(主密钥的 32 位 hex) 可在换机后解密数据。
- 主密钥本身用硬件指纹派生的密钥密封后落盘（密钥库），仅本机可解封；
  恢复密钥是用户可读的明文备份。
"""
from __future__ import annotations

from palm_sdk.bricks._shared.paths import brick_local

import hashlib
import os
import secrets

_gmssl = None
_gmssl_loaded = False

# 主密钥（16 字节）。由 brick.py 绑定后注入；为空则不可加解密。
_master_key: bytes | None = None

# 恢复密钥的 8 位 hex 校验码：MEK 首次创建时随机生成，独立持久化到 P.A.L.M_砖块/.recovery_checksum。
# 设计：与 MEK 无派生关系，仅作身份标记；用户凭恢复密钥（32hex 主密钥明文）即可推导 MEK。
_CHECKSUM_FILENAME = ".recovery_checksum"


def is_gmssl_available() -> bool:
    """国密库 gmssl 是否安装（懒加载，缺失时 crypto 砖降级而非拖垮整个应用）。"""
    global _gmssl, _gmssl_loaded
    if _gmssl_loaded:
        return _gmssl is not None
    try:
        from gmssl import sm3 as _sm3
        from gmssl.sm4 import CryptSM4, SM4_ENCRYPT, SM4_DECRYPT
        _gmssl = (_sm3, CryptSM4, SM4_ENCRYPT, SM4_DECRYPT)
    except ImportError:
        _gmssl = None
    finally:
        _gmssl_loaded = True
    return _gmssl is not None


def _require_gmssl() -> None:
    """加密/解密前确保国密库就绪；缺失抛 RuntimeError 触发空砖降级。"""
    if is_gmssl_available():
        return
    raise RuntimeError("gmssl 国密库缺失，加解密不可用")


def set_master_key(key: bytes) -> None:
    """注入加解密主密钥（来自密钥库或恢复密钥）。"""
    global _master_key
    _master_key = key


def get_master_key() -> bytes | None:
    """返回当前主密钥；未就绪为 None。"""
    return _master_key


def derive_key(fingerprint: str, salt: bytes, iterations: int = 200000) -> bytes:
    """PBKDF2-HMAC-SHA256 从硬件指纹和随机盐派生 16 字节密钥（用于密封密钥库）。"""
    return hashlib.pbkdf2_hmac(
        "sha256", fingerprint.encode("utf-8"), salt, iterations, dklen=16,
    )


def _checksum_path() -> str:
    # 与 brick.py 同一解析方式：校验码随砖内聚于 .keys/，砖可随意移动。
    return brick_local(__file__, ".keys", _CHECKSUM_FILENAME)


def _read_checksum() -> str | None:
    try:
        with open(_checksum_path(), "r", encoding="utf-8") as f:
            cs = f.read().strip().lower()
    except (FileNotFoundError, OSError):
        return None
    if len(cs) == 8 and all(c in "0123456789abcdef" for c in cs):
        return cs
    return None


def _write_checksum(cs: str) -> None:
    with open(_checksum_path(), "w", encoding="utf-8") as f:
        f.write(cs)


def ensure_checksum() -> str:
    """读取并按需创建随机 8 位 hex 校验码；MEK 首次就绪时调用一次即可。"""
    cs = _read_checksum()
    if cs is not None:
        return cs
    cs = secrets.token_hex(4)
    _write_checksum(cs)
    return cs


def recovery_checksum() -> str:
    """返回当前持久化的 8 位 hex 校验码（首次调用时随机生成并落盘）。"""
    return ensure_checksum()


def _sm3_hash(raw_bytes: bytes) -> bytes:
    """gmssl.sm3 封装：bytes → 32 字节 digest。"""
    _sm3, _, _, _ = _gmssl
    return bytes.fromhex(_sm3.sm3_hash(list(raw_bytes)))


def _hmac_sm3(key: bytes, msg: bytes) -> bytes:
    """HMAC-SM3：用 SM3 代替 SHA256，兼容 Python hmac 接口。"""
    block_size = 64
    if len(key) > block_size:
        key = _sm3_hash(key)
    key = key.ljust(block_size, b"\x00")
    ipad = bytes(a ^ 0x36 for a in key)
    opad = bytes(a ^ 0x5C for a in key)
    return _sm3_hash(opad + _sm3_hash(ipad + msg))


def encrypt_data(plaintext: bytes) -> bytes:
    """SM4-CBC 加密 + HMAC-SM3 签名，使用主密钥。

    返回格式: iv(16) + ciphertext + hmac_sm3(32)
    """
    _require_gmssl()
    if _master_key is None:
        raise RuntimeError("主密钥未就绪，加解密不可用")
    _, CryptSM4, SM4_ENCRYPT, _ = _gmssl
    iv = os.urandom(16)
    crypt = CryptSM4(padding_mode=1)
    crypt.set_key(_master_key, SM4_ENCRYPT)
    ciphertext = crypt.crypt_cbc(iv, plaintext)
    mac = _hmac_sm3(_master_key, iv + ciphertext)
    return iv + ciphertext + mac


def decrypt_data(encrypted_pkg: bytes) -> bytes:
    """先验 HMAC-SM3，再解密。校验失败抛 ValueError。"""
    if len(encrypted_pkg) < 48:
        raise ValueError("无效的加密数据包")
    _require_gmssl()
    if _master_key is None:
        raise RuntimeError("主密钥未就绪，加解密不可用")
    _, CryptSM4, _, SM4_DECRYPT = _gmssl
    iv = encrypted_pkg[:16]
    mac = encrypted_pkg[-32:]
    ciphertext = encrypted_pkg[16:-32]
    expected = _hmac_sm3(_master_key, iv + ciphertext)
    if mac != expected:
        raise ValueError("HMAC 校验失败，文件可能被篡改或非本机加密")
    crypt = CryptSM4(padding_mode=1)
    crypt.set_key(_master_key, SM4_DECRYPT)
    return crypt.crypt_cbc(iv, ciphertext)


def seal_keystore(plaintext: bytes, fingerprint: str) -> bytes:
    """用硬件指纹派生的密钥密封主密钥，仅本机可解封。

    返回格式: salt(16) + iv(16) + ciphertext + hmac_sm3(32)
    """
    _require_gmssl()
    _, CryptSM4, SM4_ENCRYPT, _ = _gmssl
    salt = os.urandom(16)
    iv = os.urandom(16)
    key = derive_key(fingerprint, salt)
    crypt = CryptSM4(padding_mode=1)
    crypt.set_key(key, SM4_ENCRYPT)
    ciphertext = crypt.crypt_cbc(iv, plaintext)
    mac = _hmac_sm3(key, salt + iv + ciphertext)
    del key
    return salt + iv + ciphertext + mac


def unseal_keystore(pkg: bytes, fingerprint: str) -> bytes:
    """解封密钥库；指纹不匹配（换机）会抛 ValueError。"""
    if len(pkg) < 64:
        raise ValueError("无效的密钥库数据")
    _require_gmssl()
    _, CryptSM4, _, SM4_DECRYPT = _gmssl
    salt = pkg[:16]
    iv = pkg[16:32]
    mac = pkg[-32:]
    ciphertext = pkg[32:-32]
    key = derive_key(fingerprint, salt)
    expected = _hmac_sm3(key, salt + iv + ciphertext)
    if mac != expected:
        raise ValueError("密钥库校验失败，指纹不匹配")
    crypt = CryptSM4(padding_mode=1)
    crypt.set_key(key, SM4_DECRYPT)
    return crypt.crypt_cbc(iv, ciphertext)

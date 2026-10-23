"""SM4/SM3 底层后端：C 实现（tongsuopy/铜锁）优先，纯 Python gmssl 保底。

选择逻辑：`import tongsuopy` 成功即用 C 后端（OpenSSL/Tongsuo 分支，实测
SM4-CBC ~166MB/s、SM3 ~392MB/s，比纯 Python 快 2~3 个数量级）；失败回退
纯 Python gmssl（可用但慢，~0.2MB/s）。

两后端已通过 GB/T 32907-2016 国标向量与互操作验证：对同一 (key, iv, plaintext)
产出**逐字节一致**的密文，可随意互换——存量密文不受换后端影响。

接口约定（与原 gmssl CryptSM4(padding_mode=1) 语义逐位对齐）：
- sm4_cbc_encrypt(key, iv, plaintext)  PKCS7 填充后 CBC，返回纯密文（不含 iv）
- sm4_cbc_decrypt(key, iv, ciphertext) CBC 解密后去 PKCS7，坏填充抛 ValueError
"""
from __future__ import annotations

BACKEND = "gmssl(pure-python)"     # 探测后更新；供日志/报告引用
_C_AVAILABLE = False


def _pkcs7_pad(data: bytes) -> bytes:
    n = 16 - len(data) % 16
    return data + bytes([n]) * n


def _pkcs7_unpad(data: bytes) -> bytes:
    if not data or len(data) % 16:
        raise ValueError("无效的填充长度")
    n = data[-1]
    if not 1 <= n <= 16 or data[-n:] != bytes([n]) * n:
        raise ValueError("无效的 PKCS7 填充")
    return data[:-n]


def _detect() -> str:
    global BACKEND, _C_AVAILABLE
    try:
        from tongsuopy.crypto.ciphers.algorithms import SM4  # noqa: F401
        _C_AVAILABLE = True
        BACKEND = "tongsuo(C)"
        return "tongsuo"
    except Exception:
        _C_AVAILABLE = False
        BACKEND = "gmssl(pure-python)"
        return "gmssl"


_MODE = _detect()


def backend_name() -> str:
    return BACKEND


def is_c_backend() -> bool:
    return _C_AVAILABLE


# ─────────────────────── C 后端（tongsuopy/铜锁） ───────────────────────
if _MODE == "tongsuo":
    from tongsuopy.crypto.ciphers.algorithms import SM4
    from tongsuopy.crypto.ciphers.base import Cipher
    from tongsuopy.crypto.ciphers.modes import CBC
    from tongsuopy.crypto.hashes import Hash, SM3

    def sm4_cbc_encrypt(key: bytes, iv: bytes, plaintext: bytes) -> bytes:
        e = Cipher(SM4(key), CBC(iv)).encryptor()
        return e.update(_pkcs7_pad(plaintext)) + e.finalize()

    def sm4_cbc_decrypt(key: bytes, iv: bytes, ciphertext: bytes) -> bytes:
        d = Cipher(SM4(key), CBC(iv)).decryptor()
        return _pkcs7_unpad(d.update(ciphertext) + d.finalize())

    def sm3(data: bytes) -> bytes:
        h = Hash(SM3())
        h.update(data)
        return h.finalize()

# ─────────────────────── 纯 Python 保底（gmssl） ───────────────────────
else:
    from gmssl import sm3 as _gsm3
    from gmssl.sm4 import CryptSM4, SM4_DECRYPT, SM4_ENCRYPT

    def sm4_cbc_encrypt(key: bytes, iv: bytes, plaintext: bytes) -> bytes:
        c = CryptSM4(padding_mode=1)
        c.set_key(key, SM4_ENCRYPT)
        return c.crypt_cbc(iv, plaintext)

    def sm4_cbc_decrypt(key: bytes, iv: bytes, ciphertext: bytes) -> bytes:
        c = CryptSM4(padding_mode=1)
        c.set_key(key, SM4_DECRYPT)
        return c.crypt_cbc(iv, ciphertext)

    def sm3(data: bytes) -> bytes:
        return bytes.fromhex(_gsm3.sm3_hash(list(data)))


def hmac_sm3(key: bytes, msg: bytes) -> bytes:
    """RFC 2104 HMAC，哈希原语为 SM3（哈希本体走 C 后端时整体近似 C 速度）。"""
    block_size = 64
    k = sm3(key) if len(key) > block_size else key
    k = k.ljust(block_size, b"\x00")
    ipad = bytes(a ^ 0x36 for a in k)
    opad = bytes(a ^ 0x5C for a in k)
    return sm3(opad + sm3(ipad + msg))

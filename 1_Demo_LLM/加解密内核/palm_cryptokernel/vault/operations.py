"""SM4 加解密原语：主密钥 + 硬件指纹密封密钥库。

（自 P.A.L.M `palm/adapters/crypto` 收敛而来 —— 统一加解密模块。）

设计要点：
- 所有加密使用持久化的「主密钥」(16 字节 = SM4 密钥长度)，与硬件指纹解耦，
  因此用户凭「恢复密钥」(主密钥的 32 位 hex) 可在换机后解密数据。
- 主密钥本身用硬件指纹派生的密钥密封后落盘（密钥库），仅本机可解封；
  恢复密钥是用户可读的明文备份。
- 数据位置：默认 `PALM_CRYPTO_HOME`（env）或 `~/.palm_cryptokernel`；可用
  `set_data_dir()` 重钉（P.A.L.M 的 shim 用它把密钥库钉回砖内 `.keys/`，
  保持"砖可整体移动"语义）。须在 boot()/ensure_checksum() 之前调用。
- 加解密底层经 `palm_cryptokernel.backends`：C 实现（tongsuopy/铜锁）优先、
  纯 Python gmssl 保底，密文格式逐字节一致，存量数据不受影响。
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets

from .. import _private_fs, backends

# 主密钥（16 字节）。由 keystore.boot() 装配后注入；为空则不可加解密。
_master_key: bytes | None = None

# 恢复密钥的 8 位 hex 校验码：MEK 首次创建时随机生成，独立持久化到 .keys/.recovery_checksum。
# 设计：与 MEK 无派生关系，仅作身份标记；用户凭恢复密钥（32hex 主密钥明文）即可推导 MEK。
_CHECKSUM_FILENAME = ".recovery_checksum"

# 数据目录（密钥库/校验码落盘位置）。懒解析：首次取值时确定。
_DATA_DIR: str | None = None


def set_data_dir(path: str) -> None:
    """重钉密钥库/校验码的数据目录（须在 boot()/ensure_checksum() 之前调用）。"""
    global _DATA_DIR
    _DATA_DIR = path


def get_data_dir() -> str:
    """返回当前数据目录（未显式设置时按 env/家目录懒解析）。"""
    global _DATA_DIR
    if _DATA_DIR is None:
        _DATA_DIR = (os.environ.get("PALM_CRYPTO_HOME")
                     or os.path.join(os.path.expanduser("~"), ".palm_cryptokernel"))
    return _DATA_DIR


def is_gmssl_available() -> bool:
    """国密底层是否可用（C 后端或纯 Python gmssl 任一即可；缺失时调用方降级）。"""
    try:
        # 触发后端探测：gmssl 为声明依赖必在；tongsuopy 可选。
        return backends.sm3(b"") is not None
    except Exception:
        return False


def backend_name() -> str:
    """当前底层后端标识（供日志/审计报告引用）。"""
    return backends.backend_name()


def set_master_key(key: bytes | None) -> None:
    """注入加解密主密钥（来自密钥库或恢复密钥）。必须是 16 字节 SM4 密钥。

    WHY 校验长度：错长度（例如把 32 字符 hex 文本直接传进来）不会立刻报错，
    而会在首次加解密时以"填充错误"的形式爆出，届时极难定位是谁写坏的。

    传 `None` 表示**清空**（未解锁态）——这是既有契约，别用类型错误去堵它。
    """
    global _master_key
    if key is None:
        _master_key = None
        return
    if not isinstance(key, (bytes, bytearray)) or len(key) != 16:
        raise ValueError("主密钥必须为 16 字节（128 位）；清空请传 None")
    _master_key = bytes(key)


def get_master_key() -> bytes | None:
    """返回当前主密钥明文；未就绪为 None。

    ⚠️ 这是**裸密钥**：只给本内核内部与审计用，别写进日志、异常或落盘。
    """
    return _master_key


def derive_key(fingerprint: str, salt: bytes, iterations: int = 200000) -> bytes:
    """PBKDF2-HMAC-SHA256 从硬件指纹和随机盐派生 16 字节密钥（用于密封密钥库）。"""
    return hashlib.pbkdf2_hmac(
        "sha256", fingerprint.encode("utf-8"), salt, iterations, dklen=16,
    )


def _checksum_path() -> str:
    # 校验码随密钥库内聚于数据目录 .keys/ 下，目录可整体移动。
    return os.path.join(get_data_dir(), ".keys", _CHECKSUM_FILENAME)


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
    # 首次落盘前确保 .keys/ 存在（原实现缺失 mkdir，首次 boot 会 FileNotFoundError）
    _private_fs.ensure_dir(os.path.dirname(_checksum_path()))
    _private_fs.write_private_text(_checksum_path(), cs)


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


def _hmac_sm3(key: bytes, msg: bytes) -> bytes:
    """HMAC-SM3（哈希原语经 backends：C 后端时整体近似 C 速度）。"""
    return backends.hmac_sm3(key, msg)


def encrypt_data(plaintext: bytes) -> bytes:
    """SM4-CBC 加密 + HMAC-SM3 认证标签，使用主密钥。

    返回格式: iv(16) + ciphertext + hmac_sm3(32)
    """
    _require_ready()
    iv = os.urandom(16)
    ciphertext = backends.sm4_cbc_encrypt(_master_key, iv, plaintext)
    mac = _hmac_sm3(_master_key, iv + ciphertext)
    return iv + ciphertext + mac


def decrypt_data(encrypted_pkg: bytes) -> bytes:
    """先验 HMAC-SM3，再解密。校验失败抛 ValueError。"""
    if len(encrypted_pkg) < 48:
        raise ValueError("无效的加密数据包")
    _require_ready()
    iv = encrypted_pkg[:16]
    mac = encrypted_pkg[-32:]
    ciphertext = encrypted_pkg[16:-32]
    expected = _hmac_sm3(_master_key, iv + ciphertext)
    # 常量时间比较：防 MAC 逐字节定时侧信道（== 会在首个不等字节提前返回）
    if not hmac.compare_digest(mac, expected):
        raise ValueError("HMAC 校验失败，文件可能被篡改或非本机加密")
    return backends.sm4_cbc_decrypt(_master_key, iv, ciphertext)


def seal_keystore(plaintext: bytes, fingerprint: str) -> bytes:
    """用硬件指纹派生的密钥密封主密钥，仅本机可解封。

    注意：此处密钥是"指纹派生密钥"而非主密钥——首次 boot 时主密钥尚未生成、
    正是被封印的对象，故只查底层可用性、不查主密钥。

    返回格式: salt(16) + iv(16) + ciphertext + hmac_sm3(32)
    """
    _require_backend()
    salt = os.urandom(16)
    iv = os.urandom(16)
    key = derive_key(fingerprint, salt)
    ciphertext = backends.sm4_cbc_encrypt(key, iv, plaintext)
    mac = _hmac_sm3(key, salt + iv + ciphertext)
    del key
    return salt + iv + ciphertext + mac


def unseal_keystore(pkg: bytes, fingerprint: str) -> bytes:
    """解封密钥库；指纹不匹配（换机）会抛 ValueError。（同 seal：不依赖主密钥）"""
    if len(pkg) < 64:
        raise ValueError("无效的密钥库数据")
    _require_backend()
    salt = pkg[:16]
    iv = pkg[16:32]
    mac = pkg[-32:]
    ciphertext = pkg[32:-32]
    key = derive_key(fingerprint, salt)
    expected = _hmac_sm3(key, salt + iv + ciphertext)
    if not hmac.compare_digest(mac, expected):
        raise ValueError("密钥库校验失败，指纹不匹配")
    return backends.sm4_cbc_decrypt(key, iv, ciphertext)


def _require_backend() -> None:
    """仅查国密底层可用（seal/unseal 用指纹派生密钥，与主密钥无关）。"""
    if not is_gmssl_available():
        raise RuntimeError("国密底层缺失（gmssl/tongsuopy 均未安装），加解密不可用")


def _require_ready() -> None:
    """数据加解密前确保底层可用且主密钥已注入。"""
    _require_backend()
    if _master_key is None:
        raise RuntimeError("主密钥未就绪，加解密不可用")

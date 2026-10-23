"""KDF 族薄接口：密钥派生（口令类 + 密钥扩展类）。

两类语义务必分清（这是最常见的误用来源）：
- **口令类**（argon2id / scrypt / bcrypt / pbkdf2）：输入是**低熵口令**，
  必须给 salt，抗暴力破解；`memory_hard=True` 表示抗 GPU/ASIC。
- **密钥扩展类**（hkdf / kbkdf-sp800-108）：输入已是**高熵密钥材料**，
  用于把一段共享密钥派生成多把用途隔离的密钥；salt/info 用于域分离。
"""
from __future__ import annotations

from typing import Any, Optional

from ..registry import registry
from ._util import BytesLike, as_bytes

FAMILY = "kdf"
PASSWORD_KDF = ("argon2id", "scrypt", "pbkdf2")
EXPANSION_KDF = ("hkdf", "kbkdf-sp800-108")


def names() -> list[str]:
    """可用 KDF 算法名。"""
    return registry.names(FAMILY)


def derive(name: str, secret: BytesLike, length: int, *,
           salt: Optional[BytesLike] = None,
           info: Optional[BytesLike] = None, **params: Any) -> bytes:
    """从 secret 派生 length 字节密钥；额外参数（time_cost/memory_cost 等）透传。"""
    algo = registry.get(FAMILY, name)
    return algo.derive(
        as_bytes(secret, field="输入密钥材料"), length,
        salt=None if salt is None else as_bytes(salt, field="salt"),
        info=None if info is None else as_bytes(info, field="info"),
        **params,
    )


def is_memory_hard(name: str) -> bool:
    """是否抗 GPU 暴力破解（口令类判据）。"""
    return bool(registry.get(FAMILY, name).memory_hard)


def recommends_passwords() -> list[str]:
    """适合派生存放口令的算法（按强度优先）。"""
    existing = registry.names(FAMILY)
    return [n for n in PASSWORD_KDF if n in existing]


def recommends_expansion() -> list[str]:
    """适合做密钥用途隔离/扩展的算法。"""
    existing = registry.names(FAMILY)
    return [n for n in EXPANSION_KDF if n in existing]


def recommended(*, purpose: str = "password") -> str:
    """推荐算法：purpose='password' 取最强的口令类，'expansion' 取密钥扩展类。"""
    pool = (recommends_passwords() if purpose == "password"
            else recommends_expansion())
    if pool:
        return pool[0]
    existing = registry.names(FAMILY)
    if not existing:
        from ..errors import AlgorithmNotFound
        raise AlgorithmNotFound(FAMILY, purpose)
    return existing[0]


__all__ = ["FAMILY", "PASSWORD_KDF", "EXPANSION_KDF", "names", "derive",
           "is_memory_hard", "recommends_passwords", "recommends_expansion",
           "recommended"]

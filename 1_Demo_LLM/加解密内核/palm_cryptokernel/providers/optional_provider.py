"""提供方（可选）：argon2-cffi —— 现代口令派生（RFC 9106）。

留住它的理由：vault 现在用 PBKDF2 封印主密钥，而 Argon2id 是 OWASP 现行首选、
且**抗 GPU/ASIC**（内存硬）。它是"口令派生"这一族里唯一值得升级的选项，
没有标准库替代，故列为可选提供方：装了即进能力清单，没装则如实标 absent。
"""
from __future__ import annotations

from typing import Any, Optional

from ..abcs import Algorithm, KDFAlgorithm
from ..errors import KeyFormatError, ProviderUnavailable

PROVIDER = "optional"
REQUIRES = None   # 无统一前置依赖：build() 内按库实际可导入性判断


class _Argon2id(KDFAlgorithm):
    """Argon2id；参数缺省按 OWASP 2024 推荐：19MiB / 2 轮 / 1 并行。"""

    name, provider, standard = "argon2id", PROVIDER, "RFC 9106"

    @property
    def memory_hard(self) -> bool:
        return True

    def derive(self, secret: bytes, length: int, *, salt: Optional[bytes] = None,
               info: Optional[bytes] = None, **params: Any) -> bytes:
        try:
            from argon2.low_level import Type, hash_secret_raw
        except ImportError as exc:  # 可选依赖缺失：明确报"未安装"而非静默降级
            raise ProviderUnavailable("argon2-cffi 未安装") from exc
        if not salt or len(salt) < 8:
            raise KeyFormatError("argon2id 需要至少 8 字节盐")
        return hash_secret_raw(
            secret=secret, salt=salt, hash_len=length,
            time_cost=int(params.get("time_cost", 2)),
            memory_cost=int(params.get("memory_cost", 19 * 1024)),
            parallelism=int(params.get("parallelism", 1)),
            type=Type.ID, version=19,
        )


def build() -> list[Algorithm]:
    try:
        from argon2.low_level import Type, hash_secret_raw  # noqa: F401
    except ImportError as exc:
        raise ProviderUnavailable("argon2-cffi 未安装") from exc
    return [_Argon2id()]


MANIFEST: tuple[tuple[str, str], ...] = (("kdf", "argon2id"),)

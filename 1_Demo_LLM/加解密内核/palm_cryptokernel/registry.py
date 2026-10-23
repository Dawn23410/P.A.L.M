"""算法注册表：规范名 → 算法实例，支持多提供方按优先级择优。

为什么需要优先级：同一算法常有多个实现（如 SM3 既可走 OpenSSL/C，也可走纯
Python gmssl），注册表按 provider 优先级择优返回，调用方只认规范名、不关心
背后是谁——这就是"可插拔"的落点。
"""
from __future__ import annotations

import threading
from typing import Optional

from .abcs import Algorithm
from .errors import AlgorithmNotFound

# provider 优先级（数值越大越优先）：C 加速 > OpenSSL/hashlib > 可选纯扩展 > 纯 Python
PROVIDER_PRIORITY = {
    "cryptodome": 90,
    "hashlib": 80,
    "optional": 70,
    "gmssl": 50,
}

# 提供方加载顺序（与优先级无关，只保证确定性的注册次序）
PROVIDER_ORDER = ("cryptodome", "hashlib", "optional", "gmssl")


class Registry:
    """(family, name) → [Algorithm]，同键多实现时按 provider 优先级择优。"""

    def __init__(self) -> None:
        self._by_family: dict[str, dict[str, list[Algorithm]]] = {}
        self._failures: dict[str, str] = {}   # provider → 失败原因（供能力清单如实披露）
        self._loaded = False
        self._lock = threading.Lock()

    # ── 注册 ──
    def register(self, algo: Algorithm) -> None:
        """登记一个算法实现；同 (family, name) 允许多 provider 并存。"""
        bucket = self._by_family.setdefault(algo.family, {}).setdefault(algo.name, [])
        bucket.append(algo)
        bucket.sort(key=lambda a: PROVIDER_PRIORITY.get(a.provider, 0), reverse=True)

    def note_failure(self, provider: str, reason: str) -> None:
        """记录某提供方不可用的原因（如依赖库缺失）。"""
        self._failures[provider] = reason

    # ── 懒加载 ──
    def load(self) -> None:
        """首次访问时装载全部提供方（幂等、线程安全）。"""
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
            from . import providers
            providers.load_all(self)
            self._loaded = True

    # ── 查询 ──
    def get(self, family: str, name: str) -> Algorithm:
        """取指定族内的算法（择优）；未注册则抛 AlgorithmNotFound。"""
        self.load()
        bucket = self._by_family.get(family, {}).get(name)
        if not bucket:
            raise AlgorithmNotFound(family, name)
        return bucket[0]

    def find(self, name: str) -> list[Algorithm]:
        """跨族按规范名查找（同一名字可能同时属于多个族，如 rsa-pkcs1v15）。"""
        self.load()
        out: list[Algorithm] = []
        for bucket in self._by_family.values():
            out.extend(bucket.get(name, ()))
        out.sort(key=lambda a: (a.family, -PROVIDER_PRIORITY.get(a.provider, 0)))
        return out

    def names(self, family: str) -> list[str]:
        """某族已注册的规范名（排序后，便于稳定输出）。"""
        self.load()
        return sorted(self._by_family.get(family, {}))

    def families(self) -> list[str]:
        """全部已注册族标识（排序后）。"""
        self.load()
        return sorted(self._by_family)

    def all_of(self, family: str) -> list[Algorithm]:
        """某族全部实现（含同名的低优先级 provider）。"""
        self.load()
        out: list[Algorithm] = []
        for bucket in self._by_family.get(family, {}).values():
            out.extend(bucket)
        return out

    def failures(self) -> dict[str, str]:
        """不可用提供方的原因表。"""
        self.load()
        return dict(self._failures)

    def provider_of(self, family: str, name: str) -> Optional[str]:
        """规范名当前的实现方标识（未注册返回 None）。"""
        try:
            return self.get(family, name).provider
        except AlgorithmNotFound:
            return None


registry = Registry()

__all__ = ["Registry", "registry", "PROVIDER_PRIORITY", "PROVIDER_ORDER"]

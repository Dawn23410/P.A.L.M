"""提供方装配层：按固定顺序加载各密码学库，失败只记原因、绝不假装可用。

约定（每个 provider 模块必须声明）：
- `PROVIDER`  provider 标识（与 registry.PROVIDER_PRIORITY 对应）
- `REQUIRES`  需要的导入名（`None` = 恒可用）
- `MANIFEST`  它能提供的 (family, name) 全清单 —— 供能力清单如实报告缺口
- `build()`   返回实现 abcs 的算法实例列表（缺库时抛异常即可）

provider 之间**互不依赖**：任一库缺失只影响它自己那部分族。
"""
from __future__ import annotations

import importlib
from typing import Any, Iterator

from ..registry import Registry

# 加载顺序即注册顺序；同名算法最终由 registry 的 provider 优先级择优
_MODULE_NAMES = (
    "cryptodome_provider",
    "cryptodome_pubkey_provider",
    "digest_provider",
    "optional_provider",
    "gmssl_provider",
)

MODULE_NAMES = _MODULE_NAMES


def _modules() -> tuple[Any, ...]:
    """导入全部 provider 模块（各模块已做到"重库延迟导入"，故此处恒安全）。"""
    return tuple(importlib.import_module(f"{__name__}.{name}") for name in _MODULE_NAMES)


def _key(mod: Any) -> str:
    """模块级键：同一库可能拆成多个 provider 模块，故失败要按模块记账。"""
    return mod.__name__.rsplit(".", 1)[-1]


def _require(import_name: str | None) -> None:
    """前置校验库是否可导入；缺失即抛 ImportError（由调用方转为失败原因）。"""
    if import_name:
        importlib.import_module(import_name)


def load_all(registry: Registry) -> None:
    """把各 provider 的算法注册进 registry；库缺失或装配异常按模块记录原因。"""
    for mod in _modules():
        try:
            _require(mod.REQUIRES)
            for algo in mod.build():
                registry.register(algo)
        except Exception as exc:  # 库缺失 / 装配异常：降级并如实记录（不炸穿调用方）
            registry.note_failure(_key(mod), f"{type(exc).__name__}: {exc}")


def catalog() -> tuple[tuple[str, str, str | None], ...]:
    """(provider, 模块键, 依赖导入名) 目录 —— 能力清单据此判定可用性。"""
    return tuple((m.PROVIDER, _key(m), m.REQUIRES) for m in _modules())


def manifest_gaps(registry: Registry) -> Iterator[tuple[str, str, str, str]]:
    """产出"清单里有、但没注册成功"的 (family, name, provider, 模块键)。"""
    registered = {
        (a.family, a.name, a.provider)
        for fam in registry.families()
        for a in registry.all_of(fam)
    }
    for mod in _modules():
        for family, name in mod.MANIFEST:
            if (family, name, mod.PROVIDER) not in registered:
                yield family, name, mod.PROVIDER, _key(mod)


def provider_names() -> tuple[str, ...]:
    """全部 provider 标识（去重且保持加载顺序）。"""
    return tuple(dict.fromkeys(mod.PROVIDER for mod in _modules()))


__all__ = ["load_all", "manifest_gaps", "provider_names", "catalog", "MODULE_NAMES"]

"""能力清单：如实披露"本内核现在能做什么、不能做什么、缺什么库"。

设计取舍（WHY）：安全模块里**宁可缺，不可假**。未安装依赖库的算法一律不注册，
并在此以 `absent` 列出缺口与原因——绝不放"占位实现"假装可用。
`report()` 同时给机器（JSON 友好）与人（可读）两用，也是砖块 capability 的出口。
"""
from __future__ import annotations

from typing import Any, Optional

from .registry import PROVIDER_PRIORITY, registry

FAMILY_LABELS = {
    "hash": "哈希摘要",
    "mac": "消息认证码",
    "kdf": "密钥派生",
    "cipher": "对称加密（无认证）",
    "aead": "认证加密（AEAD）",
    "pubkey": "公钥加密",
}


def families() -> list[str]:
    """已注册的算法族标识（含中文标签见 FAMILY_LABELS）。"""
    return registry.families()


def available(family: Optional[str] = None) -> dict[str, list[dict[str, Any]]]:
    """可用算法：{族: [spec, ...]}，**按规范名去重**（provider 为择优结果）。

    同一算法常由多个 provider 提供（如 sha256 同时有 Cryptodome 与 hashlib 实现），
    这里只报一条并附 `providers` 列表，避免"算法数"被重复实现灌水。
    """
    targets = [family] if family else registry.families()
    out: dict[str, list[dict[str, Any]]] = {}
    for fam in targets:
        entries: list[dict[str, Any]] = []
        for name in registry.names(fam):
            impls = registry._by_family[fam][name]      # 已按优先级排序
            entries.append(dict(
                impls[0].spec,
                providers=[a.provider for a in impls],
                total_implementations=len(impls),
            ))
        if entries:
            out[fam] = entries
    return out


def _lib_present(import_name: Optional[str]) -> bool:
    """依赖库是否存在（不导入、只查 spec，避免副作用）。"""
    if not import_name:
        return True
    import importlib.util
    try:
        return importlib.util.find_spec(import_name) is not None
    except (ImportError, ValueError):
        return False


def absent() -> list[dict[str, Any]]:
    """已知但当前不可用的算法（依赖库未安装，或该模块装配失败）。**报告诚实性靠这里**。"""
    from . import providers
    errors = registry.failures()
    items: list[dict[str, Any]] = []
    for family, name, provider, module in providers.manifest_gaps(registry):
        items.append({
            "family": family,
            "name": name,
            "provider": provider,
            "reason": errors.get(module) or f"提供方 {module} 未装配",
        })
    return sorted(items, key=lambda i: (i["family"], i["name"]))


def providers_status() -> dict[str, dict[str, Any]]:
    """各提供方状态：库是否在位 + 各模块的装配错误（库在但装配失败会如实列出）。"""
    from . import providers
    errors = registry.failures()
    out: dict[str, dict[str, Any]] = {}
    for provider, module, requires in providers.catalog():
        entry = out.setdefault(provider, {
            "available": True,
            "priority": PROVIDER_PRIORITY.get(provider, 0),
            "reason": "",
            "modules": [],
            "errors": {},
        })
        entry["modules"].append(module)
        if not _lib_present(requires):
            entry["available"] = False
            entry["reason"] = f"缺少依赖库：{requires}"
        elif module in errors:
            entry["available"] = False
            entry["reason"] = errors[module]
            entry["errors"][module] = errors[module]
    return out


def report() -> dict[str, Any]:
    """完整能力报告：可用矩阵 + 缺口 + 提供方状态。"""
    avail = available()
    return {
        "providers": providers_status(),
        "families": {fam: FAMILY_LABELS.get(fam, fam) for fam in registry.families()},
        "counts": {fam: len(names) for fam, names in avail.items()},
        "total": sum(len(v) for v in avail.values()),
        "available": avail,
        "absent": absent(),
    }


def capability() -> dict[str, Any]:
    """砖块契约出口：本模块对外暴露的能力（algorithm/family 计数 + 缺口）。"""
    avail = available()
    return {
        "module": "palm_cryptokernel",
        "families": list(avail),
        "algorithm_count": sum(len(v) for v in avail.values()),
        "absent_count": len(absent()),
        "providers": [n for n, s in providers_status().items() if s["available"]],
    }


__all__ = [
    "FAMILY_LABELS", "families", "available", "absent",
    "providers_status", "report", "capability",
]

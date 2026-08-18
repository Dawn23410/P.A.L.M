"""BIOS 主板自检：核心砖校验 + 扩展探测 + 健康报告（主板组件，非砖块）。

对应主板隐喻的 BIOS POST：上电自检核心组件（core=True 缺失即失败），
探测可选扩展的可用性（标记 available/degraded/absent），产出健康报告
供 CPU（agent）与前端状态栏消费。探测项全部经 registry capabilities
惰性取用，不跨砖 import（遵循铁律）。
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends

from palm_sdk.bricks.base import registry
from palm_sdk.core.config import settings
from palm_sdk.security import require_api_token
from .handle import masterboard_snapshot

_LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bios", tags=["bios"])

# 爆炸记录路径（P5 炸弹框架写入，此处只读用于可视化）
_TRUST_BOMBS_FILE = Path(settings.STORAGE_POOL_DIR).parent / "audit" / "trust_bombs.json"


def _probe(probe_id: str, title: str, check) -> dict:
    """执行单个探测项；异常视为 absent（best-effort，不阻断启动）。"""
    try:
        detail = check()
        status = "available" if detail is not False else "absent"
        return {"id": probe_id, "title": title, "status": status, "detail": detail}
    except Exception as exc:  # noqa: BLE001
        return {"id": probe_id, "title": title, "status": "absent", "detail": str(exc)}


def _probe_sandbox():
    """沙箱引擎（隔离执行能力）是否可用。"""
    brick = registry.get("sandbox")
    fn = brick.capabilities.get("sandbox_engine") if brick else None
    return bool(fn) and bool(fn())


def _probe_pywin32():
    """受限账户隔离依赖的 pywin32 是否可用。"""
    try:
        import win32security  # noqa: F401
        return True
    except Exception:
        return False


def _probe_network_llm():
    """网络 LLM（customProviders）是否已配置（只查配置，不真连）。"""
    providers = getattr(settings, "customProviders", None) or {}
    return bool(providers)


def _probe_tts():
    """本地 TTS 引擎（tts_sovits）是否可用（capability 为 async，需 await）。"""
    brick = registry.get("tts_sovits")
    fn = brick.capabilities.get("is_tts_available") if brick else None
    if not fn:
        return False
    try:
        import asyncio
        result = fn()
        if asyncio.iscoroutine(result):
            return bool(asyncio.run(result))
        return bool(result)
    except Exception:
        return False


def _probe_vault():
    """保险库根目录可写（删除兜底可用，M0 起 vault 迁入存储砖）。"""
    brick = registry.get("storage")
    fn = brick.capabilities.get("vault") if brick else None
    if not fn:
        return False
    vault = fn()
    root = Path(vault.resolve_vault_root())
    root.mkdir(parents=True, exist_ok=True)
    probe = root / ".bios_probe"
    probe.write_text("ok", encoding="utf-8")
    try:
        probe.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass  # 删除守卫拦截时忽略：探测目标仅是验证可写
    return True


def _probe_offline():
    """离线状态（只读探测；返回文本避免 False 被误判为 absent）。

    离线砖已归档：离线=禁用网卡，直接读门面唯一真相源 palm_sdk.net.is_offline，
    不再依赖任何独立砖的 capabilities。
    """
    from palm_sdk.net import is_offline
    return "离线" if is_offline() else "在线"


def _core_missing() -> list[str]:
    """返回缺失的核心砖（正常应永远为空；注册顺序问题时可早期发现）。"""
    missing = [b.manifest.name for b in registry.all() if b.manifest.is_core and not b.manifest.is_enabled]
    return missing


def read_bomb_history() -> list[dict]:
    """读爆炸记录（P5 写入）；不存在或无权限时返回空。"""
    try:
        import json
        if _TRUST_BOMBS_FILE.exists():
            return json.loads(_TRUST_BOMBS_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        pass
    return []


def run_self_check() -> dict:
    """执行完整自检，产出健康报告（BIOS POST 结果）。"""
    probes = [
        _probe("sandbox", "沙箱引擎", _probe_sandbox),
        _probe("pywin32", "受限账户隔离", _probe_pywin32),
        _probe("network_llm", "网络大模型配置", _probe_network_llm),
        _probe("tts", "本地语音合成", _probe_tts),
        _probe("vault", "保险库兜底", _probe_vault),
        _probe("offline", "离线模式", _probe_offline),
    ]
    cores = [b.manifest.name for b in registry.all() if b.manifest.is_core]
    return {
        "status": "ok",
        "cores": cores,
        "core_missing": _core_missing(),
        "buses": registry.group_by_bus(),
        "masterboard": masterboard_snapshot(),
        "probes": probes,
        "bomb_history": read_bomb_history(),
    }


@router.get("/status", dependencies=[Depends(require_api_token)])
async def bios_status():
    """主板健康报告：核心砖清单 + 总线分组 + 扩展探测 + 爆炸历史。"""
    return run_self_check()
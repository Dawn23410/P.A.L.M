"""兜底防御砖：文件级保险库检索与恢复，并汇总系统还原点状态。

保险库由沙箱砖（sandbox.vault）在 AI 删除文件前自动归档（见 safe_delete 拦截）。本砖仅提供
检索/恢复/状态接口，不直接参与删除拦截。系统还原点状态取自沙箱砖（sandbox.restore），
与保险库共同构成「系统级回滚 + 文件级找回」双层兜底。
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends

from palm_sdk.bricks.base import Brick, BrickManifest, registry
from palm_sdk.security import require_api_token

router = APIRouter(prefix="/api/safety", tags=["safety"])


def _sandbox_cap(name: str):
    """惰性取沙箱砖能力；砖/能力缺失时返回 None（铁律：缺失降级）。"""
    brick = registry.get("sandbox")
    cap_fn = brick.capabilities.get(name) if brick else None
    return cap_fn() if cap_fn else None


def _storage_cap(name: str):
    """惰性取存储砖能力（M0 起 vault 冗余层迁入存储砖）；缺失降级 None。"""
    brick = registry.get("storage")
    cap_fn = brick.capabilities.get(name) if brick else None
    return cap_fn() if cap_fn else None


@router.get("/vault", dependencies=[Depends(require_api_token)])
async def get_vault():
    """列出保险库条目与统计（保险库根目录一并返回，便于定位副本）。"""
    vault = _storage_cap("vault")
    if vault is None:
        return {"error": "沙箱砖未注册，保险库不可用"}
    return {
        "entries": vault.list_vault(),
        "stats": vault.get_vault_stats(),
        "vault_root": vault.resolve_vault_root(),
    }


@router.post("/vault/restore", dependencies=[Depends(require_api_token)])
async def restore_vault(payload: dict = Body(default={})):
    """从保险库恢复某条目到原始路径（dest 可选，overwrite 默认 False 防覆盖）。"""
    vault = _storage_cap("vault")
    if vault is None:
        return {"ok": False, "error": "沙箱砖未注册，保险库不可用"}
    entry_id = payload.get("id") or ""
    if not entry_id:
        return {"ok": False, "error": "缺少 id"}
    return vault.restore_from_vault(
        entry_id, payload.get("dest"), bool(payload.get("overwrite", False))
    )


@router.post("/vault/clear", dependencies=[Depends(require_api_token)])
async def clear_vault():
    """清空整个保险库（危险操作，UI 需二次确认；仅删副本，不碰原始文件）。"""
    vault = _storage_cap("vault")
    if vault is None:
        return {"ok": False, "error": "沙箱砖未注册，保险库不可用"}
    return vault.clear_vault()


@router.get("/status", dependencies=[Depends(require_api_token)])
async def safety_status():
    """兜底防御状态：保险库是否启用 + 系统还原点是否可用 + 保险库根目录。"""
    vault = _storage_cap("vault")
    restore = _sandbox_cap("restore_point")
    if vault is None:
        return {"vault_enabled": False, "vault_root": None, "restore_point_available": False}
    rp_available = False
    if restore is not None:
        try:
            rp_available = restore.is_system_protection_enabled()
        except Exception:
            rp_available = False
    return {
        "vault_enabled": True,
        "vault_root": vault.resolve_vault_root(),
        "restore_point_available": rp_available,
    }


brick = Brick(
    manifest=BrickManifest(
        name="safety",
        title="兜底防御",
        description="文件级保险库（AI 删除前自动归档副本，可检索恢复）+ 系统还原点状态汇总，构成系统级回滚与文件级找回的双层兜底。",
        bus_type="board",
    ),
    router=router,
)
registry.register(brick)
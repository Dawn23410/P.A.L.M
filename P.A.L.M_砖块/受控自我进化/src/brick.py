"""self_evolution 砖：受控自注册工具的提案、审批、启用/禁用、删除与清单。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Body
from palm_sdk.bricks.base import Brick, BrickManifest, registry as brick_registry
from palm_sdk.core.config import settings
from palm_sdk.security import require_api_token

from . import registry as se_registry
from . import loader as se_loader
from . import skill_registry as se_skill_registry
from . import observer as se_observer
from . import slot_store as se_slot_store

router = APIRouter(prefix="/api/self-evolution", tags=["self-evolution"])


@router.get("/tools", dependencies=[Depends(require_api_token)])
def list_tools() -> dict:
    return {"tools": se_registry.list_all()}


@router.get("/audit", dependencies=[Depends(require_api_token)])
def get_audit() -> dict:
    return {"audit": se_registry.audit_log()}


@router.post("/propose", dependencies=[Depends(require_api_token)])
def propose_tool(payload: dict = Body(...)) -> dict:
    try:
        manifest, gate = se_registry.propose(
            name=payload.get("name", ""),
            description=payload.get("description", ""),
            scope=payload.get("scope", "user_documents"),
            params_schema=payload.get(
                "params_schema", {"type": "object", "properties": {}, "required": []}
            ),
            entry_source=payload.get("entry_source", ""),
            imports_allowlist=payload.get("imports_allowlist"),
            requires_permission=payload.get("requires_permission", ""),
            requires_network=bool(payload.get("requires_network", False)),
        )
    except Exception as err:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"提案处理失败：{err}")
    return {
        "manifest": manifest,
        "gate": {
            "blocked": gate.blocked,
            "risk_level": gate.risk_level,
            "findings": gate.findings,
            "has_destructive": gate.has_destructive,
        },
    }


@router.post("/tools/{tool_id}/approve", dependencies=[Depends(require_api_token)])
def approve_tool(tool_id: str) -> dict:
    manifest = se_registry.approve(tool_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail="工具不存在或已被阻断")
    se_loader.register_into_agent(manifest)
    return {"manifest": manifest}


@router.post("/tools/{tool_id}/disable", dependencies=[Depends(require_api_token)])
def disable_tool(tool_id: str) -> dict:
    manifest = se_registry.disable(tool_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail="工具不存在")
    se_loader.unregister_from_agent(tool_id)
    return {"manifest": manifest}


@router.post("/tools/{tool_id}/delete", dependencies=[Depends(require_api_token)])
def delete_tool(tool_id: str) -> dict:
    manifest = se_registry.get_manifest(tool_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail="工具不存在")
    if manifest.get("enabled"):
        se_loader.unregister_from_agent(tool_id)
    se_registry.delete(tool_id)
    return {"deleted": tool_id}


@router.get("/skills", dependencies=[Depends(require_api_token)])
def list_skills() -> dict:
    return {"skills": se_skill_registry.list_all()}


@router.get("/skills/audit", dependencies=[Depends(require_api_token)])
def get_skill_audit() -> dict:
    return {"audit": se_skill_registry.audit_log()}


@router.post("/propose-skill", dependencies=[Depends(require_api_token)])
def propose_skill(payload: dict = Body(...)) -> dict:
    try:
        record, gate = se_skill_registry.propose_skill(
            name=payload.get("name", ""),
            description=payload.get("description", ""),
            body=payload.get("body", ""),
            scope=payload.get("scope", "project"),
            risk=payload.get("risk", "low"),
            requires_approval=bool(payload.get("requires_approval", True)),
            condensed_from=payload.get("condensed_from"),
        )
    except Exception as err:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"技能提案失败：{err}")
    return {
        "record": record,
        "gate": {
            "blocked": gate.blocked,
            "risk_level": gate.risk_level,
            "findings": gate.findings,
        },
    }


@router.post("/skills/{name}/approve", dependencies=[Depends(require_api_token)])
def approve_skill(name: str) -> dict:
    meta = se_skill_registry.approve(name)
    if meta is None:
        raise HTTPException(status_code=404, detail="技能不存在或已被阻断")
    return {"record": meta}


@router.post("/skills/{name}/disable", dependencies=[Depends(require_api_token)])
def disable_skill(name: str) -> dict:
    meta = se_skill_registry.disable(name)
    if meta is None:
        raise HTTPException(status_code=404, detail="技能不存在")
    return {"record": meta}


@router.post("/skills/{name}/delete", dependencies=[Depends(require_api_token)])
def delete_skill(name: str) -> dict:
    if not se_skill_registry.get_meta(name):
        raise HTTPException(status_code=404, detail="技能不存在")
    se_skill_registry.delete(name)
    return {"deleted": name}


@router.post("/observe", dependencies=[Depends(require_api_token)])
def observe(payload: dict = Body(...)) -> dict:
    trace_id = se_observer.record_trace(
        steps=payload.get("steps", []),
        session_id=payload.get("session_id"),
        source=payload.get("source", "agent"),
    )
    return {"id": trace_id}


@router.get("/patterns", dependencies=[Depends(require_api_token)])
def get_patterns(min_count: int = 3) -> dict:
    return {"patterns": se_observer.detect_patterns(min_count)}


@router.post("/scan-and-propose", dependencies=[Depends(require_api_token)])
def scan_and_propose(min_count: int = 3) -> dict:
    # 自动识别重复行为并草拟 pending 提案（不自动批准，仍须人审）。
    return {"proposals": se_observer.scan_and_propose(min_count)}


brick = Brick(
    manifest=BrickManifest(
        name="self_evolution",
        title="受控自我进化",
        description="AI 受控自注册工具 / 技能凝聚 / 行为观测自动提议：提案经静态校验 + 人审后生效。",
        bus_type="board",
    ),
    router=router,
    capabilities={
        "self_evo_tools": lambda: se_registry.list_all(),
        "self_evo_skills": lambda: se_skill_registry.list_approved_index(),
        "self_evo_observe": lambda steps, session_id=None: se_observer.record_trace(steps, session_id),
    },
)
brick_registry.register(brick)

# 启动时载入已启用的工具（agent 砖已先于本砖注册，故可取其 register_tool 能力）。
se_loader.load_enabled_on_startup()


# ---- Phase 4：AI 手搓硬件（实现槽 + 熔断） ----

@router.get("/swaps", dependencies=[Depends(require_api_token)])
def list_swaps() -> dict:
    """列出全部实现包（pending/active/disabled/banned）。"""
    return {"swaps": se_slot_store.list_all()}


@router.post("/swaps", dependencies=[Depends(require_api_token)])
def propose_swap(payload: dict = Body(default={})) -> dict:
    """提交 AI 手搓硬件：gate 静态校验 + 覆盖声明校验 → 落盘（影子状态）。

    入参：{brick, capability, name, description, code}。覆盖黑名单/白名单
    未开放 → 拒绝（信任根死线）。
    """
    brick_name = payload.get("brick") or ""
    cap_key = payload.get("capability") or ""
    code = payload.get("code") or ""
    if not brick_name or not cap_key or not code:
        raise HTTPException(400, "缺少 brick/capability/code")
    result = se_slot_store.propose(
        brick_name, cap_key,
        name=payload.get("name", "未命名实现"),
        description=payload.get("description", ""),
        code=code, actor="ai",
    )
    if not result.get("ok"):
        raise HTTPException(403, result.get("reason", "实现包被拒绝"))
    return result


@router.get("/swaps/{swap_id}", dependencies=[Depends(require_api_token)])
def get_swap(swap_id: str) -> dict:
    """实现包详情（含源码）。"""
    detail = se_slot_store.get_swap(swap_id)
    if detail is None:
        raise HTTPException(404, "实现包不存在")
    return detail


@router.post("/swaps/{swap_id}/approve", dependencies=[Depends(require_api_token)])
def approve_swap(swap_id: str) -> dict:
    """人工审批实现包：开放对应插槽并放行为可激活。"""
    result = se_slot_store.approve(swap_id)
    if not result.get("ok"):
        raise HTTPException(400, result.get("reason", "审批失败"))
    return result


@router.post("/swaps/{swap_id}/dry-run", dependencies=[Depends(require_api_token)])
def dry_run_swap(swap_id: str, payload: dict = Body(default={})) -> dict:
    """影子模式试运行：沙箱跑一次实现（不注册不切换），返回结果供人工对比。"""
    result = se_slot_store.dry_run(swap_id, payload.get("args"), payload.get("kwargs"))
    if not result.get("ok"):
        raise HTTPException(400, result.get("error", "试运行失败"))
    return result


@router.delete("/swaps/{swap_id}", dependencies=[Depends(require_api_token)])
def delete_swap(swap_id: str) -> dict:
    """删除实现包（先停用再移除）。"""
    result = se_slot_store.delete_swap(swap_id)
    if not result.get("ok"):
        raise HTTPException(400, result.get("reason", "删除失败"))
    return result


@router.post("/swaps/{swap_id}/activate", dependencies=[Depends(require_api_token)])
def activate_swap(swap_id: str) -> dict:
    """激活实现包（切换 active；熔断失败自动回退 primary）。"""
    result = se_slot_store.activate(swap_id)
    if not result.get("ok"):
        raise HTTPException(400, result.get("reason", "激活失败"))
    return result


@router.post("/swaps/{swap_id}/deactivate", dependencies=[Depends(require_api_token)])
def deactivate_swap(swap_id: str) -> dict:
    """停用实现包（回退 primary，不拉黑）。"""
    result = se_slot_store.deactivate(swap_id)
    if not result.get("ok"):
        raise HTTPException(400, result.get("reason", "停用失败"))
    return result


# ---- 开放插槽授权（人工） ----

@router.get("/slots", dependencies=[Depends(require_api_token)])
def list_open_slots() -> dict:
    """开放插槽清单（授权区展示；默认空 = 零开放）。"""
    return {"slots": se_slot_store.list_slots()}


@router.post("/slots/open", dependencies=[Depends(require_api_token)])
def open_slot(payload: dict = Body(default={})) -> dict:
    """人工授权开放插槽（覆盖黑名单硬拒）。入参 {brick, capability}。"""
    brick_name = payload.get("brick") or ""
    cap_key = payload.get("capability") or ""
    if not brick_name or not cap_key:
        raise HTTPException(400, "缺少 brick/capability")
    result = se_slot_store.open_slot(brick_name, cap_key)
    if not result.get("ok"):
        raise HTTPException(403, result.get("reason", "开放失败"))
    return result


@router.post("/slots/close", dependencies=[Depends(require_api_token)])
def close_slot(payload: dict = Body(default={})) -> dict:
    """收回插槽开放权限（不自动停用已激活实现，仅阻止新提交）。"""
    brick_name = payload.get("brick") or ""
    cap_key = payload.get("capability") or ""
    if not brick_name or not cap_key:
        raise HTTPException(400, "缺少 brick/capability")
    return se_slot_store.close_slot(brick_name, cap_key)
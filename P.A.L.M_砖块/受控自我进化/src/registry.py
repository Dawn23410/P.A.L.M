"""ToolRegistry（受控工具注册表）：管理 Data/tools 下侧车单元与审计日志。"""
from __future__ import annotations

import json
import os
import shutil
import time
from typing import Any

from palm_sdk.core.config import settings
from palm_sdk.bricks._shared.paths import fallback_dir, resolve_storage
from ._io import atomic_write_json
from . import schemas
from .gate import analyze, GateResult

# 受管工具目录是砖块自有的代码产物，删除时必须硬删、绝不经 safe_delete 守卫送回收站。
# 守卫仅在沙箱子进程内安装；此处捕获原始 rmtree，使主进程删除行为与宿主守卫状态无关。
_HARD_RMTREE = shutil.rmtree

TOOLS_DIR = resolve_storage("tools", brick_file=__file__)
AUDIT_PATH = os.path.join(TOOLS_DIR, "audit.jsonl")


def _tool_dir(tool_id: str) -> str:
    return os.path.join(TOOLS_DIR, tool_id)


def _manifest_path(tool_id: str) -> str:
    return os.path.join(_tool_dir(tool_id), "manifest.json")


def _source_path(tool_id: str) -> str:
    return os.path.join(_tool_dir(tool_id), "tool.py")


def _read_manifest(tool_id: str) -> dict | None:
    path = _manifest_path(tool_id)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def list_all() -> list[dict]:
    if not os.path.isdir(TOOLS_DIR):
        return []
    result = []
    for name in os.listdir(TOOLS_DIR):
        manifest = _read_manifest(name)
        if manifest is not None:
            result.append(manifest)
    return result


def get_manifest(tool_id: str) -> dict | None:
    return _read_manifest(tool_id)


def propose(
    *,
    name: str,
    description: str,
    scope: str,
    params_schema: dict,
    entry_source: str,
    imports_allowlist: list[str] | None = None,
    requires_permission: str = "",
    requires_network: bool = False,
) -> tuple[dict, GateResult]:
    """提交一个工具提案：静态校验 + 落盘（pending/blocked），返回 (清单, 校验结果)。"""
    tool_id = schemas.new_tool_id()
    manifest_seed = {
        "imports_allowlist": imports_allowlist or [],
        "requires_network": requires_network,
    }
    gate = analyze(entry_source, manifest_seed)

    status = schemas.STATUS_BLOCKED if gate.blocked else schemas.STATUS_PENDING
    manifest = schemas.build_manifest(
        tool_id=tool_id,
        name=name,
        description=description,
        scope=scope,
        params_schema=params_schema,
        entry_source=entry_source,
        imports_allowlist=imports_allowlist or [],
        requires_permission=requires_permission,
        requires_network=requires_network,
        risk_level=gate.risk_level,
        status=status,
        approved=False,
        enabled=False,
    )
    os.makedirs(_tool_dir(tool_id), exist_ok=True)
    with open(_source_path(tool_id), "w", encoding="utf-8") as handle:
        handle.write(entry_source)
    atomic_write_json(_manifest_path(tool_id), manifest)
    _append_audit("propose", tool_id, f"{name}（{gate.risk_level}）", gate.risk_level, gate.blocked)
    return manifest, gate


def _save_manifest(manifest: dict) -> None:
    atomic_write_json(_manifest_path(manifest["id"]), manifest)


def approve(tool_id: str) -> dict | None:
    manifest = _read_manifest(tool_id)
    if manifest is None or manifest["status"] == schemas.STATUS_BLOCKED:
        return None
    manifest["approved"] = True
    manifest["enabled"] = True
    manifest["status"] = schemas.STATUS_APPROVED
    _save_manifest(manifest)
    _append_audit("approve", tool_id, manifest["name"], manifest["risk_level"], False)
    return manifest


def disable(tool_id: str) -> dict | None:
    manifest = _read_manifest(tool_id)
    if manifest is None:
        return None
    manifest["enabled"] = False
    _save_manifest(manifest)
    _append_audit("disable", tool_id, manifest["name"], manifest["risk_level"], False)
    return manifest


def delete(tool_id: str) -> bool:
    manifest = _read_manifest(tool_id)
    if manifest is None:
        return False
    # 沙箱执行后子进程可能短暂持有目录句柄，退避重试避免 Windows 下静默删除失败。
    tool_dir = _tool_dir(tool_id)
    for _ in range(8):
        try:
            _HARD_RMTREE(tool_dir, ignore_errors=False)
            break
        except OSError:
            time.sleep(0.25)
    _append_audit("delete", tool_id, manifest["name"], manifest["risk_level"], False)
    return True


def _append_audit(action: str, target_id: str, detail: str, risk: str, blocked: bool) -> None:
    os.makedirs(TOOLS_DIR, exist_ok=True)
    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "action": action,
        "actor": "agent",
        "target_id": target_id,
        "detail": detail,
        "risk_level": risk,
        "gate_blocked": bool(blocked),
    }
    with open(AUDIT_PATH, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def audit_log() -> list[dict]:
    if not os.path.exists(AUDIT_PATH):
        return []
    rows = []
    with open(AUDIT_PATH, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows
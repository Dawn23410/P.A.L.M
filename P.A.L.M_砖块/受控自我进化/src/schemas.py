"""自注册工具清单（manifest）数据结构与常量。"""
from __future__ import annotations

import hashlib
import time
import uuid

STATUS_PENDING = "pending"
STATUS_BLOCKED = "blocked"
STATUS_APPROVED = "approved"


def new_tool_id() -> str:
    return "tool_" + time.strftime("%Y%m%d") + "_" + uuid.uuid4().hex[:8]


def hash_source(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def build_manifest(
    *,
    tool_id: str,
    name: str,
    description: str,
    scope: str,
    params_schema: dict,
    entry_source: str,
    imports_allowlist: list[str],
    requires_permission: str,
    requires_network: bool,
    risk_level: str,
    status: str,
    approved: bool,
    enabled: bool,
) -> dict:
    """构造工具清单字典（纯数据，便于落盘与校验）。"""
    return {
        "id": tool_id,
        "name": name,
        "description": description,
        "scope": scope,
        "entry": "tool.py:entry",
        "params_schema": params_schema,
        "imports_allowlist": imports_allowlist,
        "requires_permission": requires_permission,
        "requires_network": bool(requires_network),
        "risk_level": risk_level,
        "status": status,
        "approved": bool(approved),
        "enabled": bool(enabled),
        "source_hash": hash_source(entry_source),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
    }

"""SkillRegistry（受控技能凝聚）：管理 Data/skills 下凝聚出的技能与治理态。

技能是"被遵循的指令"，治理重点是正确性（可能固化错误套路），由人审。
每个技能落盘两份：SKILL.md（frontmatter + 正文，给人/审计看的产物）与
meta.json（治理态：status / 来源 / 哈希，机器读取）。受管目录同样绕过 safe_delete 守卫硬删。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time

from palm._core.config import settings
from palm._core.paths import fallback_dir, resolve_storage
from ._io import atomic_write_json
from . import schemas
from .gate import scan_skill_content, GateResult

# 受管技能目录是砖块自有的知识产物，删除时必须硬删、绝不经 safe_delete 守卫送回收站。
_HARD_RMTREE = shutil.rmtree

SKILLS_DIR = resolve_storage("skills", brick_file=__file__)
AUDIT_PATH = os.path.join(SKILLS_DIR, "audit.jsonl")

STATUS_PENDING = schemas.STATUS_PENDING
STATUS_BLOCKED = schemas.STATUS_BLOCKED
STATUS_APPROVED = schemas.STATUS_APPROVED
STATUS_DISABLED = "disabled"


def _sanitize(name: str) -> str:
    # 技能名直接用作目录名，剥离文件系统不安全字符，避免路径穿越。
    return re.sub(r"[^a-zA-Z0-9_\-]", "_", name).strip("_") or "skill"


def _skill_dir(name: str) -> str:
    return os.path.join(SKILLS_DIR, _sanitize(name))


def _meta_path(name: str) -> str:
    return os.path.join(_skill_dir(name), "meta.json")


def _skill_md_path(name: str) -> str:
    return os.path.join(_skill_dir(name), "SKILL.md")


def _quote(value: str) -> str:
    # 极简 frontmatter 编码：双引号包裹并转义内嵌引号，满足我们自产字段的 YAML 兼容。
    return '"' + value.replace('"', '\\"') + '"'


def _write_skill_md(record: dict) -> None:
    front = [
        f"name: {_quote(record['name'])}",
        f"description: {_quote(record['description'])}",
        "agent_created: true",
        "project: palm",
        f"scope: {_quote(record['scope'])}",
        f"risk: {_quote(record['risk'])}",
        f"requires_approval: {'true' if record['requires_approval'] else 'false'}",
    ]
    content = "---\n" + "\n".join(front) + "\n---\n\n" + record["body"]
    with open(_skill_md_path(record["name"]), "w", encoding="utf-8") as handle:
        handle.write(content)


def _read_meta(name: str) -> dict | None:
    path = _meta_path(name)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def list_all() -> list[dict]:
    if not os.path.isdir(SKILLS_DIR):
        return []
    result = []
    for entry in os.listdir(SKILLS_DIR):
        meta = _read_meta(entry)
        if meta is not None:
            result.append(meta)
    return result


def get_meta(name: str) -> dict | None:
    return _read_meta(_sanitize(name))


def propose_skill(
    *,
    name: str,
    description: str,
    body: str,
    scope: str = "project",
    risk: str = "low",
    requires_approval: bool = True,
    condensed_from: str | None = None,
    auto_proposed: bool = False,
) -> tuple[dict, GateResult]:
    """提交一个技能凝聚提案：内容扫描 + 落盘（pending/blocked），返回 (记录, 扫描结果)。"""
    safe_name = _sanitize(name)
    gate = scan_skill_content(body)
    status = STATUS_BLOCKED if gate.blocked else STATUS_PENDING
    record = {
        "name": safe_name,
        "description": description,
        "scope": scope,
        "risk": risk,
        "requires_approval": bool(requires_approval),
        "agent_created": True,
        "project": "palm",
        "status": status,
        "proposed_by": "agent",
        "condensed_from": condensed_from,
        "auto_proposed": bool(auto_proposed),
        "content_hash": schemas.hash_source(body),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "body": body,
    }
    os.makedirs(_skill_dir(safe_name), exist_ok=True)
    _write_skill_md(record)
    atomic_write_json(_meta_path(safe_name), record)
    _append_audit(
        "propose_skill", safe_name, f"{name}（{gate.risk_level}）{'·自动' if auto_proposed else ''}",
        gate.risk_level, gate.blocked,
    )
    return record, gate


def _save_meta(record: dict) -> None:
    atomic_write_json(_meta_path(record["name"]), record)


def approve(name: str) -> dict | None:
    meta = _read_meta(_sanitize(name))
    if meta is None or meta["status"] == STATUS_BLOCKED:
        return None
    meta["status"] = STATUS_APPROVED
    _save_meta(meta)
    _append_audit("approve_skill", name, meta["description"], meta["risk"], False)
    return meta


def disable(name: str) -> dict | None:
    meta = _read_meta(_sanitize(name))
    if meta is None:
        return None
    meta["status"] = STATUS_DISABLED
    _save_meta(meta)
    _append_audit("disable_skill", name, meta["description"], meta["risk"], False)
    return meta


def delete(name: str) -> bool:
    meta = _read_meta(_sanitize(name))
    if meta is None:
        return False
    skill_dir = _skill_dir(_sanitize(name))
    for _ in range(8):
        try:
            _HARD_RMTREE(skill_dir, ignore_errors=False)
            break
        except OSError:
            time.sleep(0.25)
    _append_audit("delete_skill", name, meta["description"], meta["risk"], False)
    return True


def list_approved_index() -> list[dict]:
    """已批准技能的轻量索引，供 agent 砖经 capability 读取（不含正文，控制体积）。"""
    return [
        {
            "name": m["name"],
            "description": m["description"],
            "scope": m["scope"],
            "risk": m["risk"],
            "requires_approval": m["requires_approval"],
        }
        for m in list_all()
        if m["status"] == STATUS_APPROVED
    ]


def _append_audit(action: str, target_id: str, detail: str, risk: str, blocked: bool) -> None:
    os.makedirs(SKILLS_DIR, exist_ok=True)
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
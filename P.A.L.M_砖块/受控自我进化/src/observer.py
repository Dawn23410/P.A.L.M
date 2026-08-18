"""Observer（行为观测与模式检测）：记录多步行为轨迹，识别重复模式并自动草拟技能凝聚提案。

Phase 3 核心：在 Phase 2 技能凝聚基础上，自动识别"被重复走 ≥ N 次且结构相似"的多步行为，
草拟 SKILL.md 提案（pending，仍须经人审批，绝不静默生效）。轨迹存于 Data/observations/，
与受管工具/技能同属砖块自有产物，删除时硬删、绕过 safe_delete 守卫。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
import uuid

from palm_sdk.core.config import settings
from palm_sdk.bricks._shared.paths import fallback_dir, resolve_storage
from . import skill_registry as se_skill_registry

_HARD_RMTREE = shutil.rmtree

OBS_DIR = resolve_storage("observations", brick_file=__file__)
TRACES_PATH = os.path.join(OBS_DIR, "traces.jsonl")

MIN_COUNT_DEFAULT = 3


def _ensure_dir() -> None:
    os.makedirs(OBS_DIR, exist_ok=True)


def _normalize_step(step: dict) -> dict:
    # 仅保留动作名与可选签名，丢弃可能含敏感信息的原始参数值。
    return {"action": str(step.get("action", "")), "signature": str(step.get("signature", ""))}


def record_trace(steps: list[dict], session_id: str | None = None, source: str = "agent") -> str:
    """记录一条行为轨迹（steps 为有序步骤列表，每步含 action 与可选 signature）。"""
    _ensure_dir()
    trace_id = f"trace_{time.strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}"
    trace = {
        "id": trace_id,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "session_id": session_id or "unknown",
        "source": source,
        "steps": [_normalize_step(s) for s in steps],
    }
    with open(TRACES_PATH, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(trace, ensure_ascii=False) + "\n")
    return trace_id


def load_traces() -> list[dict]:
    if not os.path.exists(TRACES_PATH):
        return []
    rows: list[dict] = []
    with open(TRACES_PATH, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def normalize_signature(steps: list[dict]) -> str:
    # 按动作序列聚类（顺序敏感）；signature 仅作可选细分，不并入主键以免过度分裂。
    return " > ".join(s["action"] for s in steps if s.get("action"))


def _already_condensed(signature: str) -> bool:
    # 已有按 condensed_from 命中且未被禁用的技能，视为已凝聚，跳过重复提案。
    for meta in se_skill_registry.list_all():
        if meta.get("condensed_from") == signature and meta.get("status") != "disabled":
            return True
    return False


def detect_patterns(min_count: int = MIN_COUNT_DEFAULT) -> list[dict]:
    """按动作序列聚类轨迹，返回重复 ≥ min_count 次且尚未凝聚的模式。"""
    groups: dict[str, list[dict]] = {}
    for trace in load_traces():
        sig = normalize_signature(trace.get("steps", []))
        if sig:
            groups.setdefault(sig, []).append(trace)

    patterns: list[dict] = []
    for sig, members in groups.items():
        if len(members) < min_count or _already_condensed(sig):
            continue
        patterns.append({
            "signature": sig,
            "count": len(members),
            "steps": members[0]["steps"],
            "sample_trace_ids": [m["id"] for m in members[:5]],
        })
    patterns.sort(key=lambda p: p["count"], reverse=True)
    return patterns


def derive_skill_name(signature: str) -> str:
    # 由动作序列哈希派生稳定且唯一的技能名，避免与人工命名冲突。
    digest = se_skill_registry.schemas.hash_source(signature)[:8]
    slug = re.sub(r"[^a-zA-Z0-9]", "_", signature)[:24].strip("_").lower() or "routine"
    return f"auto_{slug}_{digest}"


def draft_skill_body(pattern: dict) -> str:
    # 由观测到的步骤序列生成技能正文草稿（不含任何绕过安全/改源码指令，避免被 Gate 拦）。
    lines = [
        f"# 自动凝聚技能：{pattern['signature']}",
        "",
        f"> 本技能由行为观测自动凝聚（auto_proposed=true），凝聚自 {pattern['count']} 次结构相似的多步行为。",
        "> 尚未经人审，使用前请审阅正确性。",
        "",
        "## 触发",
        f"当观察到如下有序多步行为被重复执行时启用：{pattern['signature']}。",
        "",
        "## 步骤",
    ]
    for idx, step in enumerate(pattern["steps"], 1):
        note = f"（{step['signature']}）" if step.get("signature") else ""
        lines.append(f"{idx}. {step['action']}{note}")
    lines += [
        "",
        "## 提示",
        "- 此为 AI 自动草拟，正确性需人审后启用。",
        "- 仅编排既有能力，不新增危险操作。",
    ]
    return "\n".join(lines)


def propose_from_pattern(pattern: dict) -> dict:
    """把检测到的重复模式草拟成技能提案（pending，待人审），返回提案结果。"""
    name = derive_skill_name(pattern["signature"])
    record, gate = se_skill_registry.propose_skill(
        name=name,
        description=f"自动凝聚：{pattern['signature']}（{pattern['count']} 次）",
        body=draft_skill_body(pattern),
        scope="project",
        risk="low",
        requires_approval=True,
        condensed_from=pattern["signature"],
        auto_proposed=True,
    )
    return {
        "name": name,
        "status": record["status"],
        "blocked": gate.blocked,
        "risk_level": gate.risk_level,
        "signature": pattern["signature"],
        "count": pattern["count"],
    }


def scan_and_propose(min_count: int = MIN_COUNT_DEFAULT) -> list[dict]:
    """识别重复模式并批量草拟 pending 提案（不自动批准）。"""
    return [propose_from_pattern(p) for p in detect_patterns(min_count)]
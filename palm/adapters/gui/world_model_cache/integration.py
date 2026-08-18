"""层级合并分流：不重叠直接合并；语义冲突/高复杂度拉 LLM 兜底（软依赖）。

LLM 仅作兜底：默认路径（不重叠→直接合并）零 LLM 开销；仅在多 level 高重叠冲突
时尝试拉一次 LLM 整合概览，取不到或异常则标记 needs_llm_review 降级。
"""
from __future__ import annotations

import inspect

from .registry import SoftwareRegistry
from .distiller import distill_world_model
from .diff import merge_entry


def _level_overlap(a_nodes, b_nodes):
    """两 level 节点 identity 交集比例（任一为空则 0）。"""
    a = {n["identity"] for n in a_nodes}
    b = {n["identity"] for n in b_nodes}
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def _entry_brief(entry):
    """把条目压成给 LLM 的简短中文概要（不含任何动态值）。"""
    lines = [f"软件 {entry.get('software_id')} 的界面层级："]
    for level_id, lvl in entry.get("levels", {}).items():
        roles = {}
        for n in lvl.get("nodes", []):
            key = n.get("role", "control")
            roles[key] = roles.get(key, 0) + 1
        role_str = "、".join(f"{k}×{v}" for k, v in roles.items())
        lines.append(f"- 层级[{level_id}]：{len(lvl.get('nodes', []))} 节点（{role_str}）")
    return "\n".join(lines)


def _try_llm_synthesis(entry):
    """复杂/冲突时尝试拉 LLM 整合概览（软依赖，失败返回 None）。"""
    try:
        from palm_sdk.bricks.llm import brick as llm_brick
    except Exception:
        return None
    cap = None
    for cand in ("generate", "chat", "completion", "complete"):
        fn = getattr(llm_brick, "capabilities", {}).get(cand)
        if fn:
            cap = fn
            break
    if cap is None or inspect.iscoroutinefunction(cap):
        return None
    prompt = (
        "以下是同一软件的多个界面层级静态结构，请整合为一段简洁中文概览，"
        "说明该软件有哪些主要功能区域与控件类型（不要描述任何动态值）：\n"
        + _entry_brief(entry)
    )
    try:
        result = cap(prompt)
        return result if isinstance(result, str) else None
    except Exception:
        return None


def derive_and_merge(model):
    """顶层入口：蒸馏→载入→合并→（必要时 LLM 兜底）→落盘。返回 (entry, report)。"""
    incoming = distill_world_model(model)
    software_id = incoming["software_id"]
    registry = SoftwareRegistry()
    existing = registry.load(software_id)
    merged, report = merge_entry(existing, incoming)

    # 层级合并分流：多 level 且存在高重叠冲突 → 尝试 LLM 兜底。
    levels = merged.get("levels", {})
    level_ids = list(levels)
    has_conflict = any(
        _level_overlap(levels[a].get("nodes", []), levels[b].get("nodes", [])) > 0.5
        for i, a in enumerate(level_ids) for b in level_ids[i + 1:]
    )
    if has_conflict:
        synthesis = _try_llm_synthesis(merged)
        merged["llm_synthesis"] = synthesis or ""
        merged["needs_llm_review"] = synthesis is None
    else:
        merged["needs_llm_review"] = False

    registry.save(merged)
    return merged, report
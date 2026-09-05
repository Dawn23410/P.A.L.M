"""增量合并：按 identity 对比新旧节点，补充新增、标记缺失、更新静态 label。"""
from __future__ import annotations


def _index_nodes(level):
    return {n["identity"]: n for n in level.get("nodes", [])}


def merge_level(existing_level, incoming_level):
    """合并两个同 level_id 的快照；返回 (merged_nodes, changes)。

    主匹配键为 identity（而非文本）：同 identity 文本差异仅更新 label，
    不分裂出新节点——这正是"同位置不同显示内容直接判同节点"的意图。
    """
    old = _index_nodes(existing_level)
    new = _index_nodes(incoming_level)
    changes = []
    merged = []
    seen = set()
    for identity, node in new.items():
        seen.add(identity)
        if identity in old:
            base = old[identity]
            if base.get("name") != node.get("name") and node.get("name"):
                changes.append({"type": "label_updated", "identity": identity,
                                "from": base.get("name"), "to": node.get("name")})
                base = dict(base)
                base["name"] = node.get("name")
                base["rect_relative"] = node.get("rect_relative")
            merged.append(base)
        else:
            changes.append({"type": "added", "identity": identity})
            merged.append(node)
    for identity in old:
        if identity not in seen:
            changes.append({"type": "removed", "identity": identity})
            removed = dict(old[identity])
            removed["removed"] = True
            merged.append(removed)
    merged.sort(key=lambda n: n["identity"])
    return merged, changes


def merge_entry(existing, incoming):
    """合并整个软件条目（多 level 聚合）。返回 (merged_entry, report)。"""
    report = {"levels": {}}
    existing_levels = existing.setdefault("levels", {})
    for level_id, incoming_level in incoming.get("levels", {}).items():
        if level_id in existing_levels:
            merged_nodes, changes = merge_level(existing_levels[level_id], incoming_level)
            slot = existing_levels[level_id]
            slot["nodes"] = merged_nodes
            slot["stub"] = False
            slot["unobserved"] = False
            slot["observed_at"] = incoming_level.get("observed_at", "")
            report["levels"][level_id] = {"action": "merged", "changes": changes}
        else:
            existing_levels[level_id] = incoming_level
            report["levels"][level_id] = {"action": "added", "changes": []}
    existing["exe"] = incoming.get("exe", existing.get("exe", ""))
    existing["title_sample"] = incoming.get("title_sample", existing.get("title_sample", ""))
    existing["updated_at"] = incoming.get("updated_at", "")
    return existing, report

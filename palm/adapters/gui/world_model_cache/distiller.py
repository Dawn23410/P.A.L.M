"""将 world_model 瞬时快照蒸馏为静态 Atlas 草稿（仅结构，不存动态值）。"""
from __future__ import annotations

from ..desktop_control import get_window_exe
from .schema import (normalize_exe, classify_node, node_identity,
                     derive_level_id, derive_capability)


def _relative_rect(rect, window_rect):
    """把屏幕坐标 rect 转为相对窗口左上角的偏移（与窗口屏幕位置无关）。"""
    wx, wy, _, _ = window_rect
    return (rect[0] - wx, rect[1] - wy, rect[2] - wx, rect[3] - wy)


def _walk(node, ancestors, sibling_index, window_rect, out):
    """递归蒸馏 UIA 节点：identity + role + 动态占位 + 相对坐标。"""
    ct = node.get("control_type", "").removesuffix("Control")
    aid = node.get("automation_id", "") or ""
    name = node.get("name", "") or ""
    children = node.get("children", []) or []
    path = ancestors + [(ct, aid, sibling_index)]
    role, dynamic = classify_node(ct, name)
    # 动态节点同样保留 name 作引用锚：Atlas 仅规划认知、不作运行态，
    # 控件当前值（开/关态、计数、文本）的新鲜度由"执行前实时重扫"保证，
    # 故此处不剥离 name，只靠 dynamic 占位标记避免把快照当永久真相。
    entry = {
        "identity": node_identity(path),
        "control_type": ct,
        "automation_id": aid,
        "role": role,
        "name": name,
        "rect_relative": _relative_rect(node.get("rect", (0, 0, 0, 0)), window_rect),
    }
    if dynamic is not None:
        entry["dynamic"] = dynamic
    # 语义能力标签：结构性（由名/角色推导，非运行态），支撑推理中枢关键词→控件纯规则匹配
    caps = derive_capability(name, role, ct)
    if caps:
        entry["capability"] = caps
    out.append(entry)
    for idx, child in enumerate(children):
        _walk(child, path, idx, window_rect, out)


def distill_world_model(model: dict) -> dict:
    """从 world_model JSON 蒸馏出软件 Atlas 草稿（待 registry 合并落盘）。"""
    meta = model.get("meta", {})
    hwnd = meta.get("hwnd", 0)
    title = meta.get("title", "")
    window_rect = meta.get("window_rect", (0, 0, 0, 0))
    exe = get_window_exe(hwnd) if hwnd else ""
    software_id = normalize_exe(exe)
    tree = model.get("uia_tree", {})
    nodes = []
    _walk(tree, [], 0, window_rect, nodes)
    level_id, method, nav_items = derive_level_id(tree, title)
    return {
        "software_id": software_id,
        "exe": exe,
        "title_sample": title,
        "version": 1,
        "levels": {
            level_id: {
                "level_id": level_id,
                "derived_method": method,
                "nav_items": nav_items,
                "observed_at": meta.get("timestamp", ""),
                "stub": False,
                "unobserved": False,
                "nodes": nodes,
            }
        },
        "llm_synthesis": "",
        "needs_llm_review": False,
        "updated_at": meta.get("timestamp", ""),
    }

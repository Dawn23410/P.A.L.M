"""反向建图（自有树格式 + source 标签 + 只增强不覆盖）。

场景（对齐设计）：后台拿不到 UIA 树的自绘窗口 + 被动长周期里，从长期高置信未匹配簇
反向生成 Atlas 种子节点。这是主动引导（能扫 UIA→逻辑分析器 / 扫不到→LLM 建图）的**补充**
而非替代；后台能取到 UIA 树时应直接禁用以避免冗余（由 background_scan 调用方保证）。

铁律：
- 产出节点一律 Atlas 自有树格式（identity/control_type/name/role/rect_relative/calibrated_bounds），
  绝不使用 UIA 的 control_type[/automation_id|#sibling] 树格式，防与后期 UIA 树混淆；
- 每个节点带 source=observed；合并时 observed 只能「增强」uia/llm 节点（补坐标/质检验/转移边），
  绝不「覆盖」其 source 与层级。
"""
from __future__ import annotations

import logging

_LOGGER = logging.getLogger(__name__)

_NOISE = {"设置", "系统", "最小化", "最大化", "关闭"}


def _node_from_cluster(cluster: dict) -> dict:
    """把高置信未匹配簇转成 Atlas 自有树节点（source=observed）。"""
    labels = cluster.get("labels") or []
    name = next((l for l in labels if l and l not in _NOISE), None)
    name = name or f"observed_{cluster['grid'][0]}_{cluster['grid'][1]}"
    cx, cy = cluster["centroid"]
    return {
        "identity": f"observed/{cluster['grid'][0]}_{cluster['grid'][1]}",
        "control_type": "ObservedControl",
        "name": name,
        "role": "interactive",
        "rect_relative": [cx, cy, 0.04, 0.04],
        "calibrated_bounds": [cx, cy, 0.04, 0.04],
        "source": "observed",
        "match_confidence": round(min(1.0, cluster["samples"] / 12.0), 3),
        "transitions": [cluster["dominant_effect"]] if cluster["dominant_effect"] != "none" else [],
    }


def reconcile_observed(software_id: str, node: dict) -> bool:
    """把 observed 节点合并进 Atlas：命中只增强不覆盖；未命中插为新节点。"""
    from .world_model_cache.registry import SoftwareRegistry
    entry = SoftwareRegistry().load(software_id)
    levels = entry.setdefault("levels", {})
    level = levels.setdefault("default", {"nodes": []})
    for n in level["nodes"]:
        if n.get("name") == node["name"] or n.get("identity") == node["identity"]:
            n["calibrated_bounds"] = node["calibrated_bounds"]
            n["match_confidence"] = max(n.get("match_confidence", 0.0),
                                        node["match_confidence"])
            if node["transitions"]:
                n.setdefault("transitions", []).extend(
                    t for t in node["transitions"] if t not in n.get("transitions", []))
            # 关键：绝不覆盖 n["source"]（observed 不可盖 uia/llm）
            SoftwareRegistry().save(entry)
            return True
    level["nodes"].append(node)
    SoftwareRegistry().save(entry)
    return True


def reverse_build_from_pending(min_samples: int = 8) -> int:
    """从校准 pending 中挑长期高置信簇反向建图。返回成功建图数。

    调用方应保证：仅当后台 UIA 树不可取（自绘窗口）时才启用本函数；
    能取到 UIA 树时走 background_scan 直接蒸馏，不应调用本函数（避免冗余）。
    """
    from . import atlas_calibration as cal
    built = 0
    for key, cl in list(cal._pending.items()):
        if cl.get("samples", 0) < min_samples:
            continue
        sid = key.split("|", 1)[0]
        if not sid:
            continue
        node = _node_from_cluster(cl)
        if reconcile_observed(sid, node):
            cal._pending.pop(key, None)
            built += 1
    if built:
        _LOGGER.info("反向建图：从 pending 生成 %d 个 observed 节点", built)
    return built

"""聚合校准闭环（点击池 → 热点区聚类 → 与 Atlas 一一对应 → 回写 / 屯 pending）。

核心思想：用真实人类点击给 Atlas 静态地图做 ground-truth 校准——既补「按钮坐标」
（地图原本只有结构标识），又反向检验「地图画的按钮对不对」（match_confidence 质检分），
并把观察到的「点击→界面变化」写成转移规律边。

策略（对齐设计）：
- 聚合计算：攒够阈值 K 或空闲 T 秒才统一算，天然避开高频；
- 一一对应：复合键 = window_class + 空间栅格 + OCR 标签（标签为桥梁，无标签不硬回写）；
- 无法对应：进 pending 池仍计算，地图发生变更时触发重匹配（不丢长尾）。
OCR 仅用于给热点区打文字标签（识别点击位置标识），不做坐标/全屏理解。
"""
from __future__ import annotations

import logging
import time

_LOGGER = logging.getLogger(__name__)

_GRID = 12          # 空间栅格分辨率（12x12 粗定位）
_BATCH_K = 30      # 攒够 30 条点击触发聚合
_IDLE_S = 120      # 或空闲 2 分钟触发
_pending: dict[str, dict] = {}   # cluster_key -> cluster 摘要（未匹配屯着）
_last_run = 0.0

_NOISE = {"设置", "系统", "最小化", "最大化", "关闭"}


def _grid_key(nx: float, ny: float) -> tuple[int, int]:
    return (int(nx * _GRID), int(ny * _GRID))


def _cluster(records: list[dict]) -> list[dict]:
    """按 (window_class, 栅格) 聚类真实点击，算出热点区（质心 + 半径 + 样本 + 主导作用）。"""
    groups: dict[tuple, list[dict]] = {}
    for r in records:
        cls = r.get("window_class", "")
        gx, gy = _grid_key(*r["rel_pos"])
        groups.setdefault((cls, gx, gy), []).append(r)
    clusters = []
    for key, items in groups.items():
        if len(items) < 2:
            continue  # 单次噪声不聚类
        xs = [i["rel_pos"][0] for i in items]
        ys = [i["rel_pos"][1] for i in items]
        cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
        var = max(sum((x - cx) ** 2 for x in xs) / len(xs),
                  sum((y - cy) ** 2 for y in ys) / len(ys), 1e-5)
        # 主导 effect：出现次数最多的非 none 作用
        eff = {}
        for i in items:
            t = i.get("effect", {}).get("type")
            if t and t != "none":
                eff[t] = eff.get(t, 0) + 1
        dominant_effect = max(eff, key=eff.get) if eff else "none"
        clusters.append({
            "class": key[0], "grid": (key[1], key[2]),
            "centroid": (round(cx, 4), round(cy, 4)),
            "radius": round(2 * var ** 0.5, 4),
            "samples": len(items),
            "dominant_effect": dominant_effect,
            "hwnd": items[0].get("hwnd"),
            "title": items[0].get("window_title", ""),
        })
    return clusters


def _reconcile(sid: str, cluster: dict, labels: list[str]) -> str:
    """把热点区与 Atlas 按钮节点匹配并回写；不匹配返回 pending。

    匹配优先用 OCR 标签对节点 name；无标签则进 pending（不硬回写，符合设计）。
    命中则补 calibrated_bounds + 抬 match_confidence（质检）+ 写转移边（切换逻辑）。
    """
    from .world_model_cache.registry import SoftwareRegistry
    from .world_model_cache.transition_model import record_transition
    entry = SoftwareRegistry().load(sid)
    levels = entry.get("levels", {}) or {}
    label = next((l for l in labels if l and l not in _NOISE), None) if labels else None
    if not label:
        _stash_pending(sid, cluster, [])
        return "pending_no_label"
    matched = None
    for lv in levels.values():
        for node in lv.get("nodes", []) or []:
            if (node.get("name") or "").strip() == label:
                matched = node
                break
        if matched:
            break
    if matched is None:
        _stash_pending(sid, cluster, [label])
        return "pending_unmatched"
    # 命中：回写坐标 + 质检分
    conf = min(1.0, cluster["samples"] / 8.0)
    matched.setdefault("calibrated_bounds",
                       [cluster["centroid"][0], cluster["centroid"][1], 0.04, 0.04])
    matched["calibrated_bounds"][0] = cluster["centroid"][0]
    matched["calibrated_bounds"][1] = cluster["centroid"][1]
    matched["match_confidence"] = round(max(matched.get("match_confidence", 0.0), conf), 3)
    if cluster["dominant_effect"] != "none":
        record_transition(sid, matched.get("identity", label),
                          {f"effect:{cluster['dominant_effect']}"})
    SoftwareRegistry().save(entry)
    return "matched"


def _stash_pending(sid: str, cluster: dict, labels: list[str]) -> None:
    key = f"{sid}|{cluster['grid']}|{labels[0] if labels else ''}"
    cluster["labels"] = labels
    _pending[key] = cluster


def retry_pending() -> int:
    """地图变更后重匹配 pending（长尾不丢）。返回成功匹配数。"""
    if not _pending:
        return 0
    labels_by_key = _ocr_labels_for_pending()
    done, n = [], 0
    for key, cl in _pending.items():
        sid = key.split("|", 1)[0]
        if _reconcile(sid, cl, cl.get("labels", []) or labels_by_key.get(key, [])) == "matched":
            done.append(key)
            n += 1
    for k in done:
        _pending.pop(k, None)
    return n


def _ocr_labels_for_pending() -> dict[str, list[str]]:
    """pending 重匹配时补打 OCR 标签（仅小图，最省）。"""
    from . import ocr_labeler
    out: dict[str, list[str]] = {}
    for key, cl in _pending.items():
        if cl.get("labels"):
            continue
        if ocr_labeler.submit_region(cl.get("hwnd", 0),
                                     (cl["centroid"][0], cl["centroid"][1], 0.06, 0.06), key):
            pass
    res = ocr_labeler.maybe_run_ocr(force=True)
    for k, v in res.items():
        out[k] = v
    return out


def calibrate_once(force: bool = False) -> dict:
    """主入口：攒够阈值或空闲触发聚合校准。force=True 忽略频率（测试/显式）。"""
    global _last_run
    from . import click_collector, ocr_labeler
    pool = click_collector.drain_click_pool()
    if not pool:
        return {"status": "empty"}
    now = time.time()
    if not force and len(pool) < _BATCH_K and (now - _last_run) < _IDLE_S:
        # 未达触发条件：把池子塞回去（drain 已清空，需回填）
        for r in pool:
            click_collector._click_pool.append(r)
        return {"status": "waiting", "pool": len(pool)}
    clusters = _cluster(pool)
    # 给每个热点区提交 OCR 小图（识别点击位置标识），再批量跑
    for cl in clusters:
        ocr_labeler.submit_region(cl.get("hwnd", 0),
                                  (cl["centroid"][0], cl["centroid"][1], 0.06, 0.06),
                                  f"{cl['class']}|{cl['grid']}")
    ocr_labels = ocr_labeler.maybe_run_ocr(force=True)
    matched = pending = 0
    for cl in clusters:
        ckey = f"{cl['class']}|{cl['grid']}"
        sid = _sid_from_cluster(cl)
        if not sid:
            continue
        r = _reconcile(sid, cl, ocr_labels.get(ckey, []))
        if r == "matched":
            matched += 1
        elif r.startswith("pending"):
            pending += 1
    _last_run = now
    return {"status": "done", "clusters": len(clusters),
            "matched": matched, "pending": pending}


def _sid_from_cluster(cluster: dict) -> str:
    """从 cluster 推导 software_id（用窗口 exe 归一化，与 Atlas 同键）。"""
    try:
        from .desktop_control import get_window_exe
        sid = get_window_exe(cluster.get("hwnd", 0))
        return sid or ""
    except Exception:
        return ""

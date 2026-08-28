"""GUI 感知层：渐近式 UIA 扫描 + 桌面上下文 + 目标窗口选择。

设计回应需求②（渐近扫描防崩溃、重扫防漏扫）与⑦（感知桌面窗口数/聚焦）：

- scan_uia_progressive / build_uia_tree_progressive：把一次性全量递归（原 world_model.build_uia_tree）
  改为分批 BFS，批间让出 COM 线程，避免 UIAutomation 主线程争用触发 ntdll 崩溃（Electron 尤甚）；
  首扫后按节点数差异退避重扫，界面仍在加载（迟出现节点）则补扫并打 late_loaded 标记，
  直到达稳定（连续两次节点数一致）或撞 max_rescan 硬上限（绝不高频）。
- perceive_desktop：枚举可见窗口，记录 hwnd/标题/类名/矩形/是否前台，让引擎先知道
  「开了几个窗口、哪个聚焦」，避免误操错窗。
- select_target_window：结合 software_id 与桌面上下文选目标窗，前台优先。
- ensure_foreground：聚焦目标窗，保证后续点击落在正确窗口。

全部纯读取/轻量操控，不降级 OCR（后台接触式采集另见守护设计）。
"""
from __future__ import annotations

import collections
import ctypes
import logging
import time

from .desktop_control import find_window
from .assistive_mode import is_assistive_mode

_LOG = logging.getLogger(__name__)

# 渐近扫描参数：分批大小 / 重扫上限 / 退避间隔(s)——初值需实测微调
PROGRESSIVE_BATCH = 120
MAX_RESCAN = 4
RESCAN_BACKOFF = (0.3, 0.8, 1.5)
MAX_NODES = 1500
MAX_DEPTH = 12


def _area(rect: tuple) -> int:
    """矩形面积；rect 为 (左,上,右,下)。"""
    l, t, r, b = rect
    return max(0, r - l) * max(0, b - t)


def _build_node(control, node_id: int, parent_id: int) -> dict:
    """把单个 UIA 控件转成与 world_model 同构的 dict（分批 BFS 专用，不从树递归取值）。

    与 world_model._walk_uia 同属「控件→节点」转换，但后者是递归且直接挂 children；
    此处需在 BFS 队列中按 id 回填 parent，结构不同，故不合并（避免跨遍历耦合）。
    """
    try:
        rect = control.BoundingRectangle
        node_rect = (rect.left, rect.top, rect.right, rect.bottom)
    except Exception:
        node_rect = (0, 0, 0, 0)
    try:
        name = control.Name or ""
    except Exception:
        name = ""
    try:
        visible = not control.IsOffscreen
    except Exception:
        visible = True
    try:
        enabled = control.IsEnabled
    except Exception:
        enabled = True
    try:
        sel_pat = control.GetSelectionItemPattern()
        selected = bool(sel_pat.IsSelected) if sel_pat else False
    except Exception:
        selected = False
    return {
        "id": node_id,
        "parent_id": parent_id,
        "name": name,
        "control_type": control.ControlTypeName,
        "automation_id": getattr(control, "AutomationId", "") or "",
        "class_name": control.ClassName,
        "rect": node_rect,
        "visible": visible,
        "enabled": enabled,
        "image_confirmed": False,
        "visible_text": "",
        "selected": selected,
        "children": [],
    }


def _batch_walk(root, batch: int, max_nodes: int, max_depth: int):
    """分批 BFS 遍历 UIA 树；批间让出线程，避免长遍历卡死目标应用（尤其 Electron）。

    返回 (根节点 dict, 带坐标扁平节点列表, 节点总数)。根节点 id=1、parent=0 不挂父。
    """
    by_id: dict[int, dict] = {}
    flat: list[dict] = []
    count = 0
    queue = collections.deque([(root, 0, 0)])  # (control, depth, parent_id)
    while queue and count < max_nodes:
        take = min(batch, len(queue))
        for _ in range(take):
            if count >= max_nodes:
                break
            ctrl, depth, pid = queue.popleft()
            count += 1
            node = _build_node(ctrl, count, pid)
            by_id[node["id"]] = node
            if pid and pid in by_id:
                by_id[pid]["children"].append(node)
            if _area(node["rect"]) > 0:
                flat.append(node)
            if depth < max_depth:
                try:
                    for child in ctrl.GetChildren():
                        queue.append((child, depth + 1, node["id"]))
                except Exception:
                    pass
        if take:
            time.sleep(0)  # 让出线程调度，缓解 UIAutomation 线程争用
    root_node = by_id.get(1) or {
        "id": 0, "parent_id": 0, "name": "", "control_type": "Window",
        "automation_id": "", "class_name": "", "rect": (0, 0, 0, 0),
        "visible": True, "enabled": True, "image_confirmed": False,
        "visible_text": "", "selected": False, "children": [],
    }
    return root_node, flat, count


def build_uia_tree_progressive(hwnd: int, batch: int = PROGRESSIVE_BATCH,
                              max_nodes: int = MAX_NODES, max_depth: int = MAX_DEPTH,
                              max_rescan: int = MAX_RESCAN,
                              backoff: tuple = RESCAN_BACKOFF) -> dict:
    """渐近式构建 UIA 树：分批扫描 + 退避重扫，规避两类失败。

    - 崩溃防护：单次遍历分批 BFS，批间让出线程（②点「一次不要扫太多」）。
    - 漏扫防护：首扫后比对节点数，界面仍在加载则按 backoff 退避重扫、补出迟出现节点
      （late_loaded），直到达稳定（连续两次节点数一致）或撞 max_rescan 硬上限（绝不高频）。
    返回结构与原 build_uia_tree 同构，便于下游无缝替换；附 rescan_count/late_loaded_count/stable
    供上层判断「树是否已就绪」。
    """
    import uiautomation as auto

    root = auto.ControlFromHandle(hwnd)
    prev_count = -1
    late_loaded = 0
    attempts = 0
    for attempt in range(max_rescan + 1):
        tree, flat, count = _batch_walk(root, batch, max_nodes, max_depth)
        if count == prev_count:
            break  # 稳定：界面不再变化
        if prev_count >= 0:
            late_loaded += max(0, count - prev_count)
        prev_count = count
        attempts = attempt
        if attempt < max_rescan:
            time.sleep(backoff[min(attempt, len(backoff) - 1)])
    stable = count == prev_count or attempts >= max_rescan
    if is_assistive_mode():
        _LOG.info("辅助模式开启中：UIA 树按屏幕阅读器视图构建（hwnd=%s, nodes=%s）", hwnd, count)
    return {
        "tree": tree, "flat": flat, "node_count": count,
        "late_loaded_count": late_loaded, "rescan_count": attempts,
        "stable": stable,
    }


def perceive_desktop() -> dict:
    """枚举可见窗口，输出桌面上下文：开了几个窗口、哪个是前台。

    纯读取（EnumWindows + GetWindowText/GetClassName/GetWindowRect），
    不抢焦点、不截图、不注入，可作为 automate 引擎首步低成本判断目标窗。
    """
    u32 = ctypes.windll.user32
    fg = u32.GetForegroundWindow()
    windows: list[dict] = []

    def cb(hwnd, _):
        if not u32.IsWindowVisible(hwnd):
            return True
        n = u32.GetWindowTextLengthW(hwnd)
        title = ""
        if n > 0:
            buf = ctypes.create_unicode_buffer(n + 1)
            u32.GetWindowTextW(hwnd, buf, n + 1)
            title = buf.value
        cls = ctypes.create_unicode_buffer(128)
        u32.GetClassNameW(hwnd, cls, 128)
        r = ctypes.wintypes.RECT()
        u32.GetWindowRect(hwnd, ctypes.byref(r))
        windows.append({
            "hwnd": hwnd, "title": title, "class_name": cls.value,
            "rect": (r.left, r.top, r.right, r.bottom),
            "is_foreground": hwnd == fg,
        })
        return True

    cb_t = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(cb)
    u32.EnumWindows(cb_t, 0)
    # 前台优先排序，便于 select_target_window 退化时取前台
    windows.sort(key=lambda w: (not w["is_foreground"], w["hwnd"]))
    return {"foreground_hwnd": fg, "windows": windows, "count": len(windows)}


def select_target_window(software_id: str, ctx: dict | None = None) -> int:
    """结合 software_id 与桌面上下文选目标窗口；前台优先的退化链。

    标题子串命中 → 上下文内标题含 software_id → 前台窗口。返回 hwnd（0=未选中）。
    """
    if not software_id:
        return (ctx or {}).get("foreground_hwnd", 0)
    found = find_window(software_id)  # 标题子串，取面积最大者
    if found:
        return found[0]
    if ctx:
        for w in ctx["windows"]:
            if software_id.lower() in (w["title"] or "").lower():
                return w["hwnd"]
    return (ctx or {}).get("foreground_hwnd", 0)


def ensure_foreground(hwnd: int) -> bool:
    """聚焦目标窗口（轻量），保证后续点击落在正确窗口；返回是否成功聚焦。"""
    if not hwnd:
        return False
    u32 = ctypes.windll.user32
    if not u32.IsWindow(hwnd):
        return False
    u32.SetForegroundWindow(hwnd)
    time.sleep(0.05)
    return u32.GetForegroundWindow() == hwnd

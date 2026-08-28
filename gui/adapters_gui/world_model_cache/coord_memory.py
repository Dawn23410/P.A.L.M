"""跨会话控件坐标记忆（越用越快）：补足「首点跳过 UIA 重扫」的跨重启/重开窗缺口。

与 Atlas 静态地图、转移规律层正交：
- Atlas 只存结构（不存坐标值作运行态）→ 铁律仍在；
- 转移规律层存「动作→界面控件集合」统计（dynamics）；
- 本层只存「某软件某控件相对窗口的归一化包围盒中心」，进程重启或窗口关闭重开后
  仍可直接 denormalize 出绝对坐标 + O(1) 命中测试（ControlFromPoint），
  跳过 find_control_direct 的 UIA 树深度遍历（depth 12/24 walk，84–515ms）。

零 LLM 依赖；落盘 gui_coord_memory 分类，经 storage 砖 fail-soft（砖未就绪仅留缓存）。
"""
from __future__ import annotations

import json

from .transition_model import _storage_cap

COORD_CATEGORY = "gui_coord_memory"


def _read_coord(store, software_id: str):
    """经 storage 砖读回坐标条目 JSON（失败返回 None）。"""
    find_cap = _storage_cap("find_config_file")
    read_cap = _storage_cap("read_file_content")
    if not find_cap or not read_cap:
        return None
    rec = find_cap(COORD_CATEGORY, f"{software_id}.json")
    if not rec:
        return None
    data = read_cap(rec.id)
    if data is None:
        return None
    try:
        return json.loads(data.decode("utf-8"))
    except Exception:
        return None


def _write_coord(store, software_id: str, entry: dict) -> bool:
    """经 storage 砖写盘坐标条目（不可用则仅留缓存）。"""
    cap = _storage_cap("store_file")
    if not cap:
        return False
    data = json.dumps(entry, ensure_ascii=False).encode("utf-8")
    cap(COORD_CATEGORY, f"{software_id}.json", data, True)
    return True


class CoordMemory:
    """进程内坐标注册表（单例），持久化经 storage 砖（与 TransitionStore 平行）。"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._cache: dict[str, dict] = {}
        return cls._instance

    def load(self, software_id: str) -> dict:
        if software_id in self._cache:
            return self._cache[software_id]
        entry = None
        store = _storage_cap("get_store")()
        if store is not None:
            entry = _read_coord(store, software_id)
        if entry is None:
            entry = {"software_id": software_id, "coords": {}}
        self._cache[software_id] = entry
        return entry

    def save(self, entry: dict) -> bool:
        software_id = entry.get("software_id", "unknown")
        self._cache[software_id] = entry
        store = _storage_cap("get_store")()
        if store is None:
            return False
        return _write_coord(store, software_id, entry)


def save_coord(software_id: str, key: str, nx: float, ny: float, nw: float, nh: float) -> bool:
    """记录某控件相对窗口的归一化包围盒中心(nx,ny)与尺寸(nw,nh)。

    nx,ny,nh,nw ∈ [0,1]；越界直接拒绝。EMI 中心继续用于 get_coord 兼容旧调用；
    同时累积二阶矩（sx/sy/sxx/syy/sxy）供概率区域模型拟合人类点击散布半径。
    单次样本置信极低：samples<2 时区域不可信，须多样本收敛（契合保守基调）。
    """
    if not software_id or not key:
        return False
    if not (0.0 <= nx <= 1.0 and 0.0 <= ny <= 1.0):
        return False
    mem = CoordMemory()
    entry = mem.load(software_id)
    coords = entry.setdefault("coords", {})
    rec = coords.get(key)
    if rec is None:
        coords[key] = {"nx": nx, "ny": ny, "nw": nw, "nh": nh, "samples": 1,
                       "sx": nx, "sy": ny, "sxx": nx * nx, "syy": ny * ny, "sxy": nx * ny}
    else:
        # EMA 中心：半窗抑制单次噪声（get_coord 兼容）
        a = 0.5
        rec["nx"] = rec["nx"] * (1 - a) + nx * a
        rec["ny"] = rec["ny"] * (1 - a) + ny * a
        rec["nw"] = rec["nw"] * (1 - a) + nw * a
        rec["nh"] = rec["nh"] * (1 - a) + nh * a
        # 累积矩：全量，供散布半径（方差）估算
        s = rec.get("samples", 1) + 1
        rec["sx"] = rec.get("sx", nx) + nx
        rec["sy"] = rec.get("sy", ny) + ny
        rec["sxx"] = rec.get("sxx", nx * nx) + nx * nx
        rec["syy"] = rec.get("syy", ny * ny) + ny * ny
        rec["sxy"] = rec.get("sxy", nx * ny) + nx * ny
        rec["samples"] = s
    return mem.save(entry)


def get_coord(software_id: str, key: str) -> tuple[float, float, float, float] | None:
    """返回归一化包围盒(nx,ny,nw,nh)；观测不足 2 次或缺失返回 None（单次噪声不可信）。"""
    entry = CoordMemory().load(software_id)
    rec = (entry.get("coords") or {}).get(key)
    if not rec or rec.get("samples", 0) < 2:
        return None
    return (rec["nx"], rec["ny"], rec["nw"], rec["nh"])


def get_coord_stats(software_id: str) -> dict:
    """坐标记忆统计：控件数与其中已达可信样本(≥2)的数量（供联动度审计聚合）。"""
    entry = CoordMemory().load(software_id)
    coords = (entry.get("coords") or {})
    return {"coords": len(coords),
            "trusted": sum(1 for c in coords.values() if c.get("samples", 0) >= 2)}


def region_for(software_id: str, key: str) -> dict | None:
    """拟合人类点击概率区域：质心 + 散布半径（由累积二阶矩估算），区域大小随样本散布决定。

    返回 {centroid:(cx,cy), radius, n_samples, trusted}；样本<2 或缺失返回 None（不可信）。
    人无法稳定点在同一像素，区域半径=2*sqrt(var_x+var_y)，覆盖约 95% 真实点击散布。
    """
    entry = CoordMemory().load(software_id)
    rec = (entry.get("coords") or {}).get(key)
    if not rec or rec.get("samples", 0) < 2:
        return None
    s = rec["samples"]
    mx, my = rec["sx"] / s, rec["sy"] / s
    var_x = max(rec["sxx"] / s - mx * mx, 1e-6)
    var_y = max(rec["syy"] / s - my * my, 1e-6)
    radius = 2.0 * (var_x + var_y) ** 0.5
    return {"centroid": (mx, my), "radius": radius, "n_samples": s, "trusted": True}


def region_argmax(software_id: str, key: str,
                  candidates: list[dict]) -> dict | None:
    """区域内候选 argmax 消歧（无 LLM）：先排除落在人类点击区域外的候选，再取最高分。

    candidates: [{center:(x,y), weight:float, ...}]，center 为归一化相对坐标。
    返回选中的候选；若无区域先验或无候选则退化返回最高 weight 候选。
    得分 = weight × 区域高斯密度（越靠近质心越密），实现"最可能点击点"消歧。
    """
    if not candidates:
        return None
    reg = region_for(software_id, key)
    if reg is None or not reg["trusted"]:
        return max(candidates, key=lambda c: c.get("weight", 0.0))
    cx, cy = reg["centroid"]
    r = reg["radius"]

    def _density(center):
        dx, dy = center[0] - cx, center[1] - cy
        d2 = (dx * dx + dy * dy) / (r * r + 1e-9)
        return (2.71828 ** (-d2 / 2.0))

    in_region = [c for c in candidates
                 if ((c["center"][0] - cx) ** 2 + (c["center"][1] - cy) ** 2) ** 0.5 <= r * 1.5]
    pool = in_region or candidates  # 全超范围则退化不丢弃
    return max(pool, key=lambda c: c.get("weight", 0.0) * _density(c["center"]))

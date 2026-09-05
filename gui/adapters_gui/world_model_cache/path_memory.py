"""路线记忆：自动记录 LLM 正常路线与异常处理路线，按意图关键词检索，LLM 免费复用。

与 Atlas/转移/坐标三层正交：
- Atlas 存结构、转移存 dynamics、坐标存位置；
- 本层存「意图→有序操作步骤」的**经验路线**（正常=LLM 成功路径；异常=LLM 纠正/兜底路径）。

落盘 gui_routes 分类，经 storage 砖 capability fail-soft（砖不可用时仅留进程内缓存）。
适配性设计：
- 缩放：路线步骤用 name/automation_id/control_type 结构性 identity，不存绝对坐标 → 分辨率/DPI 无关；
- 软件更新：每条路线带层级结构签名，查询时比对当前签名，不一致即判过期并降权（触发 LLM 重规划）。
"""
from __future__ import annotations

import json
import re
import time
from collections import defaultdict

from .transition_model import _storage_cap

ROUTE_CATEGORY = "gui_routes"

_STOP = {"的", "了", "请", "帮", "我", "把", "在", "中", "里", "去", "到",
         "一个", "一下", "怎么", "如何", "想", "要", "让"}
_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]+|[a-zA-Z]+")

# 置信度（执行度）校准：多信号渐进累加，避免「单次 LLM 命中即全盘信任推理」。
# 设计要点：单次 LLM 落盘只给基线+小幅增量，需多次佐证/执行成功才会越过信任带，
# 满足「不要一次 LLM 完全命中就直接全部使用推理」。
_TRUST_INIT = 0.12        # 路线首次由 LLM 落盘时的基线置信度
_TRUST_PLAN = 0.14        # 每次 LLM 再次确认/落盘同一路线
_TRUST_EXEC_OK = 0.10     # 执行器上报执行成功（越用越准的核心回写）
_TRUST_TRANSITION = 0.08  # 转移规律层佐证步骤链（跨层联动）
_TRUST_COORD = 0.06       # 坐标记忆已覆盖（可省 UIA 重扫，越用越快）
_TRUST_EXEC_FAIL = -0.28  # 执行失败（直接降信任）
_TRUST_LLM_REJECT = -0.22 # LLM 判定推断路线错误
_TRUST_MIN, _TRUST_MAX = 0.0, 1.0

# 信任带（reasoning_hub 据置信度判 trusted/verify/weak）
TRUST_HIGH = 0.80         # ≥ 此值：纯推理执行，无需 LLM、无需事后校验
TRUST_MID = 0.40          # ≥ 此值：推理执行但强制事后校验；以下：仍走 LLM


def _clamp_conf(v: float) -> float:
    return max(_TRUST_MIN, min(_TRUST_MAX, v))


def intent_signature(intent: str) -> set[str]:
    """意图→关键词签名（去停用词；英文整词 + 中文 unigram/bigram，语序无关）。

    近似意图靠集合 Jaccard 重叠匹配，容忍措辞与语序差异（"打开蓝牙"≈"把蓝牙打开"）。
    中文发射所有 1-gram/2-gram 而非整词，避免"蓝牙打开"与"打开蓝牙"因顺序不同而漏匹配；
    控件名匹配（_score_control）只取 len≥2 的 token，bigram 足以覆盖"蓝牙"等目标词。
    """
    toks: set[str] = set()
    for m in _TOKEN_RE.findall((intent or "").lower()):
        if re.fullmatch(r"[a-z]+", m):
            toks.add(m)
            continue
        for i in range(len(m)):
            toks.add(m[i:i + 1])          # 1-gram
            if i + 2 <= len(m):
                toks.add(m[i:i + 2])      # 2-gram
    return {t for t in toks if t not in _STOP}


def _signature_overlap(a: set, b: set) -> float:
    """Jaccard 相似度：两意图签名重叠比例（0~1）。"""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _route_id(sid: str, sig: list[str]) -> str:
    return f"{sid}:{hash(frozenset(sig)) % 100000}"


def _now() -> float:
    return time.time()


def _read_routes(store, software_id):
    find_cap = _storage_cap("find_config_file")
    read_cap = _storage_cap("read_file_content")
    if not find_cap or not read_cap:
        return None
    rec = find_cap(ROUTE_CATEGORY, f"{software_id}.json")
    if not rec:
        return None
    data = read_cap(rec.id)
    if data is None:
        return None
    try:
        return json.loads(data.decode("utf-8"))
    except Exception:
        return None


def _write_routes(store, software_id, entry):
    cap = _storage_cap("store_file")
    if not cap:
        return False
    data = json.dumps(entry, ensure_ascii=False).encode("utf-8")
    cap(ROUTE_CATEGORY, f"{software_id}.json", data, True)
    return True


class RouteStore:
    """进程内路线注册表（单例），持久化经 storage 砖（与 TransitionStore/CoordMemory 平行）。"""

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
        store_cap = _storage_cap("get_store")
        store = store_cap() if store_cap else None
        if store is not None:
            entry = _read_routes(store, software_id)
        if entry is None:
            entry = {"software_id": software_id, "routes": {}, "exceptions": {}}
        self._cache[software_id] = entry
        return entry

    def save(self, entry: dict) -> bool:
        software_id = entry.get("software_id", "unknown")
        self._cache[software_id] = entry
        store_cap = _storage_cap("get_store")
        store = store_cap() if store_cap else None
        if store is None:
            return False
        return _write_routes(store, software_id, entry)


def record_route(software_id: str, intent: str, steps: list, outcome: str = "ok",
                 source: str = "llm", structural_sig: str = "") -> bool:
    """记录一条路线（正常=LLM 成功路径）。同意图签名累加样本、用最新成功步骤覆盖（越用越准）。"""
    if not software_id or not steps:
        return False
    sig = sorted(intent_signature(intent))
    rid = _route_id(software_id, sig)
    store = RouteStore()
    entry = store.load(software_id)
    routes = entry.setdefault("routes", {})
    r = routes.get(rid)
    if r is None:
        r = {"route_id": rid, "intent_sig": sig, "intent_raw": intent,
             "steps": steps, "outcome": outcome, "source": source,
             "samples": 0, "confidence": _TRUST_INIT, "structural_sig": structural_sig,
             "last_used": 0}
    r["samples"] += 1
    r["steps"] = steps
    r["outcome"] = outcome
    r["source"] = source
    r["structural_sig"] = structural_sig
    # 渐进累加：首次为基线，后续每次 LLM 确认仅小幅提升，绝不一次封顶。
    r["confidence"] = round(_clamp_conf(r["confidence"] + _TRUST_PLAN), 3)
    r["last_used"] = _now()
    routes[rid] = r
    return store.save(entry)


def query_route(software_id: str, intent: str, current_struct_sig: str = "",
                 min_samples: int = 1) -> dict | None:
    """查询最匹配的正常路线；返回带 stale 标志与置信度的路线 dict 或 None。

    门限：意图重叠≥0.5（样本≥最小门限，默认 1）。置信度由 record_route 渐进累加，
    信任等级（trusted/verify/weak）由 reasoning_hub 据置信度判定，本函数只负责检索。
    结构签名不一致即判 stale 并降权 0.4，仍可达门限才返回（软件更新后主动退化到 LLM 重规划）。
    """
    sig = intent_signature(intent)
    entry = RouteStore().load(software_id)
    routes = entry.get("routes", {}) or {}
    best, best_score = None, 0.0
    for r in routes.values():
        if r.get("outcome") != "ok":
            continue
        ov = _signature_overlap(set(r.get("intent_sig", [])), sig)
        if ov < 0.5:
            continue
        stale = bool(current_struct_sig and r.get("structural_sig")
                     and current_struct_sig != r.get("structural_sig"))
        conf = r["confidence"] * (0.4 if stale else 1.0)
        score = ov * conf
        if r["samples"] >= min_samples and score > best_score:
            best_score = score
            best = dict(r, stale=stale, confidence=round(conf, 3))
    return best


def _locate_route(entry: dict, sig: set[str], min_ov: float = 0.5) -> dict | None:
    """按意图签名定位最匹配的正常路线（供回写/佐证时复用）。"""
    best, best_ov = None, 0.0
    for r in (entry.get("routes", {}) or {}).values():
        if r.get("outcome") != "ok":
            continue
        ov = _signature_overlap(set(r.get("intent_sig", [])), sig)
        if ov >= min_ov and ov > best_ov:
            best_ov, best = ov, r
    return best


def adjust_confidence(software_id: str, intent: str, delta: float, reason: str = "") -> bool:
    """按意图定位路线并调整其置信度（多信号渐进累加的核心写入口）。"""
    if not software_id or not intent:
        return False
    sig = intent_signature(intent)
    store = RouteStore()
    entry = store.load(software_id)
    r = _locate_route(entry, sig)
    if not r:
        return False
    r["confidence"] = round(_clamp_conf(r["confidence"] + delta), 3)
    r.setdefault("signals", []).append({"d": round(delta, 3), "reason": reason, "t": _now()})
    r["last_used"] = _now()
    return store.save(entry)


def report_execution(software_id: str, intent: str, success: bool) -> bool:
    """执行器回写：路线实际执行成功→加信任（越用越准）；失败→降信任。

    闭环关键：让「越用越准」从单方向记忆真正变成双向校准——执行反馈反向调制置信度，
    避免一条偶然成功的路线被永久高估。
    """
    delta = _TRUST_EXEC_OK if success else _TRUST_EXEC_FAIL
    return adjust_confidence(software_id, intent, delta,
                             "exec_ok" if success else "exec_fail")


def get_route_stats(software_id: str) -> dict:
    """路线记忆统计：正常路线数、异常路线数、全部路线明细（供联动度审计聚合）。"""
    entry = RouteStore().load(software_id)
    routes = (entry.get("routes", {}) or {})
    ex = (entry.get("exceptions", {}) or {})
    return {"ok_routes": sum(1 for r in routes.values() if r.get("outcome") == "ok"),
            "total_routes": len(routes), "exceptions": len(ex),
            "routes": list(routes.values())}


def record_exception(software_id: str, intent: str, failed_steps: list,
                     recovered_steps: list, exception_type: str = "") -> bool:
    """记录异常处理路线：LLM 首规划失败后纠正出的可用路径（下次主动规避同一坑）。"""
    if not software_id or not recovered_steps:
        return False
    sig = sorted(intent_signature(intent))
    rid = _route_id(software_id, sig) + ":ex"
    store = RouteStore()
    entry = store.load(software_id)
    ex = entry.setdefault("exceptions", {})
    rec = ex.get(rid)
    if rec is None:
        rec = {"route_id": rid, "intent_sig": sig, "intent_raw": intent,
               "failed_steps": failed_steps, "recovered_steps": recovered_steps,
               "exception_type": exception_type, "samples": 0, "last_used": 0}
    rec["samples"] += 1
    rec["recovered_steps"] = recovered_steps
    rec["failed_steps"] = failed_steps
    rec["exception_type"] = exception_type
    rec["last_used"] = _now()
    ex[rid] = rec
    return store.save(entry)


def query_exception(software_id: str, intent: str) -> dict | None:
    """查询已知异常处理路线（同意图重叠≥0.5）。返回 recovered_steps 供中枢优先采用。"""
    sig = intent_signature(intent)
    entry = RouteStore().load(software_id)
    ex = entry.get("exceptions", {}) or {}
    for r in ex.values():
        if _signature_overlap(set(r.get("intent_sig", [])), sig) >= 0.5:
            return r
    return None

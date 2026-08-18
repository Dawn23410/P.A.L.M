"""转移规律层（经验式 dynamics）：补足严格世界模型定义的转移动态缺口。

与 Atlas 静态认知地图正交：
- Atlas 只存「有什么界面/控件」（结构，不存动态值、不作运行态）；
- 本层只存「在某软件点了某控件后，界面通常出现哪些控件」（经验式转移统计），
  归独立的 gui_transitions 落盘分类，绝不回写 Atlas 静态地图。

零 LLM 依赖：纯统计高频共现；置信度 = 该控件在历史样本中的出现比例。
接入点（见 atlas_tool.DescribeWindowTool）：
- anticipate=True：附历史高频控件先验，压缩规划上下文；
- record_action=label：感知后记录「label→当前控件集合」转移。
"""
from __future__ import annotations

import json
from collections import defaultdict

TRANSITION_CATEGORY = "gui_transitions"

# 噪声过滤（与 atlas_tool 对齐，避免把标题栏/搜索框计入转移）
_NOISE_CT = {"WindowControl", "TitleBar", "MenuBarControl", "MenuItemControl",
             "TextControl", "ToolTipControl", "EditControl", "ListControl",
             "ScrollBarControl", "PaneControl", "GroupControl"}
_NOISE_NAME = {"设置", "系统", "最小化", "最大化", "关闭", "搜索框，查找设置"}


def _storage_cap(name):
    """惰性取 storage 砖 capability；砖未就绪时返回 None（fail-soft）。"""
    try:
        from palm_sdk.bricks.storage import brick as storage_brick
    except Exception:
        return None
    return getattr(storage_brick, "capabilities", {}).get(name)


def _get_store():
    cap = _storage_cap("get_store")
    return cap() if cap else None


def _read_transition(store, software_id):
    """经 storage 砖 capability 读回转移条目 JSON（失败返回 None）。"""
    find_cap = _storage_cap("find_config_file")
    read_cap = _storage_cap("read_file_content")
    if not find_cap or not read_cap:
        return None
    rec = find_cap(TRANSITION_CATEGORY, f"{software_id}.json")
    if not rec:
        return None
    data = read_cap(rec.id)
    if data is None:
        return None
    try:
        return json.loads(data.decode("utf-8"))
    except Exception:
        return None


def _write_transition(store, software_id, entry):
    """经 storage 砖 capability 写盘转移条目（不可用则仅留缓存）。"""
    cap = _storage_cap("store_file")
    if not cap:
        return False
    data = json.dumps(entry, ensure_ascii=False).encode("utf-8")
    cap(TRANSITION_CATEGORY, f"{software_id}.json", data, True)
    return True


def _control_key(control_type: str, automation_id: str, name: str) -> str | None:
    """控件规范化标识（类比 Atlas identity 的轻量版，用于跨会话稳定匹配）。"""
    aid = automation_id or name or ""
    if not aid:
        return None
    return f"{control_type}|{aid}"


def extract_control_keys(controls: list[dict]) -> set[str]:
    """从 describe_window 的 controls 列表抽取去噪控件标识集合。"""
    keys: set[str] = set()
    for c in controls:
        if c.get("control_type") in _NOISE_CT or (c.get("name") or "") in _NOISE_NAME:
            continue
        k = _control_key(c.get("control_type", ""), c.get("automation_id", ""), c.get("name", ""))
        if k:
            keys.add(k)
    return keys


class TransitionStore:
    """进程内转移注册表（单例），持久化经 storage 砖（与 SoftwareRegistry 平行）。"""

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
        store = _get_store()
        if store is not None:
            entry = _read_transition(store, software_id)
        if entry is None:
            entry = {"software_id": software_id, "transitions": {}, "version": 1}
        self._cache[software_id] = entry
        return entry

    def save(self, entry: dict) -> bool:
        software_id = entry.get("software_id", "unknown")
        self._cache[software_id] = entry
        store = _get_store()
        if store is None:
            return False
        return _write_transition(store, software_id, entry)


def record_transition(software_id: str, action_label: str, resulting_keys: set[str]) -> bool:
    """记录一次转移：在某软件执行 action_label 后，界面出现 resulting_keys 控件集合。

    纯累加统计；置信度由 query 阶段按样本比例计算，避免存冗余派生值。
    """
    if not software_id or not action_label or not resulting_keys:
        return False
    store = TransitionStore()
    entry = store.load(software_id)
    trans = entry.setdefault("transitions", {})
    rec = trans.setdefault(action_label, {"samples": 0, "outcomes": {}})
    rec["samples"] += 1
    for k in resulting_keys:
        rec["outcomes"][k] = rec["outcomes"].get(k, 0) + 1
    entry["version"] = entry.get("version", 1) + 1
    return store.save(entry)


def query_expected(software_id: str, action_label: str, threshold: float = 0.5,
                   min_samples: int = 3) -> list[tuple[str, float]]:
    """查询某动作后的预期控件（出现比例≥threshold），返回 [(control_key, confidence)] 降序。

    min_samples：最小样本门限（默认 3）。样本不足时返回空——避免单次偶发观察被当成
    置信度 1.0 的铁律污染预测（"越用越准"的前提：噪声样本不进入预测）。
    """
    entry = TransitionStore().load(software_id)
    rec = (entry.get("transitions") or {}).get(action_label)
    if not rec or rec["samples"] < min_samples:
        return []
    n = rec["samples"]
    out = [(k, round(c / n, 3)) for k, c in rec["outcomes"].items() if c / n >= threshold]
    out.sort(key=lambda x: -x[1])
    return out


def query_software_expected(software_id: str, threshold: float = 0.5,
                            min_samples: int = 3) -> list[tuple[str, float]]:
    """不指定动作时，返回该软件跨动作的全局高频控件（规划先验）。

    min_samples：单控件累计出现次数门限（默认 3），过滤偶发噪声控件。
    """
    entry = TransitionStore().load(software_id)
    totals: dict[str, int] = defaultdict(int)
    samples = 0
    for rec in (entry.get("transitions") or {}).values():
        samples += rec["samples"]
        for k, c in rec["outcomes"].items():
            totals[k] += c
    if samples == 0:
        return []
    out = [(k, round(c / samples, 3)) for k, c in totals.items()
           if c >= min_samples and c / samples >= threshold]
    out.sort(key=lambda x: -x[1])
    return out


def get_transition_stats(software_id: str) -> dict:
    """转移规律层统计：动作数与累计样本数（供推理中枢联动度审计聚合）。"""
    entry = TransitionStore().load(software_id)
    trans = (entry.get("transitions") or {})
    return {"actions": len(trans),
            "samples": sum(r.get("samples", 0) for r in trans.values())}
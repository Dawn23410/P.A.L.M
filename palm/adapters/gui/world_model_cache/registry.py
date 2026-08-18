"""SoftwareRegistry：按 software_id 聚合 Atlas，经 storage 砖 capability 落盘。

gui 工具组不跨砖 import storage 内部，仅经其 capabilities 取用 store/读写原语（缺失降级 None）。
"""
from __future__ import annotations

import json

from .schema import ATLAS_CATEGORY


def _storage_cap(name):
    """惰性取 storage 砖 capability；砖未就绪时返回 None（fail-soft）。"""
    try:
        from palm._core.container import brick as storage_brick
    except Exception:
        return None
    return getattr(storage_brick, "capabilities", {}).get(name)


def _get_store():
    cap = _storage_cap("get_store")
    return cap() if cap else None


def _read_atlas(store, software_id):
    """经 storage 砖 capability 读回 Atlas 条目（JSON 解析失败返回 None）。

    capability 闭包已绑定 store，调用时不再传 store。
    """
    find_cap = _storage_cap("find_config_file")
    read_cap = _storage_cap("read_file_content")
    if not find_cap or not read_cap:
        return None
    rec = find_cap(ATLAS_CATEGORY, f"{software_id}.json")
    if not rec:
        return None
    data = read_cap(rec.id)
    if data is None:
        return None
    try:
        return json.loads(data.decode("utf-8"))
    except Exception:
        return None


def _write_atlas(store, software_id, entry):
    """经 storage 砖 capability 写盘 Atlas 条目（dedupe_name 避免同名副本累积）。

    capability 闭包已绑定 store，调用时不再传 store。
    """
    cap = _storage_cap("store_file")
    if not cap:
        return False
    data = json.dumps(entry, ensure_ascii=False).encode("utf-8")
    cap(ATLAS_CATEGORY, f"{software_id}.json", data, True)
    return True


class SoftwareRegistry:
    """进程内 Atlas 注册表（单例），持久化经 storage 砖。"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._cache = {}
        return cls._instance

    def load(self, software_id):
        """载入软件条目：先查进程内缓存，再回退 storage 落盘。"""
        if software_id in self._cache:
            return self._cache[software_id]
        entry = None
        store = _get_store()
        if store is not None:
            entry = _read_atlas(store, software_id)
        if entry is None:
            entry = {"software_id": software_id, "levels": {}, "version": 1}
        self._cache[software_id] = entry
        return entry

    def save(self, entry):
        """落盘软件条目：更新缓存并经 storage capability 写盘（不可用则仅留缓存）。"""
        software_id = entry.get("software_id", "unknown")
        self._cache[software_id] = entry
        store = _get_store()
        if store is None:
            return False
        return _write_atlas(store, software_id, entry)

    def get(self, software_id):
        return self.load(software_id)


def list_software_ids():
    """枚举已持久化的 Atlas 软件条目（仅文件名，免解密开销）。

    落盘文件名即 {software_id}.json，故无需解密即可拿到全部软件清单，
    供 get_cognitive_map 的「罗列已知软件」入口使用。砖不可用时返回空列表。
    """
    store = _get_store()
    if not store:
        return []
    try:
        state = store.get_state()
    except Exception:
        return []
    ids = []
    for f in getattr(state, "files", []):
        cat = getattr(f, "category", None)
        name = getattr(f, "name", "")
        if cat != ATLAS_CATEGORY or not name.endswith(".json"):
            continue
        sid = name[:-5]
        # 过滤存储探针（__probe__）与退化兜底（unknown：exe 无法解析），避免污染规划目录。
        if sid.startswith("__") or sid == "unknown":
            continue
        ids.append(sid)
    return ids
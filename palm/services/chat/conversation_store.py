"""会话记录服务：聊天记录落盘与恢复（收敛自 conversations 砖）。

底层落盘委托存储适配器（store_file 含加密与 pool.json 索引），复用 PoolStore
单例避免双实例竞争；经服务容器取存储句柄，不直接 import 存储内部模块。
孤立代理对（被截断的 emoji 高位）是非法 Unicode，落盘前递归清除避免保存 500。
"""
from __future__ import annotations

import json
import re

from palm._core.logging import get_logger
from palm._core.container import container
from palm._core.housekeeping import emit_entity_deleted, ENTITY_CONVERSATION

logger = get_logger(__name__)

CONVERSATION_CATEGORY = "对话记录"

_SURROGATE_RE = re.compile(r"[\ud800-\udfff]")


def _strip_surrogates(obj):
    """递归移除字符串中的孤立代理对，其余类型原样返回。"""
    if isinstance(obj, str):
        return _SURROGATE_RE.sub("", obj)
    if isinstance(obj, list):
        return [_strip_surrogates(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _strip_surrogates(v) for k, v in obj.items()}
    return obj


def _storage_capabilities() -> dict:
    storage = container.get("storage")
    if not storage:
        return {}
    return getattr(storage, "capabilities", {}) or {}


def _store():
    """取存储适配器的 PoolStore 单例（避免双实例竞争 pool.json）。"""
    get_store = _storage_capabilities().get("get_store")
    return get_store() if callable(get_store) else None


def save_conversation_log(conv_id: str, payload: dict):
    """以 <convId>.json 固定文件名 upsert；委托存储适配器 store_file（含加密+索引）。"""
    store_file = _storage_capabilities().get("store_file")
    if not store_file:
        return None
    return store_file(
        CONVERSATION_CATEGORY,
        f"{conv_id}.json",
        json.dumps(_strip_surrogates(payload), ensure_ascii=False).encode("utf-8"),
        dedupe_name=True,
    )


def load_all_conversations() -> list[dict]:
    """读回「对话记录」分类下全部会话 JSON；损坏文件跳过不阻断其余。"""
    store = _store()
    if store is None:
        return []
    read_file_content = _storage_capabilities().get("read_file_content")
    if not read_file_content:
        return []
    state = store.get_state()
    out: list[dict] = []
    for f in state.files:
        if f.category != CONVERSATION_CATEGORY or not f.name.endswith(".json"):
            continue
        data = read_file_content(f.id)
        if not data:
            continue
        try:
            out.append(json.loads(data.decode("utf-8")))
        except (ValueError, UnicodeDecodeError):
            continue
    return out


def delete_conversation_log(conv_id: str) -> bool:
    """按 <convId>.json 固定文件名定位并删除单条会话记录。"""
    caps = _storage_capabilities()
    find_config_file = caps.get("find_config_file")
    delete_file = caps.get("delete_file")
    if not find_config_file or not delete_file:
        return False
    filename = f"{conv_id}.json"
    rec = find_config_file(CONVERSATION_CATEGORY, filename)
    if not rec:
        return False
    return delete_file(rec.id)


def save_conversations(items: list[dict]) -> dict:
    """增量 upsert 每个会话日志到「对话记录」分类；仅写入传入的会话，不删除其余。"""
    saved = 0
    for log in items:
        save_conversation_log(log.get("id", ""), log)
        saved += 1
    logger.info("保存会话日志 count=%d", saved)
    return {"saved": saved}


def remove_conversation(conv_id: str) -> dict:
    """删除单条会话记录并扇出级联清理事件（best-effort，不影响主删除）。"""
    ok = delete_conversation_log(conv_id)
    if not ok:
        raise LookupError(f"对话记录不存在：{conv_id}")
    logger.warning("删除会话记录 conv_id=%s", conv_id)
    try:
        emit_entity_deleted(ENTITY_CONVERSATION, conv_id)
    except Exception as exc:  # noqa: BLE001 级联失败仅告警
        logger.warning("级联清理事件扇出失败（已忽略）: %s", exc)
    return {"deleted": True}

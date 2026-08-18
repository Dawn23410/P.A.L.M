"""conversations 砖块：会话聊天记录落盘与恢复。

自身持有「对话记录」功能的业务逻辑（分类名 / 固定文件名 upsert / 遍历读取），
底层落盘委托 storage 砖的存储原语（store_file 含 crypto 加密与 pool.json 索引），
复用 storage 的 PoolStore 单例避免双实例竞争；不跨砖 import storage 内部模块。
"""
from __future__ import annotations

import json
import re

from fastapi import APIRouter, Depends, HTTPException

from palm_sdk.core.logging import get_logger
from palm_sdk.security import require_api_token
from palm_sdk.bricks.base import Brick, BrickManifest, registry
from palm_sdk.bricks.housekeeping import emit_entity_deleted, ENTITY_CONVERSATION
from palm_sdk.permission import PermissionSpec, RiskLevel, require_permission
from palm_sdk.schemas.chat import ConversationLogList

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["conversations"])

CONVERSATION_CATEGORY = "对话记录"

# 孤立代理对（如被截断的 emoji 高位 \ud800-\udfff）是非法 Unicode，
# 直接 json.dumps(ensure_ascii=False) 后 .encode("utf-8") 会抛 UnicodeEncodeError。
# 落盘前递归清除，避免会话记录保存 500。
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
    storage_brick = registry.get("storage")
    if not storage_brick:
        return {}
    return getattr(storage_brick, "capabilities", {}) or {}


def _store():
    # 复用 storage 砖的 PoolStore 单例（避免双实例竞争 pool.json）。
    caps = _storage_capabilities()
    get_store = caps.get("get_store")
    return get_store() if callable(get_store) else None


def save_conversation_log(conv_id: str, payload: dict):
    # 以 <convId>.json 为固定文件名 upsert；委托 storage 的 store_file（含加密 + 索引）。
    caps = _storage_capabilities()
    store_file = caps.get("store_file")
    if not store_file:
        return None
    return store_file(
        CONVERSATION_CATEGORY,
        f"{conv_id}.json",
        json.dumps(_strip_surrogates(payload), ensure_ascii=False).encode("utf-8"),
        dedupe_name=True,
    )


def load_all_conversations() -> list[dict]:
    # 读回「对话记录」分类下全部会话 JSON；损坏文件跳过不阻断其余。
    store = _store()
    if store is None:
        return []
    caps = _storage_capabilities()
    read_file_content = caps.get("read_file_content")
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
    # 按 <convId>.json 固定文件名定位并删除单条会话记录。
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


@router.post("/conversations", dependencies=[Depends(require_api_token)])
def save_conversations(body: ConversationLogList) -> dict:
    # 增量 upsert 每个会话日志到「对话记录」分类；仅写入传入的会话，不删除其余。
    saved = 0
    for log in body.items:
        save_conversation_log(log.id, log.model_dump())
        saved += 1
    logger.info("保存会话日志 count=%d", saved)
    return {"saved": saved}


@router.get("/conversations", dependencies=[Depends(require_api_token)])
def list_conversations() -> list[dict]:
    # 读回全部会话聊天记录（前端用于本地存储清空时的恢复）。
    return load_all_conversations()


@router.delete("/conversations/{conv_id}", dependencies=[Depends(require_api_token), Depends(require_permission("conversations.delete"))])
def remove_conversation(conv_id: str) -> dict:
    ok = delete_conversation_log(conv_id)
    if not ok:
        raise HTTPException(status_code=404, detail="对话记录不存在")
    logger.warning("删除会话记录 conv_id=%s", conv_id)
    # 扇出级联删除事件：清理 agent 记忆/向量等跨砖引用，避免孤儿（best-effort，不影响主删除）。
    try:
        emit_entity_deleted(ENTITY_CONVERSATION, conv_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("级联清理事件扇出失败（已忽略）: %s", exc)
    return {"deleted": True}


brick = Brick(
    manifest=BrickManifest(
        name="conversations",
        title="会话记录",
        description="会话聊天记录落盘与恢复（/api/conversations，固定文件名 upsert 到「对话记录」分类）；底层经 storage 砖存储原语加密落盘。",
        bus_type="sata",
    ),
    router=router,
    permissions=[
        PermissionSpec(key="conversations.delete", title="删除会话记录",
                        description="永久删除某条本地会话聊天记录，不可恢复。",
                        risk=RiskLevel.MEDIUM, brick="conversations"),
    ],
)
registry.register(brick)
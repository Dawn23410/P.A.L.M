"""记忆文件落盘路径：纯计算，agent 与 evolution 都用到，避免重复实现。

按会话+角色持久化记忆文件路径；净化 id 防路径穿越。不同角色使用不同的记忆
文件，实现「人格隔离」——切换角色时不会带入其他角色的记忆上下文。
"""
from __future__ import annotations

import re
from pathlib import Path

from palm_sdk.core.config import settings


def agent_memory_path(conversation_id: str, character_id: str = "") -> Path:
    """返回某会话的记忆文件路径（含角色隔离）。"""
    safe_conv = re.sub(r"[^A-Za-z0-9_\-]", "_", conversation_id or "default")
    if character_id:
        safe_char = re.sub(r"[^A-Za-z0-9_\-]", "_", character_id[:32])
        filename = f"{safe_char}_{safe_conv}.json"
    else:
        filename = f"{safe_conv}.json"
    return Path(settings.STORAGE_POOL_DIR) / "agent_memory" / filename
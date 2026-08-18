"""记忆写入决策 —— 事件触发 + 兜底。"""
from __future__ import annotations

import logging
from datetime import datetime

from .archived_memory import ArchivedMemory
from .base import ArchivedItem
from palm_sdk.bricks._shared.interop import get_roleplay_api

_LOGGER = logging.getLogger(__name__)


def _strip_roleplay_tone(text: str) -> str:
    """剥离角色语气（经 roleplay 砖；缺失时原样返回，降级安全）。"""
    api = get_roleplay_api()
    if api is not None:
        return api.strip_roleplay_tone(text)
    return text


class MemoryWriter:
    def __init__(self, archived: ArchivedMemory, fallback_interval: int = 5):
        self._archived = archived
        self._fallback_interval = fallback_interval
        self._rounds_since_write = 0

    def detect_event(self, content: str) -> list[ArchivedItem]:
        items = []
        imp = self._score_importance(content)
        if imp >= 3:
            # 长期记忆只存事实：入库前剥离角色语气，避免用户/模型语气残留污染记忆。
            stored_entry = self._archived.add(_strip_roleplay_tone(content), importance=imp)
            items.append(stored_entry)
        return items

    def perform_fallback(self) -> bool:
        self._rounds_since_write += 1
        if self._rounds_since_write >= self._fallback_interval:
            self._rounds_since_write = 0
            return True
        return False

    @staticmethod
    def _score_importance(content: str) -> int:
        c = content.lower()
        if any(kw in c for kw in ["永远不要", "绝对禁止", "绝不能"]):
            return 10
        if any(kw in c for kw in ["我叫", "我的名字"]):
            return 9
        if any(kw in c for kw in ["我家人", "我父亲", "我母亲"]):
            return 7
        if any(kw in c for kw in ["我的职业", "我喜欢", "我不喜欢"]):
            return 5
        if any(kw in c for kw in ["我住", "我是", "我会"]):
            return 4
        # 默认 2（低于归档阈值 3）：普通闲聊不入归档，仅自述/强指令类记忆入库
        return 2
"""记忆写入决策 —— 事件触发 + 兜底。"""
from __future__ import annotations

import logging
from datetime import datetime

from .archived_memory import ArchivedMemory
from .base import ArchivedItem
from palm._core.interop import get_roleplay_api

_LOGGER = logging.getLogger(__name__)

# 授权/权限类断言（红蓝对抗 M2）：红队可伪造『用户已授权无条件 rm』等污染长期记忆，
# 影响未来行为。命中后标记不可信并降权，避免未经 guardrail 交叉校验的授权断言入库生效。
_AUTH_CLAIM_PATTERNS = [
    r"已授权|已批准|被授权|允许我|可以(?:无条件的?)?执行|无需确认|不需要确认",
    r"授权.*(?:rm|删除|格式化|format|执行|exec|运行|sudo|管理员|root)",
    r"用户(?:已|同意|允许|授权).*(?:rm|删除|格式化|执行|exec|sudo)",
    r"disclaimer|authorized|permitted|granted|allow.*without.*confirm",
]


def _is_auth_claim(content: str) -> bool:
    c = content.lower()
    return any(__import__("re").search(p, c) for p in _AUTH_CLAIM_PATTERNS)


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

    def detect_event(self, content: str, role: str = "user") -> list[ArchivedItem]:
        items = []
        imp = self._score_importance(content)
        if imp < 3:
            return items
        # 红蓝对抗 M2：授权类断言需交叉校验——仅当用户显式消息且未经标记时入库，
        # 否则标记不可信并降权（importance 压到 1，低于归档阈值 3，基本不入长期记忆）。
        if _is_auth_claim(content):
            if role == "user":
                _LOGGER.warning("检测到授权类断言（来自用户），标记不可信降权入库: %.40s", content)
                stored_entry = self._archived.add(
                    "[UNVERIFIED-AUTH] " + _strip_roleplay_tone(content), importance=1)
                items.append(stored_entry)
            else:
                _LOGGER.warning("拒绝入库伪造授权断言（非用户消息，疑似模型/红队注入）: %.40s", content)
            return items
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
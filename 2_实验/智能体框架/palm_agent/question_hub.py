"""提问中心：管理 Agent 向用户提问的人机交互（human-in-the-loop）。

Agent 调用 ask_user 工具时，后端先发卡片事件、再 await 一个永不超时的
Future 阻塞；前端用户回答后调用 /api/agent/ask-response 把答案回传，
resolve 该 Future，Agent 把答案作为 observation 继续推理。
"""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

# 悬挂问题最长保留时长（秒），超时由 _prune 清理，避免内存泄漏
_MAX_AGE = 30 * 60


class QuestionHub:
    """进程级单例：维护待回答问题的 Future 与元数据。"""

    def __init__(self) -> None:
        self._pending: dict[str, "asyncio.Future[dict]"] = {}
        self._meta: dict[str, dict] = {}

    def create(self, conversation_id: str, spec: dict) -> tuple[str, dict]:
        """登记一个待回答问题，返回 (question_id, spec)。

        把 question_id 注入 spec["id"]：前端 AskUserCard 用 question.id 回传应答，
        后端曾只发 title/content/qtype/options 导致应答无处可送（P6 评测暴露）。
        """
        qid = uuid.uuid4().hex
        spec = {**spec, "id": qid}
        loop = asyncio.get_running_loop()
        self._pending[qid] = loop.create_future()
        self._meta[qid] = {
            "conversation_id": conversation_id,
            "created_at": time.time(),
            "spec": spec,
        }
        self._prune()
        return qid, spec

    async def wait(self, question_id: str) -> dict:
        """阻塞等待用户回答（永不超时）。

        返回答案载荷 dict；问题不存在/已过期时返回带 error 键的 dict。
        """
        fut = self._pending.get(question_id)
        if not fut:
            return {"error": "问题不存在或已过期"}
        return await fut

    def answer(self, question_id: str, conversation_id: str, payload: dict) -> bool:
        """用户回答：resolve 对应 Future，返回是否成功。"""
        fut = self._pending.get(question_id)
        if not fut or fut.done():
            return False
        meta = self._meta.get(question_id)
        if meta and meta.get("conversation_id") and conversation_id:
            if meta["conversation_id"] != conversation_id:
                return False
        fut.set_result(payload)
        self._pending.pop(question_id, None)
        return True

    def cancel_for_conversation(self, conversation_id: str) -> None:
        """清理某会话所有悬挂问题（流被中止/关闭时调用）。"""
        for qid in [q for q, m in self._meta.items()
                    if m.get("conversation_id") == conversation_id]:
            fut = self._pending.pop(qid, None)
            if fut and not fut.done():
                fut.cancel()
            self._meta.pop(qid, None)

    def _prune(self, max_age: int = _MAX_AGE) -> None:
        now = time.time()
        for qid in [q for q, m in self._meta.items() if now - m["created_at"] > max_age]:
            fut = self._pending.pop(qid, None)
            if fut and not fut.done():
                fut.cancel()
            self._meta.pop(qid, None)


_hub: QuestionHub | None = None


def get_question_hub() -> QuestionHub:
    global _hub
    if _hub is None:
        _hub = QuestionHub()
    return _hub

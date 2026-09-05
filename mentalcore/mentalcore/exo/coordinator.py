"""双 Agent 协调器（移植自 palm coordinator.py，适配 Boss=心智魔方）。

Boss 常驻（MentalCore 纯聊天），Worker 按需拉起（WorkCube 外骨骼）。
消息经 IntentRouter 分类路由：
- chat：Boss 直接回复
- task：确认并后台拉起 Worker
- intervention：转发到 Worker 干预队列（cancel/pause/resume/redirect）
- query：Boss 从轨迹摘要检索后回复

与归档差异：Boss 用 MentalCore.send_message（心智魔方保持不动，Worker 全用归档设计）。
"""
from __future__ import annotations

from .intent_router import IntentRouter, I_CHAT, I_TASK, I_INTERVENTION, I_QUERY

_ACTION_NAMES = {"cancel": "取消", "pause": "暂停", "resume": "恢复", "redirect": "重定向"}


class ExoCoordinator:
    """外骨骼协调器：Boss/Worker 生命周期与消息分发。"""

    def __init__(self, boss_core, cube):
        self._boss = boss_core
        self._cube = cube
        self._router = IntentRouter()

    def handle_message(self, message: str) -> dict:
        """处理用户消息：意图路由 → 分发到 Boss / Worker，返回 {"intent","body","fields"}。"""
        intent = self._router.route(message, worker_active=self._cube.worker_active)
        if intent.intent == I_CHAT:
            return self._boss_chat(message)
        if intent.intent == I_TASK:
            return self._boss_ack_task(message, intent.task_goal)
        if intent.intent == I_INTERVENTION:
            return self._handle_intervention(intent)
        if intent.intent == I_QUERY:
            return self._handle_query(message)
        return self._boss_chat(message)

    # ── 路由分支 ──────────────────────────────────────────────
    def _boss_chat(self, message: str) -> dict:
        packet, _manifest, _emotion = self._boss.send_message(message)
        return {"intent": "chat", "body": packet.body, "fields": packet.fields}

    def _boss_ack_task(self, message: str, task_goal: str) -> dict:
        self._cube.submit_async(task_goal, "", self._boss)
        return {"intent": "task",
                "body": f"已启动后台 Worker 执行：{task_goal[:100]}",
                "fields": {}}

    def _handle_intervention(self, intent) -> dict:
        ok = self._cube.forward_intervention(
            intent.intervention_action, intent.redirect_instruction)
        label = _ACTION_NAMES.get(intent.intervention_action, intent.intervention_action)
        body = (f"已向后台 Worker 发送「{label}」指令。" if ok
                else f"发送「{label}」失败，Worker 可能已完成。")
        return {"intent": "intervention", "body": body, "fields": {}}

    def _handle_query(self, message: str) -> dict:
        return {"intent": "query", "body": self._cube.answer_query(message), "fields": {}}

    # ── 状态与外部干预 ──────────────────────────────────────────
    def get_status(self) -> dict:
        return self._cube.get_status()

    def intervene(self, action: str, instruction: str = "") -> bool:
        """外部直接调用：向 Worker 发送干预指令。"""
        return self._cube.forward_intervention(action, instruction)

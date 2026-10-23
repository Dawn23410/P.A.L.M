"""双 Agent 协调器 —— Boss/Worker 生命周期管理与消息路由。

核心流程：
1. 用户消息 → IntentRouter 判定意图（chat/task/intervention/query）
2. chat → Boss 直接回复（可附带 Worker 轨迹摘要）
3. task → Boss 回复确认 → 后台 asyncio.Task 启动 Worker
4. intervention → 转发到 Worker 干预队列（cancel/pause/resume/redirect）
5. query → Boss 从 TraceStore 检索 Worker 进展后回复

Worker 全程在后台执行，事件只写 TraceStore 不直接发前端；
Boss 在每轮对话前从 TraceStore 拉取摘要注入 system prompt，
实现「分片检索」而非一次性灌入全部上下文。
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, AsyncIterator, Callable

from .dual_core import Agent
from .trace_store import TraceStore
from .intent_router import (
    IntentRouter, IntentResult,
    I_CHAT, I_TASK, I_INTERVENTION, I_QUERY,
)
from ..tool_base import ToolRegistry, get_registry
from ..schemas import AgentEvent
from palm._core.interop import get_memory_api
from .professional_memory import (
    get_default_professional_memory,
    schedule_trace_digest,
)

_LOGGER = logging.getLogger(__name__)


def _memory_api():
    api = get_memory_api()
    if api is None:
        raise RuntimeError("记忆砖未注册")
    return api


class DualCoordinator:
    """双 Agent 协调器：管理 Boss/Worker 生命周期与消息分发。

    一个 coordinator 实例服务一个会话（conversation_id）。
    Boss 常驻；Worker 按需创建、完成即回收（TraceStore 保留供检索）。
    """

    def __init__(
        self,
        boss_model: str,
        worker_model: str,
        llm_stream_fn: Callable,
        adjudicator_check_fn: Callable | None = None,
        conversation_id: str = "",
        character_id: str = "",
        persona_text: str = "",
        character_card: Any = None,
        boss_memory: Any = None,
        vector_persist_dir: str = "",
        boss_max_iterations: int = 2,
        worker_max_iterations: int = 15,
        worker_max_plan_steps: int = 8,
    ) -> None:
        self._boss_model = boss_model
        self._worker_model = worker_model
        self._llm_stream_fn = llm_stream_fn
        self._adj = adjudicator_check_fn
        self._conversation_id = conversation_id
        self._character_id = character_id
        self._persona_text = persona_text
        self._character_card = character_card
        self._boss_memory = boss_memory
        self._vector_persist_dir = vector_persist_dir
        self._boss_max_iter = boss_max_iterations
        self._worker_max_iter = worker_max_iterations
        self._worker_max_plan = worker_max_plan_steps

        self._intent_router = IntentRouter()
        self._boss: Agent | None = None
        self._worker: Agent | None = None
        self._worker_task: asyncio.Task | None = None
        self._professional_digest_task: asyncio.Task | None = None
        self._trace_store: TraceStore | None = None
        try:
            self._professional_memory = get_default_professional_memory()
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("专业Agent私有记忆库初始化失败（降级为无私有经验）: %s", exc)
            self._professional_memory = None

        self._init_boss()

    # ── Boss 管理 ──────────────────────────────────────────────

    def _init_boss(self) -> None:
        """创建 Boss Agent（常驻，复用会话记忆与角色设定）。

        Boss 是 Reflex 层——纯对话，不执行工具。
        空工具注册表确保 Boss 只产出文本回复，任务执行全部交给 Worker。
        """
        boss_tools = ToolRegistry()  # 空：Boss 不调用工具
        self._boss = Agent(
            model=self._boss_model,
            memory=self._boss_memory,
            tools=boss_tools,
            max_iterations=self._boss_max_iter,
            auto_filter_tools=False,  # 无工具，跳过语义匹配
            conversation_id=self._conversation_id,
            character_id=self._character_id,
            persona_text=self._persona_text,
            character_card=self._character_card,
            agent_role="boss",
        )

    # ── Worker 管理 ─────────────────────────────────────────────

    def _create_worker(self, task_goal: str) -> Agent:
        """创建 Worker Agent（每个任务一个新实例，独立记忆与工具）。"""
        # 独立 ToolRegistry：排除 ask_user（后台无前端连接，wait 会死锁）
        worker_tools = ToolRegistry()
        for tool in get_registry().list_tools():
            if tool.spec.name != "ask_user":
                worker_tools.register(tool)

        # 独立 buffer memory：隔离角色扮演上下文
        worker_memory = _memory_api().create_memory("buffer", model_window=128000)

        # 轨迹存储
        self._trace_store = TraceStore(
            task_id=f"{self._conversation_id}_{int(time.time())}",
            task_goal=task_goal,
            vector_persist_dir=self._vector_persist_dir or None,
        )

        worker = Agent(
            model=self._worker_model,
            memory=worker_memory,
            tools=worker_tools,
            max_iterations=self._worker_max_iter,
            max_plan_steps=self._worker_max_plan,
            conversation_id=self._conversation_id,
            character_id="",       # Worker 不绑定角色
            persona_text="",       # Worker 不做角色扮演
            agent_role="worker",
            trace_store=self._trace_store,
        )
        if self._professional_memory is not None:
            try:
                worker._professional_memory_context = (
                    self._professional_memory.build_injection_context(task_goal)
                )
            except Exception as exc:  # noqa: BLE001
                _LOGGER.warning("专业Agent私有经验注入失败（跳过）: %s", exc)
                worker._professional_memory_context = ""
        return worker

    @property
    def worker_active(self) -> bool:
        """Worker 是否正在执行（任务未完成）。"""
        return (
            self._worker is not None
            and self._worker_task is not None
            and not self._worker_task.done()
        )

    @property
    def worker_finished(self) -> bool:
        """Worker 是否已完成（任务结束但 TraceStore 仍可检索）。"""
        if self._trace_store is not None and self._trace_store.is_finished:
            return True
        return (
            self._worker_task is not None
            and self._worker_task.done()
            and self._trace_store is not None
        )

    def _start_worker(self, task_goal: str) -> None:
        """后台启动 Worker 执行任务。"""
        # 已有活跃 Worker：取消旧的（旧任务在下次 await 时收到 CancelledError）
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()

        self._worker = self._create_worker(task_goal)
        worker = self._worker
        trace = self._trace_store

        async def _run_worker() -> None:
            """Worker 后台执行体：事件只写 TraceStore，不直接发前端。"""
            try:
                async for _event in worker.run(
                    task_goal,
                    self._llm_stream_fn,
                    self._adj,
                    use_planning=True,
                ):
                    # 事件已被 run_native / dual_plan 记录到 trace_store
                    # 此处无需额外处理，消费即丢弃
                    pass
            except asyncio.CancelledError:
                if trace:
                    trace.add("error", "Worker 任务被取消")
                raise
            except Exception as exc:  # noqa: BLE001
                if trace:
                    trace.add("error", f"Worker 异常: {str(exc)[:200]}")
                _LOGGER.exception("Worker 执行异常")
            finally:
                if trace:
                    trace.mark_finished()
                    self._schedule_professional_digest(trace)

        self._worker_task = asyncio.create_task(_run_worker())
        _LOGGER.info("Worker 已启动: %s", task_goal[:100])

    def _schedule_professional_digest(self, trace: TraceStore) -> None:
        """任务完成后异步整理专业Agent私有工作笔记。"""
        if self._professional_memory is None:
            return
        task = schedule_trace_digest(
            self._professional_memory,
            trace,
            self._llm_stream_fn,
            self._worker_model,
        )
        if task is not None:
            self._professional_digest_task = task

    def cleanup_worker(self) -> None:
        """回收已完成的 Worker 实例（TraceStore 保留供后续检索）。"""
        if self._worker_task and self._worker_task.done():
            self._worker = None
            self._worker_task = None

    # ── 消息路由 ──────────────────────────────────────────────

    async def handle_message(
        self, message: str,
    ) -> AsyncIterator[AgentEvent]:
        """处理用户消息：意图路由 → 分发到 Boss/Worker。"""
        # 回收已完成的 Worker
        self.cleanup_worker()

        intent = self._intent_router.route(
            message, worker_active=self.worker_active,
        )

        if intent.intent == I_CHAT:
            async for ev in self._boss_chat(message):
                yield ev

        elif intent.intent == I_TASK:
            async for ev in self._boss_ack_task(message, intent.task_goal):
                yield ev
            self._start_worker(intent.task_goal)

        elif intent.intent == I_INTERVENTION:
            async for ev in self._handle_intervention(intent):
                yield ev

        elif intent.intent == I_QUERY:
            async for ev in self._handle_query(message):
                yield ev

        else:
            async for ev in self._boss_chat(message):
                yield ev

    async def _boss_chat(self, message: str) -> AsyncIterator[AgentEvent]:
        """Boss 直接对话：每轮注入 Worker 轨迹摘要。"""
        self._boss._worker_trace_summary = self._get_worker_summary()
        async for event in self._boss.run(
            message, self._llm_stream_fn, self._adj,
        ):
            yield event

    async def _boss_ack_task(
        self, message: str, task_goal: str,
    ) -> AsyncIterator[AgentEvent]:
        """Boss 确认任务并告知用户已启动后台 Worker。

        在用户消息后追加系统提示，让 Boss 自然地告知用户任务已交接。
        """
        ack_hint = (
            f"\n\n[系统提示] 用户的消息包含复杂任务「{task_goal[:100]}」，"
            "系统已启动后台 Worker 执行。请用自然的方式告知用户任务正在后台进行，"
            "你可以继续和我对话讨论这个任务，我会实时关注 Worker 进展。"
            "\n\n⚠️ 严格禁止调用任何工具——任务已交由后台 Worker 处理，"
            "你只需用文字回复确认即可，不要尝试搜索、读取文件或执行任何操作。"
        )
        self._boss._worker_trace_summary = ""
        async for event in self._boss.run(
            message + ack_hint, self._llm_stream_fn, self._adj,
        ):
            yield event

    async def _handle_intervention(
        self, intent: IntentResult,
    ) -> AsyncIterator[AgentEvent]:
        """处理干预指令：转发到 Worker + Boss 简要回应。"""
        if not self._worker:
            yield AgentEvent(
                type="delta",
                content="当前没有正在执行的后台任务。",
            )
            yield AgentEvent(type="done")
            return

        ok = self._worker.send_intervention(
            intent.intervention_action,
            intent.redirect_instruction,
        )

        action_names = {
            "cancel": "取消",
            "pause": "暂停",
            "resume": "恢复",
            "redirect": "重定向",
        }
        action_label = action_names.get(intent.intervention_action, intent.intervention_action)

        if ok:
            yield AgentEvent(
                type="delta",
                content=f"已向后台 Worker 发送「{action_label}」指令。",
            )
        else:
            yield AgentEvent(
                type="delta",
                content=f"发送「{action_label}」指令失败，Worker 可能已完成。",
            )
        yield AgentEvent(type="done")

    async def _handle_query(self, message: str) -> AsyncIterator[AgentEvent]:
        """处理查询指令：Boss 从 TraceStore 检索后回复。"""
        summary = self._get_worker_summary()
        self._boss._worker_trace_summary = summary
        # 在消息后追加系统提示，让 Boss 基于 Worker 进展回答
        query_hint = (
            f"\n\n[系统提示] 用户在询问后台任务进展。"
            f"以下是 Worker 当前进度：\n{summary}"
        )
        async for event in self._boss.run(
            message + query_hint, self._llm_stream_fn, self._adj,
        ):
            yield event

    # ── 轨迹检索 ──────────────────────────────────────────────

    def _get_worker_summary(self) -> str:
        """获取 Worker 轨迹摘要（供 Boss 上下文注入）。"""
        if self._trace_store and self._trace_store.entry_count > 0:
            return self._trace_store.get_summary()
        return ""

    def get_trace_store(self) -> TraceStore | None:
        """获取当前 TraceStore 引用（供外部检索）。"""
        return self._trace_store

    async def query_trace(self, keyword: str, top_k: int = 5) -> list[dict]:
        """语义检索 Worker 轨迹。"""
        if self._trace_store:
            return [e.to_dict() for e in self._trace_store.query(keyword, top_k)]
        return []

    # ── 外部干预接口 ────────────────────────────────────────────

    def intervene(self, action: str, instruction: str = "") -> bool:
        """外部直接调用：向 Worker 发送干预指令。"""
        if self._worker:
            return self._worker.send_intervention(action, instruction)
        return False

    # ── 状态查询 ──────────────────────────────────────────────

    def get_status(self) -> dict:
        """返回当前协调器状态（供前端展示）。"""
        trace = self._trace_store
        has_trace = trace is not None
        return {
            "worker_active": self.worker_active,
            "worker_finished": self.worker_finished,
            "task_started": has_trace,
            "trace_entries": trace.entry_count if has_trace else 0,
            "task_goal": trace.task_goal if has_trace else "",
            "last_trace_type": trace.last_entry_type if has_trace else "",
        }
"""Agent 核心编排：把提示构建 / 执行 / ReAct 循环三个 Mixin 组装为 Agent 类。

全部推理细节已下沉到对应 Mixin（见 agent_prompt_mixin / agent_execution_mixin /
agent_react_mixin），本文件只负责实例装配与顶层 run 分发，保持单一职责。
支持核心组件依赖注入，与主Agent内核保持接口一致。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator, Optional

from ..schemas import AgentEvent
from ..tool_base import (
    ToolRegistry, get_registry,
    agent_conversation_id, agent_model, agent_is_wakeup, agent_character_id,
)
from ..tool_matcher import get_matcher
from palm.adapters.model.model_router import select_model
from ..completion_gate import get_default_gate
from ..persona import create_persona_provider
from .dual_runner import run_native as _run_native_impl
from palm_sdk.bricks._shared.interop import get_memory_api

from ..protocols import (
    MemoryProtocol,
    ToolRegistryProtocol,
    ToolMatcherProtocol,
    CompletionGateProtocol,
    PersonaProviderProtocol,
    TokenBudgetProtocol,
    PlannerProtocol,
)


def _memory_api():
    # 记忆砖门面：Memory / create_memory / TokenBudgetAllocator 等经 capability 取用。
    api = get_memory_api()
    if api is None:
        raise RuntimeError("记忆砖未注册")
    return api
from ..react_parser import parse_react_output
from .dual_prompt import PromptMixin
from ..agent_execution_mixin import ExecutionMixin
from ..agent_react_mixin import ReactMixin

_LOGGER = logging.getLogger(__name__)

# 对外兼容：早期调用方可能从 .core 直接取解析函数
__all__ = ["Agent", "parse_react_output"]


class Agent(PromptMixin, ExecutionMixin, ReactMixin):
    """双模认知引擎 Agent 实例。

    agent_role 区分两种角色：
    - "boss"：主 Agent（Reflex），快速对话 + 意图路由 + 监控 Worker 轨迹
    - "worker"：专业 Agent（Cortex），后台深度执行 + 全量轨迹记录
    - None：兼容模式，行为与原始单 Agent 一致
    """

    def __init__(
        self,
        model: str,
        memory: Any | None = None,
        tools: ToolRegistry | None = None,
        max_iterations: int = 10,
        deep_think: bool = False,
        model_window: int = 128000,
        user_message: str = "",
        max_plan_steps: int = 8,
        persona_text: str = "",
        character_card: Any = None,
        conversation_id: str = "",
        character_id: str = "",
        tool_mode: str = "native",
        auto_filter_tools: bool = True,
        agent_role: str | None = None,
        trace_store: Any | None = None,
        # ── 新增：可注入核心组件（保持与主Agent接口一致） ──────────────────
        matcher: Optional[ToolMatcherProtocol] = None,
        completion_gate: Optional[CompletionGateProtocol] = None,
        persona_provider: Optional[PersonaProviderProtocol] = None,
        token_budget: Optional[TokenBudgetProtocol] = None,
    ):
        self._agent_role = agent_role
        self._trace_store = trace_store
        self._model = model
        self._memory = memory or _memory_api().create_memory("buffer", model_window=model_window)
        self._tools = tools or get_registry()
        # 工具调用架构：native=原生结构化(function calling)，react=文本式 ReAct 兜底。
        self._tool_mode = tool_mode
        self._auto_filter_tools = auto_filter_tools
        self._max_iterations = max_iterations
        self._deep_think = deep_think
        self._max_plan_steps = max_plan_steps
        # 注入核心组件（默认实现保持原有行为）
        self._budget = token_budget or _memory_api().TokenBudgetAllocator(model_window)
        self._matcher = matcher or get_matcher()
        self._completion_gate = completion_gate or get_default_gate()
        self.persona_provider = persona_provider or create_persona_provider(
            persona_text=persona_text,
            character_card=character_card,
        )
        self._conversation_count = 0
        self._user_message = user_message
        self._persona_text = persona_text
        self._character_card = character_card
        self._character_id = character_id or ""
        self._conversation_id = conversation_id
        self._preloaded_observations: list[str] = []
        self._emotion_hint: str = ""
        self._last_full_output: str | None = None
        self._emitted_reasoning = ""
        # 干预队列：Boss 通过此队列向 Worker 发送 redirect/pause/cancel 指令
        self._intervention_queue: asyncio.Queue | None = None
        if agent_role == "worker":
            self._intervention_queue = asyncio.Queue()
            import os
            os.environ.setdefault("PALM_AUTOCONFIRM_RUN_CODE", "1")
        # 初始化语义匹配索引
        all_tools = self._tools.list_tools()
        if not self._matcher._index:
            self._matcher.build_index(all_tools)

    def register_tool(self, tool) -> None:
        self._tools.register(tool)

    # ── 干预机制（Boss → Worker） ──────────────────────────────

    async def check_intervention(self) -> str | None:
        """Worker 在每步执行前调用：检查是否有来自 Boss 的干预指令。

        返回值：
        - None：无干预，继续执行
        - "redirect"：重定向，Worker 应读取 _redirect_instruction 获取新指令
        - "pause"：暂停，Worker 等待恢复信号
        - "cancel"：取消，Worker 应立即终止
        - "resume"：恢复（从 pause 状态继续）
        """
        if self._intervention_queue is None or self._intervention_queue.empty():
            return None
        try:
            cmd = self._intervention_queue.get_nowait()
            action = cmd.get("action", "")
            if action == "redirect":
                self._redirect_instruction = cmd.get("instruction", "")
                if self._trace_store:
                    self._trace_store.add(
                        "intervention",
                        f"重定向指令: {self._redirect_instruction[:200]}",
                    )
            elif action == "cancel" and self._trace_store:
                self._trace_store.add("intervention", "任务被 Boss 取消")
            elif action == "pause" and self._trace_store:
                self._trace_store.add("intervention", "任务被 Boss 暂停")
            return action
        except asyncio.QueueEmpty:
            return None

    def send_intervention(self, action: str, instruction: str = "") -> bool:
        """Boss 调用：向 Worker 发送干预指令。

        action: "redirect" | "pause" | "cancel" | "resume"
        instruction: redirect 时的新的任务指令
        返回 True 表示发送成功，False 表示 Worker 不存在或队列不可用。
        """
        if self._intervention_queue is None:
            return False
        try:
            self._intervention_queue.put_nowait({
                "action": action,
                "instruction": instruction,
            })
            return True
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("发送干预指令失败: %s", exc)
            return False

    async def _wait_for_resume(self) -> None:
        """Worker 暂停后等待恢复信号（阻塞直到收到 resume 或 cancel）。"""
        if self._intervention_queue is None:
            return
        while True:
            cmd = await self._intervention_queue.get()
            action = cmd.get("action", "")
            if action in ("resume", "cancel"):
                return

    def _prepare_run(self, message: str) -> list[tuple[str, str]]:
        """写入用户消息、触发记忆归档、监控 Token 预算。"""
        self._memory.add("user", message)
        self._conversation_count += 1
        # 记忆写入决策（事件触发+归档）
        self._memory.writer.detect_event(message)
        if self._conversation_count % 5 == 0:
            self._memory.writer.perform_fallback()
        # Token 预算监控
        budget_action = self._budget.monitor(len(message))
        if budget_action == "compress":
            _LOGGER.info("Token预算触发压缩")
        # 语义上下文预加载：200ms 内异步执行轻量工具，注入 Observation
        self._preload_context(message)
        # 情绪正则检测：基于用户原始消息检测一次，结果供 prompt 注入复用。
        # 仅用户原始情绪有意义——规划模式下 _user_message 会被子目标覆盖，但情绪信号不随之变。
        try:
            from palm_sdk.bricks._shared.emotion import detect, build_emotion_hint
            self._emotion_hint = build_emotion_hint(detect(message))
            # 同步到persona_provider
            if hasattr(self.persona_provider, "emotion_hint"):
                self.persona_provider.emotion_hint = self._emotion_hint
        except Exception:  # noqa: BLE001  检测失败静默降级为不注入
            self._emotion_hint = ""
            if hasattr(self.persona_provider, "emotion_hint"):
                self.persona_provider.emotion_hint = ""
        return []  # tool_call_history 初始值

    async def run(
        self,
        message: str,
        llm_stream_fn: callable,
        adjudicator_check_fn: callable | None = None,
        use_planning: bool = False,
        structured_output: dict | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """运行 Agent，产出一个 SSE 事件流。

        开启 use_planning 时先制定计划、再分步执行并在失败时重规划；
        关闭时退化为普通 ReAct 循环。
        """
        # 即时事件队列：ask_user 弹窗等「需等待人工介入」的事件必须在 wait 前推送，
        # 否则消费方（SSE/前端）收不到事件就无法应答、wait 永不返回（真实死锁）。
        # SSE 层（brick._stream_agent_sse）会在 run 前预挂队列，这里仅兜底补建。
        if getattr(self, "_ask_events", None) is None:
            self._ask_events = asyncio.Queue()
        # P5 结构化输出：把可选的 JSON Schema 挂到实例，供 native/react 收尾抽取
        self._structured_schema = structured_output or None
        # 写入运行上下文，供工具（如后台任务登记）读取会话信息
        agent_conversation_id.set(self._conversation_id)
        agent_model.set(self._model)
        agent_character_id.set(self._character_id)
        tool_call_history = self._prepare_run(message)
        # P4 上下文真压缩：拼 prompt 前把超预算的旧轮次摘要化（native/react/规划 共用）。
        # 压缩仅在历史超 Token 预算时触发，小对话零额外开销；异常不阻塞主流程。
        try:
            # 杂活外包：记忆压缩走 flash 小模型（未配 flash 则回退主力，零风险）
            await self._memory.compress_old_turns(llm_stream_fn, select_model("trivial", self._model))
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("上下文压缩异常（跳过）: %s", exc)
        # P5 追踪：包裹事件流记录轨迹，任何异常都不影响主流程
        from ..trace import RunTracer, persist_trace
        tracer = RunTracer()
        tracer.start(self._conversation_id, self._model, self._tool_mode)

        async def _traced(agen):
            async for event in agen:
                tracer.record(event)
                yield event

        try:
            # 规划优先：开启 use_planning 时统一走 PlanEngine，由其内部按 tool_mode 选单步执行器
            # （native=原生 FC 循环 / 其他=ReAct），复用同一套「分解→执行→失败重规划」编排。
            if use_planning:
                from .dual_plan import PlanEngine
                engine = PlanEngine(
                    self, llm_stream_fn, adjudicator_check_fn,
                    max_steps=self._max_plan_steps,
                    step_max_iter=min(self._max_iterations, 6),
                    step_timeout=180,
                )
                async for event in _traced(engine.run(message)):
                    yield event
                return
            # native 模式：原生结构化工具调用（function calling）循环。
            if self._tool_mode == "native":
                outcome: dict = {}
                async for event in _traced(self._run_native(
                    message, llm_stream_fn, adjudicator_check_fn, outcome,
                )):
                    yield event
                return
            outcome: dict = {}
            async for event in _traced(self.run_react(
                message, llm_stream_fn, adjudicator_check_fn, tool_call_history, outcome,
            )):
                yield event
        finally:
            trace_dict = tracer.to_dict()
            self._last_trace = trace_dict
            persist_trace(trace_dict)
            # Worker 模式：标记轨迹存储完成
            if self._agent_role == "worker" and self._trace_store:
                self._trace_store.mark_finished()

    async def _run_native(
        self, message: str, llm_stream_fn: callable,
        adjudicator_check_fn: callable | None, outcome: dict, emit_done: bool = True,
    ) -> AsyncIterator[AgentEvent]:
        """原生结构化工具调用主循环（function calling）的薄转发。"""
        async for event in _run_native_impl(
            self, message, llm_stream_fn, adjudicator_check_fn, outcome, emit_done,
        ):
            yield event
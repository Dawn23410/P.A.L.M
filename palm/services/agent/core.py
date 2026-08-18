"""Agent 核心编排：把提示构建 / 执行 / ReAct 循环三个 Mixin 组装为 Agent 类。

重构后支持核心组件依赖注入：
- 所有核心组件（记忆、工具、匹配器、完成门、角色提供者）均可通过构造函数注入自定义实现
- 不传参数时使用默认实现，完全保持原有行为
- Mixin 通过 self 的属性访问依赖，无需关心底层是默认实现还是自定义实现
- 真正实现"即插即用"：实现对应 Protocol 即可替换任意一层，无需修改内核代码
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator, Optional

from .schemas import AgentEvent
from .tool_base import (
    ToolRegistry, get_registry,
    agent_conversation_id, agent_model, agent_is_wakeup, agent_character_id,
)
from .tool_matcher import get_matcher
from .model_router import select_model
from .native_runner import run_native as _run_native_impl
from .completion_gate import get_default_gate
from .persona import create_persona_provider
from palm._core.interop import get_memory_api

from .protocols import (
    MemoryProtocol,
    ToolRegistryProtocol,
    ToolMatcherProtocol,
    CompletionGateProtocol,
    PersonaProviderProtocol,
    TokenBudgetProtocol,
    PlannerProtocol,
)


def _memory_api():
    """记忆砖门面：Memory / create_memory / TokenBudgetAllocator 等经 capability 取用。"""
    api = get_memory_api()
    if api is None:
        raise RuntimeError("记忆砖未注册")
    return api
from .react_parser import parse_react_output
from .agent_prompt_mixin import PromptMixin
from .agent_execution_mixin import ExecutionMixin
from .agent_react_mixin import ReactMixin

_LOGGER = logging.getLogger(__name__)

# 对外兼容：早期调用方可能从 .core 直接取解析函数
__all__ = ["Agent", "parse_react_output"]


class Agent(PromptMixin, ExecutionMixin, ReactMixin):
    """单个 Agent 实例（支持所有核心组件依赖注入，各层可独立替换）。"""

    def __init__(
        self,
        model: str,
        memory: Optional[MemoryProtocol] = None,
        tools: Optional[ToolRegistryProtocol] = None,
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
        allowed_tools: Optional[list[str]] = None,
        # ── 新增：可注入核心组件（不传则使用默认实现） ──────────────────
        matcher: Optional[ToolMatcherProtocol] = None,
        completion_gate: Optional[CompletionGateProtocol] = None,
        persona_provider: Optional[PersonaProviderProtocol] = None,
        token_budget: Optional[TokenBudgetProtocol] = None,
    ):
        # ── 基础配置（保持原有属性名完全不变） ──────────────────────
        self._model = model
        self._memory = memory or _memory_api().create_memory("buffer", model_window=model_window)
        self._tools = tools or get_registry()
        self._tool_mode = tool_mode
        self._auto_filter_tools = auto_filter_tools
        self._allowed_tool_names = set(allowed_tools or []) or None
        self._max_iterations = max_iterations
        self._deep_think = deep_think
        self._max_plan_steps = max_plan_steps
        self._conversation_count = 0
        self._user_message = user_message
        self._persona_text = persona_text
        self._character_card = character_card
        self._character_id = character_id or ""
        self._conversation_id = conversation_id
        self._preloaded_observations: list[str] = []
        self._last_full_output: str | None = None
        self._emitted_reasoning = ""
        self._emotion_hint: str = ""

        # ── 注入核心组件（默认实现保持原有行为） ────────────────────
        # Token 预算管理器
        self._budget = token_budget or _memory_api().TokenBudgetAllocator(model_window)
        # 工具语义匹配器
        self._matcher = matcher or get_matcher()
        # 完成判定门
        self._completion_gate = completion_gate or get_default_gate()
        # 角色设定提供者
        self.persona_provider = persona_provider or create_persona_provider(
            persona_text=persona_text,
            character_card=character_card,
        )
        # 同步角色状态到provider（保证provider和原有属性一致）
        if hasattr(self.persona_provider, "emotion_hint"):
            self.persona_provider.emotion_hint = self._emotion_hint

        # ── 初始化语义匹配索引 ────────────────────────────────────
        all_tools = self._tools.list_tools()
        if not self._matcher._index:
            self._matcher.build_index(all_tools)

    def register_tool(self, tool) -> None:
        self._tools.register(tool)
        # 注册新工具后重建匹配索引
        try:
            self._matcher.build_index(self._tools.list_tools())
        except Exception:
            pass

    def _list_available_tools(self):
        tools = self._tools.list_tools()
        if not self._allowed_tool_names:
            return tools
        return [tool for tool in tools if tool.spec.name in self._allowed_tool_names]

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
        try:
            from palm._core.emotion import detect, build_emotion_hint
            self._emotion_hint = build_emotion_hint(detect(message))
            # 同步到persona_provider
            if hasattr(self.persona_provider, "emotion_hint"):
                self.persona_provider.emotion_hint = self._emotion_hint
        except Exception:
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
        planner: Optional[PlannerProtocol] = None,
    ) -> AsyncIterator[AgentEvent]:
        """运行 Agent，产出一个 SSE 事件流。

        支持传入自定义 planner 实现替换默认规划器；不传则使用默认 Planner。
        """
        # 即时事件队列：ask_user 弹窗等「需等待人工介入」的事件必须在 wait 前推送
        if getattr(self, "_ask_events", None) is None:
            self._ask_events = asyncio.Queue()
        # P5 结构化输出
        self._structured_schema = structured_output or None
        # 写入运行上下文
        agent_conversation_id.set(self._conversation_id)
        agent_model.set(self._model)
        agent_character_id.set(self._character_id)
        tool_call_history = self._prepare_run(message)
        # P4 上下文真压缩
        try:
            await self._memory.compress_old_turns(llm_stream_fn, select_model("trivial", self._model))
        except Exception as exc:
            _LOGGER.warning("上下文压缩异常（跳过）: %s", exc)
        # P5 追踪
        from .trace import RunTracer, persist_trace
        tracer = RunTracer()
        tracer.start(self._conversation_id, self._model, self._tool_mode)

        async def _traced(agen):
            async for event in agen:
                tracer.record(event)
                yield event

        try:
            if use_planning:
                from .plan_engine import PlanEngine
                engine = PlanEngine(
                    self, llm_stream_fn, adjudicator_check_fn,
                    planner=planner,
                    max_steps=self._max_plan_steps,
                    step_max_iter=min(self._max_iterations, 6),
                    step_timeout=180,
                )
                async for event in _traced(engine.run(message)):
                    yield event
                return
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

    async def _run_native(
        self, message: str, llm_stream_fn: callable,
        adjudicator_check_fn: callable | None, outcome: dict, emit_done: bool = True,
    ) -> AsyncIterator[AgentEvent]:
        """原生结构化工具调用主循环（function calling）的薄转发。"""
        async for event in _run_native_impl(
            self, message, llm_stream_fn, adjudicator_check_fn, outcome, emit_done,
        ):
            yield event
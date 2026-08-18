"""Agent 内核核心 Protocol 接口定义。

本文件定义 Agent 各层之间的显式契约，所有 Mixin 和执行引擎通过接口访问依赖，
不再直接访问 self 的私有属性。实现任何接口即可即插即用，无需修改内核代码。

设计原则：
1. 接口最小化：每个 Protocol 只定义该层真正需要的方法
2. 可选方法用 default 实现或 None 判定，不强制实现不需要的功能
3. 完全向后兼容：现有实现无需修改即可满足接口
4. 所有接口均为 typing.Protocol，运行时零开销，仅用于类型检查和契约文档化
"""
from __future__ import annotations

from typing import Any, AsyncIterator, Callable, Optional, Protocol, runtime_checkable


# ============================================================
# L1 数据契约层（已在 schemas.py 定义，此处不重复）
# ============================================================


# ============================================================
# L2 工具层接口
# ============================================================

@runtime_checkable
class ToolProtocol(Protocol):
    """单个工具的最小接口契约。任何实现 spec + execute 的对象都是工具。"""

    @property
    def spec(self) -> Any:
        """工具规格（ToolSpec 或兼容对象），包含 name/description/parameters 等元信息。"""
        ...

    async def execute(self, **kwargs) -> str:
        """执行工具逻辑，返回文本结果。"""
        ...


@runtime_checkable
class ToolRegistryProtocol(Protocol):
    """工具注册表接口。管理工具的注册、查询、枚举。"""

    def register(self, tool: ToolProtocol) -> None:
        """注册一个工具。重名时覆盖。"""
        ...

    def get(self, name: str) -> Optional[ToolProtocol]:
        """按名称获取工具，不存在返回 None。"""
        ...

    def unregister(self, name: str) -> None:
        """移除已注册的工具。"""
        ...

    def list_tools(self) -> list[ToolProtocol]:
        """列出所有已注册工具。"""
        ...

    def to_react_prompt(self) -> str:
        """生成 ReAct 格式的工具列表提示文本。"""
        ...


# ============================================================
# L3 记忆层接口
# ============================================================

class MemoryWriterProtocol(Protocol):
    """记忆写入器接口：负责事件触发式归档和降级摘要。"""

    def detect_event(self, message: str) -> None:
        """检测用户消息中的事件，触发对应记忆写入策略。"""
        ...

    def perform_fallback(self) -> None:
        """执行兜底摘要，将短期记忆压缩为长期记忆。"""
        ...


class MemoryCoreProtocol(Protocol):
    """核心记忆接口：人设、用户画像、安全底线、动态情境。"""

    def build_stance_injection(self, character_card: Any) -> str:
        """构建当前状态注入文本（好感度、关系阶段等）。"""
        ...

    def build_dynamic_overlay(self, user_msg: str, stage_name: str) -> str:
        """构建动态情境叠加层（仅当前轮次生效，不回写角色卡）。"""
        ...


@runtime_checkable
class MemoryProtocol(Protocol):
    """完整记忆层接口。Agent 通过此接口与记忆系统交互，不关心底层实现。"""

    writer: MemoryWriterProtocol
    core: MemoryCoreProtocol

    def add(self, role: str, content: str, images: list[dict] | None = None) -> None:
        """写入一条对话记忆。"""
        ...

    def get_context(self) -> list[dict]:
        """获取对话上下文（最近 N 轮消息）。"""
        ...

    def inject_system_context(self) -> str:
        """注入长期记忆、程序性记忆等到 system prompt。"""
        ...

    async def compress_old_turns(self, llm_stream_fn: Callable, model: str | None) -> None:
        """压缩超预算的旧轮次，在 Token 超限前触发。"""
        ...

    def record_failure(self, goal: str, step: str, error: str) -> None:
        """记录一次失败经验，供后续规划避开相同路径。"""
        ...


# ============================================================
# L4 Token 预算层接口
# ============================================================

@runtime_checkable
class TokenBudgetProtocol(Protocol):
    """Token 预算管理器接口：监控上下文长度，决策压缩时机。"""

    def monitor(self, new_tokens: int) -> str:
        """监控新增 Token 长度，返回动作：'noop' | 'compress'。"""
        ...


# ============================================================
# L5 工具匹配层接口
# ============================================================

@runtime_checkable
class ToolMatcherProtocol(Protocol):
    """语义工具匹配器接口：根据用户查询相关性排序工具。"""

    def build_index(self, tools: list[ToolProtocol]) -> None:
        """从工具列表构建检索索引。"""
        ...

    def rank(self, query: str, top_k: int = 20) -> list[tuple[str, float, str]]:
        """对查询评分，返回 (工具名, 评分, 描述) 列表。"""
        ...

    def search(self, query: str) -> list[tuple[str, str]]:
        """搜索工具，返回 (工具名, 描述) 列表。"""
        ...


# ============================================================
# L6 规划器接口
# ============================================================

@runtime_checkable
class PlannerProtocol(Protocol):
    """规划器接口：负责生成初始计划、失败时重规划。可替换实现。"""

    async def plan(
        self,
        goal: str,
        tools_summary: str,
        memory_context: str,
        llm_stream_fn: Callable,
        trivial_model: str | None,
        total_tools: int,
        known_tools: set[str],
        research_findings: str = "",
    ) -> Any:
        """制定初始计划，返回 Plan 对象。"""
        ...

    async def replan(
        self,
        goal: str,
        current_plan: Any,
        failed_step: Any,
        failure_reason: str,
        llm_stream_fn: Callable,
        trivial_model: str | None,
        known_tools: set[str],
    ) -> Any:
        """失败后重规划剩余步骤，返回新的 Plan 对象。"""
        ...


# ============================================================
# L7 角色设定提供者接口（可选，不使用角色扮演时传 None）
# ============================================================

class PersonaProviderProtocol(Protocol):
    """角色设定提供者接口。封装所有角色扮演相关逻辑，非陪伴场景可替换为 Noop 实现。"""

    persona_text: str
    character_card: Any
    emotion_hint: str

    def collect_known_character_names(self) -> list[str]:
        """收集所有已知角色名，用于清洗非角色对话中的残留语气。"""
        ...

    def strip_roleplay_tone(self, text: str, known_names: list[str]) -> str:
        """清洗文本中的角色化表达残留。"""
        ...

    def compile_roleplay_section(self, memory: MemoryProtocol | None, user_message: str) -> str:
        """构建完整的角色设定段落（静态人设 + 当前状态 + 动态叠加层）。"""
        ...

    def get_no_roleplay_constraint(self) -> str:
        """获取无角色时的强约束提示（禁止角色化表达）。"""
        ...

    def should_filter_tools(self) -> bool:
        """角色扮演模式下是否需要限制工具（如人格对话时不暴露全部工具）。"""
        ...

    def clean_assistant_text(self, text: str, has_persona: bool) -> str:
        """清洗助手输出文本，非角色模式下去除角色化残留。"""
        ...


# ============================================================
# L8 完成判定门接口
# ============================================================

CompletionRuleFn = Callable[[str, str, str], Optional[str]]
"""完成判定规则函数签名：(request, tool_name, tool_output) -> 最终回答 | None。
返回 None 表示不匹配该规则，继续判定；返回字符串表示直接以此为最终回答。"""


@runtime_checkable
class CompletionGateProtocol(Protocol):
    """完成判定门接口：识别确定性工具结果，避免已满足目标后继续空转。"""

    def register_rule(self, rule: CompletionRuleFn) -> None:
        """注册一个完成判定规则。"""
        ...

    def try_complete(self, request: str, tool_name: str, tool_output: str) -> Optional[str]:
        """尝试从工具结果直接生成最终回答。返回 None 表示需要继续推理。"""
        ...


# ============================================================
# L9 LLM 桥接接口（已通过注入 llm_stream_fn 实现，此处仅作类型定义）
# ============================================================

LLMStreamFn = Callable[[list[dict], str], AsyncIterator[Any]]
"""LLM 流式调用函数签名：(messages, model) -> 异步迭代器产出 chunk。
chunk 可以是 dict（含 content/reasoning 字段）、str 或具有 content/delta/reasoning 属性的对象。"""


# ============================================================
# L10 运行时上下文接口（Agent 运行时状态，通过 contextvars 传递）
# ============================================================

@runtime_checkable
class AgentContextProtocol(Protocol):
    """Agent 运行时上下文：会话 ID、模型名、角色 ID 等元信息。"""

    conversation_id: str
    model: str
    character_id: str
    is_wakeup: bool

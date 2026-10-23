"""规划域数据契约：可观测性事件（AgentEvent）。

domain 层零依赖约束下不引入 pydantic——本契约仅承载字段，供规划引擎
产出事件流，由上层（services/agent）映射为对外事件结构。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class AgentEvent:
    """规划/执行的可观测事件（对齐 services/agent.schemas.AgentEvent 的字段语义）。"""

    type: Literal[
        "thought",      # 思考过程
        "tool_call",    # 调用工具
        "tool_result",  # 工具执行结果
        "plan",         # 自主规划：完整计划（plan 字段为步骤列表）
        "plan_step",    # 计划单步状态更新
        "delta",        # 文本增量
        "error",        # 错误
        "done",         # 完成
        "ask_user",     # 向用户提问（等待回答期间阻塞）
    ]
    content: str = ""
    tool_name: str = ""
    tool_input: dict[str, Any] = field(default_factory=dict)
    tool_output: str = ""
    question: dict[str, Any] = field(default_factory=dict)
    plan: list[dict] = field(default_factory=list)
    plan_step: dict[str, Any] = field(default_factory=dict)
    error: str = ""

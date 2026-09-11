"""Agent 核心插槽契约（ai 插槽）。

隐喻映射：本 ABC 即「AI 专属插槽」的定义——任何实现 AgentPort 的模块
即为一颗可插入 ai 插槽的 Agent 芯片（非核心，可热插拔）。
依赖铁律：本文件零实现、零依赖（仅标准库 abc），其他层只经 ports/__init__.py 引用。
"""

from abc import ABC, abstractmethod
from typing import Any, Iterator


class AgentPort(ABC):
    """Agent 核心插槽：规划/执行/反应/提示/完成判定/意图路由。

    实现方需覆盖 Agent 主循环的全部入口；缺失任一抽象方法即无法装配（ABC 强制）。
    """

    @abstractmethod
    def run(self, prompt: str, context: dict[str, Any]) -> dict[str, Any]:
        """单次运行入口：ReAct 文本循环或原生 function calling 二选一，返回最终结果。"""

    @abstractmethod
    def stream(self, prompt: str, context: dict[str, Any]) -> Iterator[dict[str, Any]]:
        """流式事件出口：逐事件产出（工具调用/思维链/文本增量），消费方按类型分发。"""

    @abstractmethod
    def plan(self, task: str) -> dict[str, Any]:
        """计划生成：把任务拆成可执行步骤清单（含依赖与验收条件）。"""

    @abstractmethod
    def replan(self, plan: dict[str, Any], feedback: dict[str, Any]) -> dict[str, Any]:
        """重规划：执行受阻或需求变更时，依据反馈修订既有计划。"""

    @abstractmethod
    def build_prompt(self, user_input: str, persona: str, tools: list[str], memories: list[str]) -> str:
        """提示构建：把角色/工具清单/记忆注入用户输入，产出模型可消费的系统+用户消息。"""

    @abstractmethod
    def is_done(self, output: dict[str, Any]) -> bool:
        """完成判定：门控判断一轮输出是否已满足目标（true 即终止循环）。"""

    @abstractmethod
    def route_intent(self, message: str) -> str:
        """意图路由：把用户消息归类为四意图之一（如 闲聊/任务/记忆/情感），决定走哪条链路。"""

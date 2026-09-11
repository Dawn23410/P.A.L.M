"""工具插槽契约（工具总线）。

隐喻映射：工具即外设指令集——实现 ToolPort 的模块登记为可用工具，
Agent 主循环经本插槽发现、匹配、调用、防护。
依赖铁律：零实现、零依赖（仅标准库），其他层只经 ports/__init__.py 引用。
"""

from abc import ABC, abstractmethod
from typing import Any


class ToolPort(ABC):
    """工具插槽：注册/语义匹配/执行/代码防护。

    实现方（tool_registry/tool_matcher/code_guard）必须全部覆盖。
    """

    @abstractmethod
    def register(self, tool: dict[str, Any]) -> None:
        """工具注册：登记工具描述（名称/参数 schema/回调），供发现与调用。"""

    @abstractmethod
    def match(self, prompt: str) -> list[dict[str, Any]]:
        """语义匹配：按意图返回候选工具清单（含置信度），供主循环选择。"""

    @abstractmethod
    def execute(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """工具执行：按名调用已注册工具，返回结构化结果；未知名抛 KeyError。"""

    @abstractmethod
    def guard(self, code: str, lang: str) -> dict[str, Any]:
        """代码防护：静态预检生成代码（Python/JS/PowerShell），返回风险档位与命中规则。"""

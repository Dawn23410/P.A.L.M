"""守卫芯片插槽契约（chip 插槽，焊死核心）。

隐喻映射：GuardPort 即焊死的安全裁决芯片——统一规则引擎（5 档死线/严格/宽松/AI/
白名单）是唯一裁决内核，任何敏感动作先经本插槽评估，fail-closed。
依赖铁律：零实现、零依赖（仅标准库），其他层只经 ports/__init__.py 引用。
"""

from abc import ABC, abstractmethod
from typing import Any


class GuardPort(ABC):
    """守卫芯片插槽：动作裁决/策略管理。

    实现方（guardrail_engine/guardrail_policy）必须全部覆盖；
    AI 档无回调时实现方须 fail-closed deny（安全链铁律）。
    """

    @abstractmethod
    def evaluate(self, action: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        """动作裁决：评估一次敏感动作（类型/目标/参数），返回放行/拒绝/升级及档位。"""

    @abstractmethod
    def policies(self) -> list[dict[str, Any]]:
        """策略清单：返回全部现行规则（供前端 JSON 管理与审计导出）。"""

    @abstractmethod
    def set_policy(self, policy: dict[str, Any]) -> None:
        """策略更新：新增/替换一条规则；非法策略抛 ValueError 由调用方归一。"""

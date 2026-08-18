"""运维服务插槽契约（ram 插槽，内存服务）。

隐喻映射：用量/监控/缝合等运行期服务如内存中的服务进程——实现 OpsPort 的
模块插在 ram 插槽，随会话存活，不负责持久化（持久化走 sata 的 PersistPort）。
依赖铁律：零实现、零依赖（仅标准库），其他层只经 ports/__init__.py 引用。
"""

from abc import ABC, abstractmethod
from typing import Any


class OpsPort(ABC):
    """运维服务插槽：Token 用量/运行监控/定时任务。"""

    @abstractmethod
    def usage(self) -> dict[str, Any]:
        """Token 用量台账：返回累计消耗与分模型明细，供前端用量界面。"""

    @abstractmethod
    def monitor(self) -> dict[str, Any]:
        """运行监控：返回进程/资源/异常计数，供监控界面与告警。"""

    @abstractmethod
    def schedule(self, job: dict[str, Any]) -> None:
        """定时任务：登记/更新一个计划任务；触发时回调由实现方保证。"""

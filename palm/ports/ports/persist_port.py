"""持久化插槽契约（sata 插槽）。

隐喻映射：本 ABC 即 SATA 硬盘——实现 PersistPort 的模块负责会话/记忆的
落盘与恢复，是与「断电即失」的内存服务对应的长期存储面。
依赖铁律：零实现、零依赖（仅标准库），其他层只经 ports/__init__.py 引用。
"""

from abc import ABC, abstractmethod
from typing import Any


class PersistPort(ABC):
    """持久化插槽：会话落盘/恢复、记忆落盘。"""

    @abstractmethod
    def save_session(self, session: dict[str, Any]) -> None:
        """会话落盘：把会话（消息序列/元数据）写入持久介质。"""

    @abstractmethod
    def load_session(self, session_id: str) -> dict[str, Any]:
        """会话恢复：按标识取回会话；不存在返回空会话由调用方归一。"""

    @abstractmethod
    def save_memory(self, memory: dict[str, Any]) -> None:
        """记忆落盘：把运行期记忆快照持久化，供重启后重建。"""

"""记忆插槽契约（ram 插槽）。

隐喻映射：记忆即内存条——写入/检索/压缩/预算/情绪五因子都是内存服务；
断电（会话结束）后需经 persist 插槽落盘，本插槽只管运行期。
依赖铁律：零实现、零依赖（仅标准库），其他层只经 ports/__init__.py 引用。
"""

from abc import ABC, abstractmethod
from typing import Any


class MemoryPort(ABC):
    """记忆插槽：写入/语义检索/上下文压缩/Token 预算/情绪五因子。

    实现方（memory_writer/retriever/compressor/token_budget/emotion）必须全部覆盖。
    """

    @abstractmethod
    def write(self, payload: dict[str, Any]) -> None:
        """事件触发式写入：把对话/行为事件沉淀为可检索的记忆条目。"""

    @abstractmethod
    def retrieve(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """语义检索：按相关性返回 top_k 条记忆（向量/BM25 混合由实现方决定）。"""

    @abstractmethod
    def compress(self, session: dict[str, Any]) -> dict[str, Any]:
        """上下文压缩：长会话折叠为摘要+要点，保留关键事实用于注入。"""

    @abstractmethod
    def budget(self, usage: dict[str, Any]) -> dict[str, Any]:
        """Token 预算：按用量与上限给出可注入配额，防上下文超限。"""

    @abstractmethod
    def emotion(self, text: str) -> dict[str, Any]:
        """情绪五因子：对文本打分（仅输出非负值），供情感门控与角色反应使用。"""

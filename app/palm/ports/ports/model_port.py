"""模型插槽契约（cpu 插槽，焊死核心）。

隐喻映射：模型层是 CPU 核心，本 ABC 定义其对外指令集——任何模型桥/路由/供应商
模块必须实现，缺失即整机无法启动（焊死，非热插拔）。
依赖铁律：零实现、零依赖（仅标准库），其他层只经 ports/__init__.py 引用。
"""

from abc import ABC, abstractmethod
from typing import Any, Iterator


class ModelPort(ABC):
    """模型插槽：LLM 流式调用/单次补全/路由/健康。

    实现方（model_bridge/model_router/各供应商适配）必须全部覆盖。
    """

    @abstractmethod
    def stream_chat(self, messages: list[dict[str, Any]], model: str, **options: Any) -> Iterator[str]:
        """流式补全：逐 token 产出文本；消费方用于 SSE/打字机效果。"""

    @abstractmethod
    def complete(self, messages: list[dict[str, Any]], model: str, **options: Any) -> str:
        """单次补全：一次性返回完整文本（工具判定/短回答等非流式场景）。"""

    @abstractmethod
    def route(self, intent: str) -> str:
        """模型路由：按意图/成本把请求分派到 Pro/Flash 等具体模型标识。"""

    @abstractmethod
    def health(self) -> dict[str, Any]:
        """健康探测：返回可用模型清单与各模型可用性（供 BIOS 自检与前端展示）。"""

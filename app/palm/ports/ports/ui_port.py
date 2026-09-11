"""前端界面契约（ui 插槽）。

隐喻映射：前端界面即插在主板上的显示器——每个 screen 是一个界面模块，
经 UiPort 约定的端点清单与后端通信（fetch 统一收敛，不散落）。
已评审（2026-08-18）：前端采用原生 ES Modules，零构建；UiPort 为纯契约定义。
依赖铁律：本文件零实现、零依赖（仅标准库），前后端共享此契约语义。
"""

from abc import ABC, abstractmethod
from typing import Any


class UiPort(ABC):
    """前端界面契约：界面端点清单/界面渲染数据。

    Python 侧实现方为后端 API 面；JS 侧每个 screen 按同一契约提供
    endpoints() 与 render()，由 shell 校验装载。
    """

    @abstractmethod
    def endpoints(self) -> list[dict[str, Any]]:
        """界面端点清单：返回本界面依赖的后端端点（方法/路径/参数），供 shell 装载校验。"""

    @abstractmethod
    def render(self, screen: str, params: dict[str, Any]) -> dict[str, Any]:
        """渲染数据：按界面名与参数返回装配数据；未知界面返回空 dict 由调用方归一。"""

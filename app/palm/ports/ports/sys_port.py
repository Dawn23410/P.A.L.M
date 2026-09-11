"""板载系统服务插槽契约（board 插槽）。

隐喻映射：本 ABC 即主板板载设备——实现 SysPort 的模块（设置/文件/解析/兜底）
焊在主板上，提供全机通用基础服务，任何芯片都可能用到。
依赖铁律：零实现、零依赖（仅标准库），其他层只经 ports/__init__.py 引用。
"""

from abc import ABC, abstractmethod
from typing import Any


class SysPort(ABC):
    """板载系统服务插槽：应用设置/文件鉴权/解析分发。"""

    @abstractmethod
    def settings(self) -> dict[str, Any]:
        """应用设置：返回全部设置项（供前端设置界面与管理接口）。"""

    @abstractmethod
    def set_setting(self, key: str, value: Any) -> None:
        """应用设置写入：按键更新并持久化；非法键抛 ValueError 由调用方归一。"""

    @abstractmethod
    def file_gate(self, path: str) -> bool:
        """文件鉴权：判定路径是否在允许域（用户主目录）内，越界返回 false。"""

    @abstractmethod
    def parse(self, file_path: str) -> dict[str, Any]:
        """解析分发：按文件类型路由到文档解析/图片 OCR，返回结构化内容。"""

"""存储插槽契约（m2 插槽，核心存储）。

隐喻映射：本 ABC 即 M.2 固态盘槽位——实现 StoragePort 的模块即插入 m2 插槽的
核心存储设备（介质层），提供块级读写与健康自检。
依赖铁律：零实现、零依赖（仅标准库），其他层只经 ports/__init__.py 引用。
"""

from abc import ABC, abstractmethod
from typing import Any


class StoragePort(ABC):
    """存储插槽：介质层块读写/健康。

    实现方（block_store）负责真实落盘介质；上层（配额/分层/审计/索引）组合本 Port，
    不直接触碰文件系统。
    """

    @abstractmethod
    def read_block(self, key: str) -> bytes:
        """块读取：按 key 返回原始字节；key 缺失时抛 KeyError 由调用方归一。"""

    @abstractmethod
    def write_block(self, key: str, data: bytes) -> None:
        """块写入：按 key 落盘原始字节；介质层负责原子性与目录布局。"""

    @abstractmethod
    def delete_block(self, key: str) -> None:
        """块删除：按 key 移除；删除动作须经回收站语义（保险库兜底），禁止硬删。"""

    @abstractmethod
    def health(self) -> dict[str, Any]:
        """健康自检：返回容量/余量/读写状态，供 BIOS 自检与前端监控展示。"""

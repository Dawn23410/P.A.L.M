"""显示层插槽契约（pcie 插槽）。

隐喻映射：本 ABC 即显示输出口——实现 DisplayPort 的模块（桌面/壁纸/部件渲染）
插入 pcie 插槽，负责把内容渲染到用户可见的桌面与部件。
依赖铁律：零实现、零依赖（仅标准库），其他层只经 ports/__init__.py 引用。
"""

from abc import ABC, abstractmethod
from typing import Any


class DisplayPort(ABC):
    """显示层插槽：桌面/壁纸/部件渲染。"""

    @abstractmethod
    def render(self, spec: dict[str, Any]) -> bytes:
        """渲染：按规格（布局/组件/主题）产出图像字节，供展示。"""

    @abstractmethod
    def set_wallpaper(self, image: bytes) -> None:
        """壁纸：把图像字节设为桌面壁纸；失败返回异常由调用方降级。"""

    @abstractmethod
    def widgets(self) -> list[dict[str, Any]]:
        """部件清单：返回当前已注册桌面部件的描述，供管理界面展示。"""

"""GUI 自动化插槽契约（pcie 插槽，重外设）。

隐喻映射：本 ABC 即 PCIe 显卡/GUI 引擎——实现 GuiPort 的模块（Atlas 认知/
执行器 L0-L3/世界模型缓存）插入 pcie 插槽，接管桌面应用自动化。
依赖铁律：零实现、零依赖（仅标准库），其他层只经 ports/__init__.py 引用。
"""

from abc import ABC, abstractmethod
from typing import Any


class GuiPort(ABC):
    """GUI 自动化插槽：语义入口/世界模型/静态认知。"""

    @abstractmethod
    def automate(self, software_id: str, intent: str) -> dict[str, Any]:
        """语义自动化入口：软件标识 + 意图 → 执行结果；经执行器阶梯（UIA/OCR/LLM/VLC）兜底。"""

    @abstractmethod
    def world_model(self, screen: dict[str, Any]) -> dict[str, Any]:
        """世界模型：把屏幕快照/控件树解析为结构化场景，供执行器决策。"""

    @abstractmethod
    def atlas(self) -> dict[str, Any]:
        """静态认知：返回已知软件的控件规律/转移规律/坐标记忆（EMA，样本不足不可信）。"""

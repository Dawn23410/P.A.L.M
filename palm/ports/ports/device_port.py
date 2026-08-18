"""设备插槽契约（usb 插槽，五接口协议）。

隐喻映射：本 ABC 即 USB 插槽——任何外设芯片（声卡/网卡/其他外设）实现
DevicePort 即插入 USB 插槽，通过五通道协议（入站/出站/心跳/控制/数据）与主机通信。
首版纳入（2026-08-18 已评审）：契约先行，外设恢复授权即插即用。
依赖铁律：零实现、零依赖（仅标准库），其他层只经 ports/__init__.py 引用。
"""

from abc import ABC, abstractmethod
from typing import Any


class DevicePort(ABC):
    """设备插槽（USB）：五通道协议，任何外设芯片必须实现。"""

    @abstractmethod
    def ingest(self, payload: dict[str, Any]) -> None:
        """入站总线：承载控制/数据/外部事件，内部按类型路由。"""

    @abstractmethod
    def drain(self) -> list[dict[str, Any]]:
        """出站总线：抽取待发消息（心跳/数据包/出站数据），消费方轮询清空。"""

    @abstractmethod
    def heartbeat(self) -> str:
        """统一存活信号：返回就绪/异常两态标识；消费者收不到即视为离线。"""

    @abstractmethod
    def control(self, code: str, decoder: dict[str, Any]) -> dict[str, Any]:
        """控制面：控制码 + 解码器单入口，返回执行结果与状态。"""

    @abstractmethod
    def data(self, payload: dict[str, Any]) -> bytes:
        """数据面：与控制面分离的载荷通道（音频/文本/二进制），返回编码后字节。"""

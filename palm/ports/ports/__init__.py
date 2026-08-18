"""端口契约层总出口（唯一 import 点）。

契约铁律：
- 其他层（modules/bootstrap/frontend 装配）只允许 `from ports import ...` 引用本包，
  禁止直接 import 子模块（依赖方向由本出口收口，防止契约旁路）。
- 本包零实现、零依赖（仅标准库 abc/typing），可单独 import（P1 出口条件）。

隐喻映射（2026-08-18 评审）：插槽标签 → Port 类，见各模块 docstring。
"""

from ports.agent_port import AgentPort
from ports.audio_port import AudioPort
from ports.crypto_port import CryptoPort
from ports.device_port import DevicePort
from ports.display_port import DisplayPort
from ports.guard_port import GuardPort
from ports.gui_port import GuiPort
from ports.memory_port import MemoryPort
from ports.model_port import ModelPort
from ports.ops_port import OpsPort
from ports.persist_port import PersistPort
from ports.storage_port import StoragePort
from ports.sys_port import SysPort
from ports.tool_port import ToolPort
from ports.ui_port import UiPort

__all__ = [
    "AgentPort",
    "AudioPort",
    "CryptoPort",
    "DevicePort",
    "DisplayPort",
    "GuardPort",
    "GuiPort",
    "MemoryPort",
    "ModelPort",
    "OpsPort",
    "PersistPort",
    "StoragePort",
    "SysPort",
    "ToolPort",
    "UiPort",
]

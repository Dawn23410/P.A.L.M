"""声卡插槽契约（pcie 插槽，重外设）。

隐喻映射：本 ABC 即 PCIe 声卡——实现 AudioPort 的模块（语音识别/合成/声纹）
插入 pcie 插槽；当前未授权（N/O）时主板不装载实现，但契约保持可用。
依赖铁律：零实现、零依赖（仅标准库），其他层只经 ports/__init__.py 引用。
"""

from abc import ABC, abstractmethod
from typing import Any


class AudioPort(ABC):
    """声卡插槽：语音识别/语音合成/声纹识别。"""

    @abstractmethod
    def stt(self, audio: bytes) -> str:
        """语音识别：音频字节 → 文本；无授权/引擎缺失时抛依赖异常由调用方降级。"""

    @abstractmethod
    def tts(self, text: str) -> bytes:
        """语音合成：文本 → 音频字节（WAV）；CosyVoice/SoVITS 由实现方调度。"""

    @abstractmethod
    def voiceprint(self, audio: bytes) -> dict[str, Any]:
        """声纹识别：音频 → 声纹特征与分组归属，用于说话人确认。"""

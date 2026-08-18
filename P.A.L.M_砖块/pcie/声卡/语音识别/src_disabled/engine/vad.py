"""Silero VAD（语音活动检测）封装：检测说话段起止，供采集线程切分音频。

sherpa_onnx.VoiceActivityDetector 内部带缓冲：accept_waveform 喂入新采样后，
front() 返回正在累积的说话段，pop() 表示该段结束。模型文件缺失时构造抛
FileNotFoundError，由 server 捕获后降级为「无 VAD 直通」。
"""
from __future__ import annotations

import os

import numpy as np
import sherpa_onnx


class VadDetector:
    def __init__(self, model_path: str, sample_rate: int = 16000) -> None:
        if not os.path.isfile(model_path):
            raise FileNotFoundError(f"VAD 模型不存在: {model_path}")
        config = sherpa_onnx.VadModelConfig()
        config.silero_vad.model = model_path
        config.silero_vad.threshold = 0.5
        config.silero_vad.min_speech_duration = 0.25
        config.silero_vad.min_silence_duration = 0.5
        config.sample_rate = sample_rate
        self.sample_rate = sample_rate
        self._vad = sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=30)

    def accept_waveform(self, samples: np.ndarray) -> None:
        # sherpa-onnx 1.12+ 该接口只接受采样数组（采样率已在构造时由 config.sample_rate 固定）。
        self._vad.accept_waveform(samples)

    def has_segment(self) -> bool:
        return not self._vad.empty()

    @property
    def front(self) -> "object":
        # sherpa-onnx 1.12+ 由方法改为属性，直接返回当前 SpeechSegment 对象。
        return self._vad.front

    def pop(self):
        self._vad.pop()

    def flush(self):
        """立即结束当前说话段（停止监听时把残余语音收尾）。"""
        self._vad.flush()

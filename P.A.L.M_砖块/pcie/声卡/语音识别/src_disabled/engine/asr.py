"""流式 ASR（Zipformer 双语模型）封装：为每个说话段创建独立流，边喂边出中间结果。

模型目录约定含 encoder.onnx / decoder.onnx / joiner.onnx / tokens.txt 四个文件；
缺失任一文件时构造抛 FileNotFoundError，由 server 捕获后降级为不可用。
"""
from __future__ import annotations

import os

import numpy as np
import sherpa_onnx

# zipformer 首次解码最少样本数（50 帧 @16k）：实测低于 8000 时
# sherpa-onnx 1.13.4 的 C++ 解码器帧缓冲越界直接崩溃（非优雅返回空）。
_MIN_CHUNK = 8000
# 模型流式 chunk：multi-zh-hans 为 chunk-16（16×60ms=960ms）。decode_stream 一次只
# 解码一个 chunk，喂入大块后必须按 chunk 循环 decode，否则只解出开头一小段。
_CHUNK_SAMPLES = 15360


class StreamingAsr:
    REQUIRED_FILES = ["encoder.onnx", "decoder.onnx", "joiner.onnx", "tokens.txt"]

    @classmethod
    def is_ready(cls, model_dir: str) -> bool:
        """模型目录是否包含全部必需文件（server 先探测再构造，避免异常当缺失）。"""
        return all(os.path.isfile(os.path.join(model_dir, name)) for name in cls.REQUIRED_FILES)

    def __init__(self, model_dir: str, sample_rate: int = 16000) -> None:
        self.sample_rate = sample_rate
        # 按流 id 暂存未达最小解码长度的波形，凑够再解码（防 C++ 越界崩溃）。
        self._pending: dict[int, np.ndarray] = {}
        missing = [name for name in self.REQUIRED_FILES
                   if not os.path.isfile(os.path.join(model_dir, name))]
        if missing:
            raise FileNotFoundError(f"ASR 模型目录缺少文件: {', '.join(missing)}")
        # sherpa-onnx 1.12+ 改为工厂方法构造（旧 OnlineRecognizerConfig 已移除）；
        # zipformer 双语模型的 mel 特征维度固定为 80。
        self._recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
            tokens=os.path.join(model_dir, "tokens.txt"),
            encoder=os.path.join(model_dir, "encoder.onnx"),
            decoder=os.path.join(model_dir, "decoder.onnx"),
            joiner=os.path.join(model_dir, "joiner.onnx"),
            num_threads=1,
            sample_rate=sample_rate,
            feature_dim=80,
            enable_endpoint_detection=False,  # 分段交给 VAD，ASR 内不判定端点
        )

    def create_stream(self):
        return self._recognizer.create_stream()

    def feed(self, stream, samples: np.ndarray) -> None:
        """按流式 chunk 循环喂入并解码，尾部不足一块的并入下次。

        decode_stream 一次只消费一个 chunk（960ms），整段一次 accept 只会解出
        开头一小段，故必须切块循环（实测整段一次 decode 结果为空）。
        """
        samples = np.asarray(samples)
        key = id(stream)
        pending = self._pending.pop(key, None)
        if pending is not None:
            samples = np.concatenate([pending, samples])
        while samples.size >= _CHUNK_SAMPLES:
            stream.accept_waveform(self.sample_rate, samples[:_CHUNK_SAMPLES])
            self._recognizer.decode_stream(stream)
            samples = samples[_CHUNK_SAMPLES:]
        if samples.size > 0:
            self._pending[key] = samples

    def flush_stream(self, stream) -> None:
        """句段收尾：残余不足一块的波形补足最小安全块后解码（避免越界崩溃）。

        残余不足 _MIN_CHUNK 时放弃（喂入会触发 C++ 崩溃），仅损失句尾极短波形。
        """
        samples = self._pending.pop(id(stream), None)
        if samples is None or samples.size == 0:
            return
        if samples.size >= _MIN_CHUNK:
            stream.accept_waveform(self.sample_rate, samples)
            self._recognizer.decode_stream(stream)

    def partial(self, stream) -> str:
        return self._recognizer.get_result(stream)

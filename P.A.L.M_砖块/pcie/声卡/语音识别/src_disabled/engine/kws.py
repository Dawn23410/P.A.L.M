"""KWS（关键词唤醒）封装：在说话段内并行检测预设关键词，命中后附加到结果。

关键词模型目录约定含 encoder.onnx / decoder.onnx / joiner.onnx / tokens.txt /
keywords.txt；keywords.txt 可由主进程经 /api/stt/keywords 动态更新（写文件后
重建 KeywordSpotter）。模型或关键词文件缺失时构造抛 FileNotFoundError，由
server 捕获后降级为「不检测」。
"""
from __future__ import annotations

import os

import numpy as np
import sherpa_onnx

REQUIRED_FILES = ["encoder.onnx", "decoder.onnx", "joiner.onnx", "tokens.txt"]

# KWS 解码器最小安全块（与 ASR 同源问题）：实测 3200 采样触发 C++ 特征缓冲越界
# 直接退出进程（features.cc GetFrames），凑够 8000（500ms）才喂入解码。
_MIN_CHUNK = 8000
# KWS 模型 chunk-8：8×60ms=480ms=7680 采样。decode_stream 一次消费一个 chunk，
# 大块须循环喂入，否则只解出开头。
_KWS_CHUNK = 7680


def sanitize_keywords(tokens_path: str, lines: list[str]) -> tuple[list[str], list[str]]:
    """剔除音素不在模型词表中的关键词行，返回 (合法行, 被剔除行)。

    KWS 模型对不认识的音素会直接 exit 杀进程（C++ 层 InitKeywords），必须先预检。
    tokens 带调规则：只有韵母可带声调符号（zh ì 而不是 zhì），样例 keywords 常写错。
    """
    tokens = set()
    with open(tokens_path, encoding="utf-8") as fh:
        for line in fh:
            parts = line.split()
            if parts:
                tokens.add(parts[0])
    valid: list[str] = []
    dropped: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        phones = stripped.split("@")[0].strip().split()
        if all(phone in tokens for phone in phones):
            valid.append(stripped)
        else:
            dropped.append(stripped)
    return valid, dropped


class KeywordSpotter:
    def __init__(self, model_dir: str, keywords_file: str) -> None:
        missing = [name for name in REQUIRED_FILES
                   if not os.path.isfile(os.path.join(model_dir, name))]
        if missing:
            raise FileNotFoundError(f"KWS 模型目录缺少文件: {', '.join(missing)}")
        if not os.path.isfile(keywords_file):
            raise FileNotFoundError(f"KWS 关键词文件不存在: {keywords_file}")
        # sherpa-onnx 1.12+ 构造改为位置参数（tokens/encoder/decoder/joiner/keywords_file）。
        self._spotter = sherpa_onnx.KeywordSpotter(
            os.path.join(model_dir, "tokens.txt"),
            os.path.join(model_dir, "encoder.onnx"),
            os.path.join(model_dir, "decoder.onnx"),
            os.path.join(model_dir, "joiner.onnx"),
            keywords_file,
        )
        self._pending: dict[int, np.ndarray] = {}

    def create_stream(self):
        return self._spotter.create_stream()

    def feed(self, stream, samples: np.ndarray) -> None:
        """按流式 chunk 循环喂入解码，尾部不足一块的并入下次。

        与 ASR 同理：decode_stream 一次只消费一个 chunk（480ms），大块须切块循环。
        """
        samples = np.asarray(samples)
        key = id(stream)
        pending = self._pending.pop(key, None)
        if pending is not None:
            samples = np.concatenate([pending, samples])
        while samples.size >= _KWS_CHUNK:
            stream.accept_waveform(16000, samples[:_KWS_CHUNK])
            self._spotter.decode_stream(stream)
            samples = samples[_KWS_CHUNK:]
        if samples.size > 0:
            self._pending[key] = samples

    def hit_keyword(self, stream) -> str:
        """返回已解码部分命中的关键词；未命中返回空串。

        段尾不足最小块的残余采样不喂入（喂了会触发 C++ 崩溃），可能漏掉
        恰好落在句尾的关键词——KWS 仅作辅助标记，漏检可接受。
        """
        return self._spotter.get_result(stream)

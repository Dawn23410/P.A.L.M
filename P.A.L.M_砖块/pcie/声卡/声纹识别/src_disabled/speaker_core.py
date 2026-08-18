"""声纹核心：CAM++ 说话人嵌入提取 + 本地声纹库（注册/比对/1:N 识别）。

引擎子进程与主进程测试脚本共用此模块：提取部分仅依赖 sherpa_onnx（已在独立
.venv-speaker 中），不依赖 palm_sdk，保证子进程隔离（架构铁律：重 ML 运行时绝不进主进程）。

模型：CAM++（campplus）fp16 ONNX，192 维说话人嵌入，中文训练约 20 万说话人，
CPU 推理 ~70ms/句，余弦相似度比对。
"""
from __future__ import annotations

import json
import os
import time
from typing import Optional

import numpy as np


# 同一说话人余弦相似度典型区间 ~0.6–0.9，跨说话人 ~0.1–0.4；0.31 为 sherpa-onnx
# 默认验证阈值，测试脚本会按检验集重新扫描调优，但这里给一个可用默认值。
DEFAULT_THRESHOLD = 0.31
_EMBED_DIM = 192


def read_wav(path: str) -> tuple[np.ndarray, int]:
    """读 wav → 单声道 float32 波形(归一化到 [-1,1]) 与采样率。

    用 soundfile 兼容 16-bit PCM / 32-bit float / 立体声等任意格式，
    立体声自动下混为单声道（声纹模型吃单路）。sherpa_onnx 要求 float32 输入。
    """
    import soundfile as sf

    samples, sample_rate = sf.read(path, dtype="float32", always_2d=False)
    samples = np.asarray(samples, dtype=np.float32)
    if samples.ndim > 1:
        samples = samples.mean(axis=1)  # 下混单声道
    return samples, int(sample_rate)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """余弦相似度；零向量防御返回 0。"""
    na = np.linalg.norm(a)
    nb = np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


class SpeakerExtractor:
    """CAM++ 说话人嵌入提取器（封装 sherpa_onnx SpeakerEmbeddingExtractor）。"""

    def __init__(self, model_path: str, num_threads: int = 1) -> None:
        if not os.path.isfile(model_path):
            raise FileNotFoundError(f"声纹模型缺失: {model_path}（请先下载 CAM++ onnx 放入 speaker_models/）")
        import sherpa_onnx

        config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=model_path, num_threads=num_threads
        )
        self._extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config)
        self.model_path = model_path

    def compute_embedding(self, samples: np.ndarray, sample_rate: int) -> np.ndarray:
        """从 float32 波形提取 192 维说话人嵌入。

        samples: float32 归一化波形；sample_rate: 应与模型训练采样率一致(16000)。
        """
        samples = np.ascontiguousarray(samples, dtype=np.float32)
        stream = self._extractor.create_stream()
        stream.accept_waveform(sample_rate, samples)
        stream.input_finished()
        embedding = self._extractor.compute(stream)
        return np.asarray(embedding, dtype=np.float32)

    def compute_from_wav(self, wav_path: str) -> np.ndarray:
        samples, sr = read_wav(wav_path)
        return self.compute_embedding(samples, sr)


class SpeakerStore:
    """本地声纹库：说话人名称 → 平均嵌入向量，支持注册/验证/1:N 识别。

    持久化到 JSON（嵌入为列表），路径由 store_path 指定。注册时对新嵌入与
    既有嵌入做指数滑动平均，提升鲁棒性；识别取最高余弦相似度并比对阈值。
    """

    def __init__(self, store_path: str, threshold: float = DEFAULT_THRESHOLD) -> None:
        self.store_path = store_path
        self.threshold = threshold
        self.speakers: dict[str, dict] = {}
        self.load()

    def load(self) -> None:
        if os.path.isfile(self.store_path):
            try:
                with open(self.store_path, encoding="utf-8") as fh:
                    data = json.load(fh)
                self.speakers = data.get("speakers", {})
                self.threshold = data.get("threshold", self.threshold)
            except (ValueError, OSError):
                self.speakers = {}
        os.makedirs(os.path.dirname(self.store_path) or ".", exist_ok=True)

    def save(self) -> None:
        with open(self.store_path, "w", encoding="utf-8") as fh:
            json.dump(
                {"threshold": self.threshold, "speakers": self.speakers},
                fh, ensure_ascii=False, indent=2,
            )

    def enroll(self, name: str, embedding: np.ndarray, alpha: float = 0.5) -> None:
        """注册/更新说话人：首次直接存入，已有则与历史平均做滑动平均。"""
        emb = np.asarray(embedding, dtype=np.float32)
        if name in self.speakers:
            prev = np.asarray(self.speakers[name]["embedding"], dtype=np.float32)
            merged = (1 - alpha) * prev + alpha * emb
            self.speakers[name]["embedding"] = merged.tolist()
            self.speakers[name]["count"] = self.speakers[name].get("count", 1) + 1
        else:
            self.speakers[name] = {
                "embedding": emb.tolist(),
                "count": 1,
                "created": time.time(),
            }
        self.save()

    def verify(self, name: str, embedding: np.ndarray) -> dict:
        """验证：与指定说话人比对，返回 {match, similarity, exists}。"""
        if name not in self.speakers:
            return {"match": False, "similarity": 0.0, "exists": False}
        ref = np.asarray(self.speakers[name]["embedding"], dtype=np.float32)
        sim = cosine_similarity(ref, np.asarray(embedding, dtype=np.float32))
        return {"match": sim >= self.threshold, "similarity": sim, "exists": True}

    def identify(self, embedding: np.ndarray) -> dict:
        """1:N 识别：返回相似度最高的说话人；低于阈值则判为未知。"""
        emb = np.asarray(embedding, dtype=np.float32)
        best_name: Optional[str] = None
        best_sim = -1.0
        for name, info in self.speakers.items():
            sim = cosine_similarity(np.asarray(info["embedding"], dtype=np.float32), emb)
            if sim > best_sim:
                best_sim = sim
                best_name = name
        if best_name is not None and best_sim >= self.threshold:
            return {"speaker": best_name, "similarity": best_sim, "match": True}
        return {"speaker": None, "similarity": best_sim, "match": False}

    def list_speakers(self) -> list[dict]:
        return [
            {"name": name, "count": info.get("count", 1)}
            for name, info in self.speakers.items()
        ]

    def remove(self, name: str) -> bool:
        if name in self.speakers:
            del self.speakers[name]
            self.save()
            return True
        return False

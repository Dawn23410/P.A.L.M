"""Ollama 嵌入适配器（内嵌独立项目）。

从 P.A.L.M 记忆层向量记忆的 Ollama 回退中抽取出来，作为**可选的外部嵌入后端**独立提供。
注意：本包**不再**作为 palm-memory 向量记忆的回退路径——记忆层已改为纯本地 ONNX（bge-m3）。
本包仅供需要调用 Ollama embed API 的场景独立使用（例如把 Ollama 当作独立嵌入服务）。

设计：
- 主模型失败时自动降级到后备模型；全部不可用返回 None（fail-closed），绝不抛异常。
- 仅依赖标准库 urllib，零第三方依赖（与 加解密内核 / palm-budget 同级、零硬依赖风格一致）。
- 同维度约束：Ollama 主/后备模型必须与目标向量库维度一致（bge-m3 / mxbai-embed-large 均为 1024 维）。
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Optional

_LOGGER = logging.getLogger(__name__)


class OllamaEmbedder:
    """调用本地/远程 Ollama embed API 批量生成向量。

    用法：
        from palm_ollama import OllamaEmbedder
        emb = OllamaEmbedder().embed(["今天天气真好", "另一句话"])
        # -> list[list[float]] 或 None（服务不可用 / 全部模型失败）
    """

    def __init__(self, base_url: str = "http://127.0.0.1:11434",
                 model: str = "bge-m3:latest",
                 fallback_model: str = "mxbai-embed-large:latest",
                 timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.fallback_model = fallback_model
        self.timeout = timeout

    def embed(self, texts: list[str]) -> Optional[list[list[float]]]:
        """批量嵌入；主模型失败降级后备模型；全部失败返回 None。

        Args:
            texts: 待嵌入文本列表。
        Returns:
            list[list[float]]（维度由 Ollama 模型决定）或 None。
        """
        for attempt_model in [self.model, self.fallback_model]:
            try:
                req = urllib.request.Request(
                    f"{self.base_url}/api/embed",
                    data=json.dumps({"model": attempt_model, "input": texts}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                embeddings = data.get("embeddings")
                if embeddings:
                    if attempt_model != self.model:
                        _LOGGER.info("embedding 降级 %s ← %s", attempt_model, self.model)
                    return embeddings
            except (urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError):
                continue
        _LOGGER.warning("所有 Ollama embedding 模型均不可用（%s / %s）", self.model, self.fallback_model)
        return None

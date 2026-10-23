"""palm-ollama —— Ollama 嵌入 + 模型管理工作区（内嵌独立项目）。

职责边界（重要）
----------------
本包**只管嵌入与本地模型管理，不提供对话能力**：

- :class:`OllamaEmbedder` —— 嵌入（原生 `/api/embed`）。从 P.A.L.M 记忆层向量记忆的
  Ollama 回退中抽取；记忆层现已改为纯本地 ONNX（bge-m3），本类仅供需要独立调用
  Ollama embed API 的场景使用。
- `palm_ollama.workspace` —— 本地模型工作区（目录浏览 / 模型文件传输与下载）。

**对话（`/api/chat`）不在本包**：那属于"模型调用"，已统一收归 `LLM内核/palm_llm`，
见 `palm_llm.providers.OllamaProvider`（配置里写 `type: "ollama"` 即走原生协议）。
这样拆分是为了让本包保持**零第三方依赖**（仅标准库），可被记忆层等底层模块安全引用，
而不被迫拖入 httpx / pydantic。

共性约定：仅经 `_net` 出网（主工程在场走网卡门面，否则标准库降级）、fail-closed
（不可用产出 `None` / 错误而非抛异常）。
"""
from __future__ import annotations

from .embedder import OllamaEmbedder

__version__ = "0.2.0"
__all__ = ["OllamaEmbedder"]

"""Ollama 引导服务：向导规格与来源解析（收敛自 Ollama 向导代理 brick）。

仅操作 localhost 的 Ollama，符合「模型发现」同源思路。运行检测/下载/转换
逻辑在同目录 connection/catalog/downloader/convert，本模块只保留向导所需的
规格常量与纯解析函数（API 壳已随「放弃接口」原则废弃）。
"""
from __future__ import annotations

import hashlib
from typing import Optional

# 向导预设模型清单（统一由本模块下发，前端仅收集选择）。
OLLAMA_PRESETS = [
    {"value": "llama3.2", "label": "Llama 3.2（轻量，推荐入门）"},
    {"value": "llama3.1", "label": "Llama 3.1"},
    {"value": "qwen2.5", "label": "Qwen 2.5"},
    {"value": "deepseek-r1", "label": "DeepSeek-R1（推理）"},
    {"value": "phi3", "label": "Phi 3"},
    {"value": "mistral", "label": "Mistral"},
    {"value": "gemma2", "label": "Gemma 2"},
]

# 向导默认模型参数（仅 UI 预留，暂不接入对话）。
DEFAULT_PARAMS = {"temperature": 0.7, "top_p": 0.9, "max_tokens": 2048}

DEFAULT_OLLAMA = "http://localhost:11434"


def base_url(base_url: Optional[str]) -> str:
    """返回 Ollama 原生 API 基址（host 根，如 http://localhost:11434）。

    向导传入的 base_url 往往是 OpenAI 兼容地址（带 /v1 后缀）；Ollama 原生
    管理 API（/api/create、/api/pull、/api/tags）挂在 host 根、没有 /v1，
    不剥掉会拼成不存在的路由。统一归一到 host 根。
    """
    u = (base_url or DEFAULT_OLLAMA).rstrip("/")
    while u.lower().endswith("/v1"):
        u = u[: -len("/v1")].rstrip("/")
    return u


def resolve_source(srcs: dict, source: str) -> tuple[Optional[str], Optional[dict]]:
    """解析下载来源。source="auto"（默认）时自动挑选首个可用来源（魔搭优先，回退 HF）。"""
    srcs = srcs or {}
    if source and source != "auto" and srcs.get(source, {}).get("url"):
        return source, srcs[source]
    for s in ("modelscope", "hf"):
        if srcs.get(s, {}).get("url"):
            return s, srcs[s]
    return None, None


def safe_name(name: str) -> str:
    """把模型名清洗为安全文件名（去空格、非单词字符转下划线）。"""
    import re
    return re.sub(r"[^\w.-]", "_", (name or "").strip())


def sha256_chunked(path: str, chunk_size: int = 1024 * 1024) -> str:
    """分块计算文件 SHA-256（大文件避免一次性读入内存）。"""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()

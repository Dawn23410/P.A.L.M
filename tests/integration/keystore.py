"""API 密钥/后端配置定位与加载（测试用，离线安全）。

目标（用户需求 1）：把散落在各处的密钥/后端配置「找出来」并统一暴露：
- 桌面 ``可用API.json``：OpenAI 兼容端点的 provider/format/base_url/api_key/default_model。
- 项目 ``.env``：SoVITS(GSV) TTS 服务地址与参考音色；mentalcore/.env。

设计原则：
- 密钥绝不进入代码或日志（仅打印字段名/来源路径）。
- 加载失败返回 None + 原因，由测试方决定 skip 还是 fail。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Optional


# 候选密钥文件（按优先级）。桌面「可用API.json」为当前主用。
_CANDIDATE_KEY_FILES = [
    os.path.join(os.path.expanduser("~"), "Desktop", "可用API.json"),
    os.path.join(os.path.expanduser("~"), "Desktop", "可用API.txt"),
    os.path.join(os.getcwd(), "可用API.json"),
]


@dataclass
class LLMKey:
    provider: str
    fmt: str
    base_url: str
    api_key: str
    default_model: str
    source: str
    recommended_models: list[str] = None

    @property
    def redacted_key(self) -> str:
        k = self.api_key
        return (k[:6] + "…" + k[-4:]) if len(k) > 10 else "***"


def find_api_key_file() -> Optional[str]:
    """返回第一个存在的密钥文件路径（按 _CANDIDATE_KEY_FILES 顺序）。"""
    for p in _CANDIDATE_KEY_FILES:
        if os.path.isfile(p):
            return p
    return None


def load_llm_key() -> tuple[Optional[LLMKey], Optional[str]]:
    """加载 LLM 端点密钥。

    返回 (LLMKey, None) 成功；或 (None, 原因) 失败。
    """
    path = find_api_key_file()
    if not path:
        return None, "未找到密钥文件（候选: " + ", ".join(_CANDIDATE_KEY_FILES) + "）"
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
    except Exception as e:
        return None, f"读取密钥文件失败 {path}: {e}"
    try:
        key = LLMKey(
            provider=d.get("provider", "unknown"),
            fmt=d.get("format", "openai"),
            base_url=d.get("base_url", ""),
            api_key=d.get("api_key", ""),
            default_model=d.get("default_model", ""),
            source=path,
            recommended_models=d.get("recommended_models", []),
        )
    except Exception as e:
        return None, f"密钥文件结构异常 {path}: {e}"
    if not key.api_key or not key.base_url:
        return None, f"密钥文件缺少 api_key/base_url: {path}"
    return key, None


def load_gsv_config(project_root: str) -> dict:
    """从项目 ``.env`` 读取 SoVITS(GSV) TTS 服务配置（不读密钥值到日志）。"""
    cfg = {}
    env_path = os.path.join(project_root, ".env")
    if not os.path.isfile(env_path):
        return cfg
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            if k.startswith("SOVITS_"):
                cfg[k] = v
    return cfg


# ── 与 llm 包的桥接 ──
def build_provider_config(key: LLMKey, model: str | None = None):
    """从 LLMKey 构造 llm.models.ProviderConfig（供 get_provider_instance 使用）。"""
    from llm.models import ProviderConfig
    return ProviderConfig(
        name=key.provider,
        type="openai_compat" if key.fmt == "openai" else key.fmt,
        base_url=key.base_url,
        api_key=key.api_key,
        default_model=model or key.default_model,
    )

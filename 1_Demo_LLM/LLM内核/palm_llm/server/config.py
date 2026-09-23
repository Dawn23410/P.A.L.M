"""全局配置 (config.json) 的读写与默认值管理。"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from .models import AppConfig, ProviderConfig

# 数据根目录：优先环境变量 PALM_LLM_HOME（config.json / data/ 都挂这里），
# 默认 ~/.palm-llm，避免 pip 安装后把用户数据写进 site-packages。
HOME_DIR = Path(
    os.environ.get("PALM_LLM_HOME", str(Path.home() / ".palm-llm"))
).resolve()
BASE_DIR = HOME_DIR          # 兼容旧名（cli 等调用方引用 BASE_DIR）
CONFIG_PATH = HOME_DIR / "config.json"
DATA_DIR = HOME_DIR / "data"
CONV_DIR = DATA_DIR / "conversations"
UPLOAD_DIR = DATA_DIR / "uploads"


def _default_config() -> AppConfig:
    return AppConfig(
        providers=[],
        active_provider="",
        active_model="",
        system_prompt="你是一个有帮助的AI助手。",
        presets=[],
    )


def load_config() -> AppConfig:
    if not CONFIG_PATH.exists():
        cfg = _default_config()
        save_config(cfg)
        return cfg
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        cfg = _default_config()
        save_config(cfg)
        return cfg
    # 容错：缺失字段用默认值补齐
    cfg = AppConfig.model_validate(raw)
    return cfg


def save_config(cfg: AppConfig) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        cfg.model_dump_json(indent=2, exclude_none=False),
        encoding="utf-8",
    )


def get_provider(provider_id: Optional[str] = None) -> Optional[ProviderConfig]:
    cfg = load_config()
    pid = provider_id or cfg.active_provider
    if not pid:
        return None
    for p in cfg.providers:
        if p.id == pid:
            return p
    return None


def ensure_dirs() -> None:
    for d in (DATA_DIR, CONV_DIR, UPLOAD_DIR):
        d.mkdir(parents=True, exist_ok=True)

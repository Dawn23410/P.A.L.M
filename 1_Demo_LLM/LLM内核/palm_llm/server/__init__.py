"""对话应用服务层（原 engine/backend）：配置管理 / 会话持久化 / SSE 调度 / 模型发现。

分层边界：
  - 本包（server）为应用层，pydantic 模型 + 磁盘状态 + HTTP/CLI 适配；
  - 调用内核（palm_llm.providers）时经 models 的 to_kernel() 显式转换，
    不依赖内核字段的隐式 duck-type。
数据目录：环境变量 PALM_LLM_HOME（默认 ~/.palm-llm）。
"""
from .chat import resolve_image, run_chat
from .config import (
    BASE_DIR,
    HOME_DIR,
    ensure_dirs,
    get_provider,
    load_config,
    save_config,
)
from .models import (
    AppConfig,
    ChatRequest,
    Conversation,
    Message,
    ModelParameters,
    Preset,
    ProviderConfig,
)
from . import discovery, storage

__all__ = [
    "AppConfig",
    "BASE_DIR",
    "ChatRequest",
    "Conversation",
    "HOME_DIR",
    "Message",
    "ModelParameters",
    "Preset",
    "ProviderConfig",
    "discovery",
    "ensure_dirs",
    "get_provider",
    "load_config",
    "resolve_image",
    "run_chat",
    "save_config",
    "storage",
]

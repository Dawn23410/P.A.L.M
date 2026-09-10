"""薄桥接层：实现已抽离至独立包 palm_llm（palm_llm.server，含 providers 内核）。

数据目录经 PALM_LLM_HOME 钉在本 engine/ 下，旧调用方（src/cli、src/server、tests）
的 from backend.* 导入零改动。注意：若进程先导入了 palm_llm（未设环境变量），
其数据目录将默认 ~/.palm-llm，与本 shim 的钉定互不影响（各进程独立）。
"""
import os as _os
from pathlib import Path as _Path

_os.environ.setdefault(
    "PALM_LLM_HOME", str(_Path(__file__).resolve().parent.parent)
)

import palm_boot  # noqa: E402,F401  自举：挂载内嵌项目
from palm_llm.server import *  # noqa: F401,F403
from palm_llm.server import (  # noqa: F401
    AppConfig,
    ChatRequest,
    Conversation,
    Message,
    ModelParameters,
    Preset,
    ProviderConfig,
    discovery,
    ensure_dirs,
    get_provider,
    load_config,
    resolve_image,
    run_chat,
    save_config,
    storage,
)

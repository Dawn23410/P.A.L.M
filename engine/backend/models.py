"""薄桥接层：实现见 palm_llm.server.models。"""
import palm_boot  # noqa: E402,F401  自举：挂载内嵌项目
from palm_llm.server.models import *  # noqa: F401,F403
from palm_llm.server.models import (  # noqa: F401
    AppConfig, ChatRequest, Conversation, Message, ModelParameters, Preset, ProviderConfig,
)

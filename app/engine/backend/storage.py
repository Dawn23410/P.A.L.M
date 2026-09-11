"""薄桥接层：实现见 palm_llm.server.storage。"""
import palm_boot  # noqa: E402,F401  自举：挂载内嵌项目
from palm_llm.server.storage import *  # noqa: F401,F403
from palm_llm.server.storage import (  # noqa: F401
    append_message, create_conversation, delete_conversation, export_conversation,
    get_conversation, import_conversation, list_conversations, save_conversation,
)

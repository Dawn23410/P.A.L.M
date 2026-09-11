"""薄桥接层：实现见 palm_llm.providers.base。"""
import palm_boot  # noqa: E402,F401  自举：挂载内嵌项目
from palm_llm.providers.base import *  # noqa: F401,F403
from palm_llm.providers.base import BaseProvider, close_client, get_client  # noqa: F401

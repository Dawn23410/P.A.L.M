"""Agent 砖块包。"""
from . import brick  # noqa: F401
# 门面符号：evolution 砖经 get_agent_api() 取用的回调入口（避免反向 import）。
from .brick import run_proactive_stream, push_bubble  # noqa: F401
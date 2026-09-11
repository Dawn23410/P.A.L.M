"""桥接：再导出 palm_llm.providers.openai_compat（真实实现见独立包 palm_llm）。"""
import palm_boot  # noqa: E402,F401  自举：挂载内嵌项目
from palm_llm.providers.openai_compat import *  # noqa: F401,F403
from palm_llm.providers.openai_compat import OpenAICompatProvider  # noqa: F401

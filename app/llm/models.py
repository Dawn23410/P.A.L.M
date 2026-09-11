"""桥接：再导出 palm_llm.models（真实实现见独立包 palm_llm）。"""
import palm_boot  # noqa: E402,F401  自举：挂载内嵌项目
from palm_llm.models import *  # noqa: F401,F403
from palm_llm.models import Message, ModelParameters, ProviderConfig  # noqa: F401

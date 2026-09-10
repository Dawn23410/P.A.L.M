"""薄桥接层：实现见 palm_memory.domain_memory.vector_memory。"""
import palm_boot  # noqa: E402,F401  自举：挂载内嵌项目
from palm_memory.domain_memory.vector_memory import *  # noqa: F401,F403
from palm_memory.domain_memory.vector_memory import VectorMemory, purge_vector_by_conv_id  # noqa: F401

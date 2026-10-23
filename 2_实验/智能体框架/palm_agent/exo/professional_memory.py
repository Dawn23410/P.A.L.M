"""薄桥接层：实现在主工程 agent 框架（`palm.services.agent.dual.professional_memory`）。

外骨骼并入主工程时去重：本模块原为移植副本，现直接复用主工程原件。
"""
from palm_agent.dual.professional_memory import *  # noqa: F401,F403
from palm_agent.dual.professional_memory import (  # noqa: F401
    K_EXPERIENCE,
    K_USER_PROFILE,
    K_ERROR,
    ALLOWED_KINDS,
    ProfessionalMemoryRecord,
    ProfessionalMemory,
    get_default_professional_memory,
    schedule_trace_digest,
)

_HostProfessionalMemory = ProfessionalMemory


class ProfessionalMemory(_HostProfessionalMemory):  # type: ignore[no-redef]
    """适配层：主工程版要求落盘路径；外骨骼 mock 模式传 None（零落盘）时用临时库。"""

    def __init__(self, db_path=None, *args, **kwargs):
        if db_path is None:
            import os
            import tempfile

            db_path = os.path.join(tempfile.mkdtemp(prefix="exo_mem_"), "exo_memory.db")
        super().__init__(db_path, *args, **kwargs)

# -*- coding: utf-8 -*-
"""palm_sdk.bricks._shared 包：跨砖共享服务的独立态安全桩。

重新导出各子模块，使 `from palm_sdk.bricks._shared import eventbus` 等同
`from palm_sdk.bricks._shared.eventbus import ...` 的模块级访问可用。
"""
from . import emotion  # noqa: F401
from . import eventbus  # noqa: F401
from . import handle  # noqa: F401
from . import interop  # noqa: F401
from . import paths  # noqa: F401
from . import tooling  # noqa: F401
from . import transport  # noqa: F401
from . import watchdog  # noqa: F401
from . import redundancy  # noqa: F401

# 兼容：`from palm_sdk.bricks._shared import eventbus`
from .eventbus import emit, STORAGE_ARCHIVE, STORAGE_CLEANUP, STORAGE_QUOTA_EXCEEDED  # noqa: F401

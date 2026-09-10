"""薄桥接层：实现已迁至独立项目「沙箱」（`palm_sandbox`）。

原模块路径与导出保留，调用面不变（如 `from sandbox.sandbox_cube import SandboxCube`）。
"""
import palm_boot  # noqa: F401,E402  自举：挂载沙箱等独立项目

from palm_sandbox.ast import *  # noqa: F401,F403,E402

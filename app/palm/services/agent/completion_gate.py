"""薄桥接层：实现已迁至独立项目「智能体框架」（`palm_agent`）。

原模块路径与导出**完整保留**（含下划线私有符号），调用面不变。
"""
import palm_boot  # noqa: F401,E402  自举：挂载独立项目

import palm_agent.completion_gate as _impl  # noqa: E402

globals().update({k: v for k, v in vars(_impl).items() if not k.startswith("__")})

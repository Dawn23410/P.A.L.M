"""薄桥接层：实现已迁至独立项目「GUI自动化」（`palm_gui`）。

原模块路径与导出**完整保留**（含下划线私有符号），调用面不变。
"""
import palm_boot  # noqa: F401,E402  自举：挂载独立项目

import palm_gui.adapters_gui.background_scan as _impl  # noqa: E402

globals().update({k: v for k, v in vars(_impl).items() if not k.startswith("__")})

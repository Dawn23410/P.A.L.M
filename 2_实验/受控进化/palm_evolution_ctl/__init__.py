


# ── 宿主挂载 ────────────────────────────────────────────────────────
# 本项目的砖块按契约依赖 palm._core（容器 / 配置 / 路径 / 网卡门面），
# 独立运行时自动把主工程加入 sys.path；主工程不在场则跳过（功能按契约降级）。
import os as _os
import sys as _sys

_HOST = _os.path.join(
    _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))),
    "P.A.L.M -1")
if _os.path.isdir(_HOST) and _HOST not in _sys.path:
    _sys.path.append(_HOST)

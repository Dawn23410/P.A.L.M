


# ── 宿主挂载 ────────────────────────────────────────────────────────
import os as _os
import sys as _sys

_HOST = _os.path.join(
    _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))),
    "P.A.L.M -1")
if _os.path.isdir(_HOST) and _HOST not in _sys.path:
    _sys.path.append(_HOST)

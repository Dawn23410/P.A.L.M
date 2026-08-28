"""P.A.L.M gui microkernel.

跨平台说明：
- Windows：完整的桌面自动化（uiautomation / pyautogui / win32）。
- Linux / macOS：桌面自动化不可用，自动降级为空壳，避免 import 期崩溃。
  切勿在非 Windows 平台 import 任何依赖 uiautomation 的子模块。
"""

from __future__ import annotations

import sys

IS_DESKTOP_AUTOMATION_AVAILABLE = sys.platform == "win32"

_PLATFORM_NAME = {
    "win32": "windows",
    "darwin": "macos",
}.get(sys.platform, "linux" if sys.platform.startswith("linux") else "unknown")


def get_gui_backend_status() -> dict:
    """返回 gui 能力状态，供启动日志/诊断使用。"""
    return {
        "platform": _PLATFORM_NAME,
        "desktop_automation": IS_DESKTOP_AUTOMATION_AVAILABLE,
    }

"""辅助模式（屏幕阅读器模式）对内开关：让窗口主动暴露完整 UIA 树。

这不是 OCR 读屏，而是 Windows 原生的「辅助功能客户端」语义：当系统被告知
「屏幕阅读器正在运行」时，部分平时对 UIA 隐藏/稀疏暴露的窗口（游戏、自绘、
Electron、部分国产软件）会切换为完整可访问性树暴露，UIA 客户端即可读到
原本读不到的控件。

本模块提供**仅对内控制**的开关，绝不暴露给 LLM 工具参数：
- set_assistive_mode(enabled)：切换 Windows 全局屏幕阅读器标志 + best-effort COM 安全感知；
- is_assistive_mode()：读当前状态。

机制两层：
1) SystemParametersInfo(SPI_SETSCREENREADER)：全局「屏幕阅读器运行」标志，应用据此暴露完整树；
2) CoInitializeSecurity(EOAC_SECURITY_AWARE)：COM 层声明本进程为安全感知/辅助技术客户端
   （仅在 COM 尚未初始化时生效；uiautomation import 即初始化 COM，故必须在它之前调用。
   本模块在导入期即尝试声明，并由 gui/__init__ 最先导入以保证早于 uiautomation）。
"""
from __future__ import annotations

import ctypes
import logging

_LOGGER = logging.getLogger(__name__)

# SystemParametersInfo 动作码
SPI_GETSCREENREADER = 0x0046
SPI_SETSCREENREADER = 0x0047
SPIF_SENDCHANGE = 0x0002

# CoInitializeSecurity 能力位（仅声明安全感知/辅助技术客户端，最保守）
EOAC_SECURITY_AWARE = 0x1000

# 模块级运行时状态（不依赖 settings 落盘，保证可随时开关、可测试还原）
_state = {"enabled": False, "com_applied": False, "com_import_msg": ""}


def _com_security_aware() -> tuple[bool, str]:
    """best-effort：声明本进程为 COM 安全感知/辅助技术客户端。

    必须在首次 COM 调用前调用才生效；uiautomation import 时已 CoInitialize，
    故通常返回 RPC_E_TOO_LATE——此时 SPI 标志已足够，仅记录、不视为失败。
    """
    try:
        ole32 = ctypes.windll.ole32
    except Exception as exc:
        return False, f"ole32 不可用: {exc}"
    try:
        # 先确保本线程 COM 已初始化（CoInitializeSecurity 要求 COM 已起），
        # 忽略已初始化/RPC_E_CHANGED_MODE（线程已在其它套间）——只要 COM 起来即可。
        ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        ole32.CoInitializeEx.restype = ctypes.HRESULT
        ole32.CoInitializeEx(None, 2)  # COINIT_APARTMENTTHREADED=2（与 uiautomation 一致）
        ole32.CoInitializeSecurity.argtypes = [
            ctypes.c_void_p, ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p,
            ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong,
            ctypes.c_void_p,
        ]
        ole32.CoInitializeSecurity.restype = ctypes.HRESULT
        hr = ole32.CoInitializeSecurity(
            None, -1, None, None,
            0,  # RPC_C_AUTHN_LEVEL_DEFAULT
            3,  # RPC_C_IMP_LEVEL_IMPERSONATE
            None,
            EOAC_SECURITY_AWARE,
            None,
        )
        hr_val = hr & 0xFFFFFFFF
        if hr_val in (0, 1):  # S_OK / S_FALSE（已初始化但成功）
            return True, "OK"
        if hr_val == 0x80010119:  # RPC_E_TOO_LATE
            return False, "COM 已初始化，CoInitializeSecurity 过晚（SPI 标志已足以生效）"
        return False, f"CoInitializeSecurity 失败 hr=0x{hr_val:08X}"
    except Exception as exc:
        return False, str(exc)


def _apply_com_at_import() -> None:
    """模块导入即尝试声明 COM 辅助技术客户端（越早越好，必须在 uiautomation 之前）。

    仅在「本进程尚未初始化 COM」时生效；若其它模块已先 import uiautomation，
    则为 RPC_E_TOO_LATE，无害（SPI 标志仍可用）。结果记入 _state 供上报。
    """
    ok, msg = _com_security_aware()
    _state["com_applied"] = ok and "过晚" not in msg
    _state["com_import_msg"] = msg
    _LOGGER.info("导入期 COM 安全感知声明：%s (%s)", ok, msg)


def _sysparam_screen_reader(on: bool) -> tuple[bool, str]:
    """切换 Windows 全局「屏幕阅读器正在运行」标志。返回 (成功, 说明)。"""
    try:
        user32 = ctypes.windll.user32
    except Exception as exc:
        return False, f"user32 不可用（非 Windows 或受限）: {exc}"
    # uiParam=BOOL 状态；pvParam=NULL；fWinIni=发送变更通知
    ok = user32.SystemParametersInfoW(
        SPI_SETSCREENREADER, 1 if on else 0, None, SPIF_SENDCHANGE
    )
    if ok:
        return True, "OK"
    return False, "SystemParametersInfoW 返回 0（调用失败）"


def set_assistive_mode(enabled: bool) -> dict:
    """开启/关闭辅助模式（仅对内控制）。返回结构化结果供调用方上报。"""
    sys_ok, sys_msg = _sysparam_screen_reader(enabled)
    # COM 安全感知已在导入期声明（一次性）；此处仅补报，不再重复声明
    com_ok, com_msg = _state["com_applied"], _state["com_import_msg"]
    if not enabled:
        com_ok, com_msg = True, "skipped(关闭)"
    _state["enabled"] = enabled and sys_ok
    _LOGGER.info(
        "辅助模式 %s: SPI=%s(%s) COM=%s(%s)",
        "开启" if enabled else "关闭", sys_ok, sys_msg, com_ok, com_msg,
    )
    return {
        "enabled": _state["enabled"],
        "requested": enabled,
        "spi_ok": sys_ok,
        "spi_msg": sys_msg,
        "com_ok": com_ok,
        "com_msg": com_msg,
    }


def is_assistive_mode() -> bool:
    """当前辅助模式是否处于开启态。"""
    return bool(_state["enabled"])


def ensure_off() -> dict:
    """测试/退出保险：强制关闭并恢复 Windows 标志（幂等）。"""
    return set_assistive_mode(False)


# 模块导入即尝试声明 COM 辅助技术客户端（必须在 uiautomation 之前，越早越好）
_apply_com_at_import()

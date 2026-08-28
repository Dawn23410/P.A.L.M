"""run_code 执行前安全网：静态风险扫描 + 系统级硬阻断（移植自 palm/services/agent/code_guard.py）。

- scan_code_risks：5 类风险静态扫描（daemon 无 join / 破坏性删除 / 子进程无超时 /
  系统路径删除 / detach 后台），命中即要求确认或拒绝。
- is_hard_blocked：系统级毁灭性操作（系统目录删除/全盘格式化）——**不可被
  autoconfirm 放行**，强制拦截。
- 确认开关：MENTALCORE_EXO_AUTOCONFIRM_RUN_CODE=1 时风险扫描命中仅告警放行；
  默认关闭 → 命中即拒（fail-closed）。
"""
from __future__ import annotations

import os

# 评测/无人值守场景放行开关：默认关，命中风险扫描即拒绝；显式开启才告警放行。
_AUTOCONFIRM = os.environ.get("MENTALCORE_EXO_AUTOCONFIRM_RUN_CODE") == "1"

# 系统级毁灭性操作硬阻断：此类风险即使开启 autoconfirm 也强制拦截
_SYSTEM_DIRS = ("c:\\windows", "c:\\program files", "c:\\programdata",
                "/windows", "/sys", "/boot")
_DESTRUCTIVE_KEYS = ("rm -rf", "rmdir /s", "del /f", "os.remove", "shutil.rmtree",
                     "remove-item", "format ", "mkfs", "diskpart")


def is_hard_blocked(code: str) -> bool:
    """系统目录删除/全盘格式化等不可放行的毁灭性操作。"""
    low = (code or "").lower()
    hits_system = any(d in low for d in _SYSTEM_DIRS)
    hits_destroy = any(k in low for k in _DESTRUCTIVE_KEYS)
    if hits_system and hits_destroy:
        return True
    if "rm -rf /" in low or "rm -rf ~" in low or "sudo rm -rf" in low:
        return True
    if "format " in low and ("c:" in low or "/dev/" in low):
        return True
    return False


def scan_code_risks(code: str) -> list[str]:
    """静态扫描高危模式，返回可读风险列表（空表=无明显风险）。"""
    low = (code or "").lower()
    risks: list[str] = []
    risks += _check_daemon_thread(low)
    risks += _check_destructive_delete(low)
    risks += _check_subproc_timeout(low)
    risks += _check_system_path_delete(low, code)
    risks += _check_detached_background(low, code)
    return risks


def _check_daemon_thread(low: str) -> list[str]:
    has_thread = ("thread(" in low or "threading" in low) and "daemon" in low
    if has_thread and ".join(" not in low:
        return ["代码使用 daemon 后台线程且主线程未 join()：进程退出时子线程被强杀，任务可能没执行完"]
    return []


def _check_destructive_delete(low: str) -> list[str]:
    destructive = any(k in low for k in
                      ("os.remove", "os.rmdir", "shutil.rmtree",
                       "remove-item", "rm -rf", "rmdir /s", "del /f"))
    if destructive:
        return ["代码包含删除操作：建议加 try 容错并二次确认路径，避免误删（已启用文件保险库可找回）"]
    return []


def _check_subproc_timeout(low: str) -> list[str]:
    has_subproc = any(k in low for k in
                      ("subprocess", "popen(", "os.system", "start-process"))
    if has_subproc and "timeout" not in low:
        return ["代码调用子进程但未设置超时：可能永久挂起，建议加 timeout"]
    return []


def _check_system_path_delete(low: str, code: str) -> list[str]:
    if ("c:\\users" in low and ("*" in code or "rm" in low)) or \
            ("c:\\windows" in low and "rm" in low):
        return ["代码包含硬编码系统路径删除：风险较高，请确认路径无误"]
    return []


def _check_detached_background(low: str, code: str) -> list[str]:
    shell_bg = (" & " in code) or code.rstrip().endswith(" &") \
        or ("start /b" in low) or ("nohup" in low)
    ps_bg = ("start-process" in low and "-wait" not in low)
    console_detach = ("create_new_console" in low or "detached_process" in low)
    popen_no_wait = ("popen(" in low) and ("communicate" not in low) and ("wait" not in low)
    if shell_bg or ps_bg or console_detach or popen_no_wait:
        return ["代码疑似把任务 detach 到后台（不等待结果）：run_code 会立即返回，对话无法闭环"]
    return []


def guard_code(code: str) -> str | None:
    """run_code 前置守卫：返回拒绝文案或 None（放行）。"""
    if is_hard_blocked(code):
        return ("拒绝：代码命中系统级毁灭性操作（系统目录删除/全盘格式化），"
                "不可放行（安全硬阻断）。")
    risks = scan_code_risks(code)
    if risks and not _AUTOCONFIRM:
        return (f"拒绝：代码风险扫描未通过（AUTOCONFIRM 未开启）。"
                f"风险提示：{risks[0][:120]}")
    return None

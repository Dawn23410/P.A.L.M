"""沙箱魔方（微内核之一）：隔离执行（安全责任二）。

对需在隔离环境运行的工具（shell/代码），在受限工作目录 + 超时下以 subprocess
执行，**fail-closed**：沙箱目录无法就绪即拒绝执行，绝不裸跑在宿主目录。

执行模式（exec_mode，Windows 下受限账户隔离）：
- legacy    : 当前用户权限执行（黑名单+敏感路径纵深）——默认，兼容性最佳
- restricted: 尝试受限 Token（禁用全部特权，CreateRestrictedToken）执行；
              不可用（非管理员/API 失败）即拒绝执行（fail-closed，不静默降级）
- deny      : 一律拒绝 shell 执行（超安全，只保留纯函数工具）

受限模式需要管理员特权（CreateRestrictedToken 要求 SeRestorePrivilege）；
在非管理员环境启用 restricted 会拒绝所有 shell 命令——这是刻意的 fail-closed，
不是 bug。生产加固建议：以管理员安装 Worker 服务 + restricted 模式。
"""
import os
import subprocess
import tempfile
import time
from pathlib import Path

try:
    import ctypes
    from ctypes import wintypes
    _CTYPES_OK = True
except ImportError:  # 非 Windows / 无 ctypes
    _CTYPES_OK = False


class SandboxError(RuntimeError):
    """沙箱不可用：拒绝执行（fail-closed）。"""


_DEFAULT_DENY = (
    "rm -rf /", "rm -rf /*", "format ", "mkfs", "del /s", "rm -rf ~",
    ":(){", "> /dev/sda", "dd if=",
)


def _normalize_cmd(cmd: str) -> str:
    """命令归一化（红蓝对抗 S6）：去不可见字符、折叠所有空白为单空格、小写。

    抵抗空格拆分（f o r m a t c : → format c:）、tab/零宽字符插入等绕过。
    """
    import re as _re
    # 去不可见/零宽字符
    cleaned = _re.sub(r"[\x00-\x1f\x7f\u200b-\u200f\ufeff]", "", cmd)
    # 折叠所有空白为单空格
    norm = _re.sub(r"\s+", " ", cleaned).strip().lower()
    return norm


# 各危险模式去掉空白后的形态（用于抵抗逐字母空格拆分 f o r m a t → format）
_DENY_NOSPACE = tuple("".join(p.split()) for p in _DEFAULT_DENY)

# 受限执行模式：可用性探测结果缓存（避免每命令重复探测）
_restricted_avail = None


def _restricted_token_available() -> bool:
    """探测 CreateRestrictedToken 是否可用（非管理员不可用，结果缓存）。"""
    global _restricted_avail
    if _restricted_avail is not None:
        return _restricted_avail
    token = _create_restricted_token()
    if token is None:
        _restricted_avail = False
    else:
        _close_handle(token)
        _restricted_avail = True
    return _restricted_avail


def _create_restricted_token():
    """CreateRestrictedToken：禁用当前进程 token 的全部特权（最大降权）。

    需要 SeRestorePrivilege（管理员）；失败返回 None（调用方 fail-closed）。
    """
    if not _CTYPES_OK:
        return None
    try:
        advapi32 = ctypes.windll.advapi32
        kernel32 = ctypes.windll.kernel32
        TOKEN_QUERY = 0x0008
        TOKEN_ADJUST_PRIVILEGES = 0x0020
        DISABLE_MAX_PRIVILEGE = 0x1
        token = wintypes.HANDLE()
        if not advapi32.OpenProcessToken(
                kernel32.GetCurrentProcess(),
                TOKEN_QUERY | TOKEN_ADJUST_PRIVILEGES, ctypes.byref(token)):
            return None
        restricted = wintypes.HANDLE()
        ok = advapi32.CreateRestrictedToken(
            token, DISABLE_MAX_PRIVILEGE, 0, None, 0, None, 0, None,
            ctypes.byref(restricted))
        _close_handle(token)
        return restricted if ok else None
    except (OSError, AttributeError):
        return None


def _close_handle(handle) -> None:
    try:
        ctypes.windll.kernel32.CloseHandle(handle)
    except (OSError, AttributeError):
        pass


def _run_restricted(command: str, cwd: str, timeout: float) -> str | None:
    """以受限 Token 执行命令，输出经临时文件捕获；失败返回 None。"""
    if not _CTYPES_OK:
        return None
    token = _create_restricted_token()
    if token is None:
        return None
    try:
        advapi32 = ctypes.windll.advapi32
        kernel32 = ctypes.windll.kernel32
        CREATE_NO_WINDOW = 0x08000000
        out_file = os.path.join(cwd, "_exo_restricted_out.txt")
        redirect = f' > "{out_file}" 2>&1'
        cmdline = command + redirect
        si = wintypes.STARTUPINFO()
        si.cb = ctypes.sizeof(si)
        pi = wintypes.PROCESS_INFORMATION()
        ok = advapi32.CreateProcessWithTokenW(
            token, 0, None, cmdline, 0, CREATE_NO_WINDOW, None, cwd,
            ctypes.byref(si), ctypes.byref(pi))
        if not ok:
            return None
        kernel32.CloseHandle(pi.hThread)
        ret = kernel32.WaitForSingleObject(pi.hProcess, int(timeout * 1000))
        if ret != 0:  # WAIT_TIMEOUT → 终止
            kernel32.TerminateProcess(pi.hProcess, 1)
            kernel32.CloseHandle(pi.hProcess)
            return f"受限执行超时（>{timeout}s），已终止"
        kernel32.CloseHandle(pi.hProcess)
        try:
            with open(out_file, "r", encoding="utf-8", errors="replace") as f:
                text = f.read().strip()
        except OSError:
            text = ""
        try:
            os.remove(out_file)
        except OSError:
            pass
        return text[:2000] or "（受限执行完成，无输出）"
    except (OSError, AttributeError):
        return None
    finally:
        _close_handle(token)


class SandboxCube:
    """沙箱魔方：在隔离目录执行危险工具；危险指令黑名单委托安全魔方。"""

    def __init__(self, sandbox_dir: str | None = None, security=None,
                 exec_mode: str = "legacy"):
        # 默认隔离在临时目录下的 exo_sandbox，与宿主文件系统解耦
        if sandbox_dir:
            self._dir = Path(sandbox_dir)
        else:
            self._dir = Path(tempfile.gettempdir()) / "exo_sandbox"
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise SandboxError(f"沙箱目录无法就绪：{exc}")
        self.security = security  # 委托安全魔方的危险指令黑名单（可空，空则用本地兜底）
        if exec_mode not in ("legacy", "restricted", "deny"):
            raise ValueError(f"非法 exec_mode：{exec_mode}")
        self.exec_mode = exec_mode

    @property
    def directory(self) -> str:
        return str(self._dir)

    def _refuse(self, cmd: str) -> str | None:
        """兜底危险指令拦截（隔离之外的纵深防御）。

        security 接线时委托其 refuse_command（GuardRail 基线正则，抗混淆）；
        未接线时本地 _DEFAULT_DENY 兜底：对命令做归一化（去不可见字符/折叠空白/小写）
        后再子串匹配，抵抗红队空格拆分（f o r m a t c :）等绕过。
        """
        if self.security is not None:
            return self.security.refuse_command(cmd)
        low = cmd.lower()
        norm = _normalize_cmd(cmd)
        nospace = norm.replace(" ", "")   # 抵抗逐字母空格拆分
        for pat, pat_ns in zip(_DEFAULT_DENY, _DENY_NOSPACE):
            if pat in low or pat in norm or pat_ns in nospace:
                return f"危险指令被沙箱拦截：命中 {pat!r}"
        return None

    def run(self, command: str, timeout: float = 15.0) -> str:
        """在沙箱内执行命令，返回观测文本（stdout/stderr 截断）。"""
        refuse = self._refuse(command)
        if refuse:
            return refuse
        if self.exec_mode == "deny":
            return "拒绝：沙箱执行模式为 deny（shell 执行已禁用）"
        if self.exec_mode == "restricted":
            if not _restricted_token_available():
                return ("拒绝：受限 Token 不可用（需管理员环境）。"
                        "沙箱执行模式为 restricted——不静默降级，已拒绝执行。")
            obs = _run_restricted(command, str(self._dir), timeout)
            if obs is not None:
                return obs
            return ("拒绝：受限 Token 执行失败（CreateProcessWithTokenW 不可用）。"
                    "已按 fail-closed 拒绝执行。")
        try:
            proc = subprocess.run(
                command, shell=True, cwd=str(self._dir),
                timeout=timeout, capture_output=True, text=True,
                # Windows 控制台默认 GBK：按 utf-8 硬解会抛 UnicodeDecodeError，
                # errors=replace 保证任何编码都不炸（输出可能乱码但可读）
                encoding="utf-8", errors="replace",
            )
        except subprocess.TimeoutExpired:
            return f"沙箱执行超时（>{timeout}s），已终止"
        except (OSError, ValueError) as exc:
            return f"沙箱执行失败：{exc}"
        out = (proc.stdout or "") + (proc.stderr or "")
        return out.strip()[:2000] or f"（无输出，退出码 {proc.returncode}）"

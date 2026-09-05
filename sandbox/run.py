"""受限账户 + Job Objects 隔离执行（Windows）。

目标：在独立无特权 Windows 账户下运行沙箱代码，Job Objects 限制 CPU/内存并整树强杀，
进程通过代理 env 出网（由 sandbox_net 拦截）。

依赖（可选）：pywin32。缺失或无管理员时优雅降级为「当前用户 + 超时 + 代理 env」，
网络拦截仍然生效（只是少了账户/资源隔离）。降级会在返回中标注 isolation="fallback"。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

SANDBOX_USER = os.environ.get("SANDBOX_USER", "sandbox_runner")


def _load_sandbox_pass() -> str:
    """沙箱账户口令：优先取环境变量 SANDBOX_USER_PASS；未设置则随机生成。

    不在源码中硬编码口令，避免凭据泄露与版本库污染（旧版行为）。
    """
    env = os.environ.get("SANDBOX_USER_PASS")
    if env:
        return env
    import secrets
    return secrets.token_urlsafe(18)


SANDBOX_USER_PASS = _load_sandbox_pass()
JOB_MEMORY_LIMIT = int(os.environ.get("SANDBOX_MEM_MB", "512")) * 1024 * 1024
JOB_CPU_RATE = int(os.environ.get("SANDBOX_CPU_PERCENT", "50"))  # 百分比


def _find_in_path(name: str, extra: list[str] | None = None) -> str | None:
    """在 PATH 和备用路径列表中查找可执行文件。"""
    found = shutil.which(name)
    if found:
        return found
    if extra:
        for p in extra:
            if os.path.isfile(p) and os.access(p, os.X_OK):
                return p
    return None


def _resolve_interp(lang: str) -> str | None:
    if lang == "python":
        env = os.environ.get("SANDBOX_PYTHON")
        if env:
            return env
        if sys.executable and "python" in os.path.basename(sys.executable).lower():
            return sys.executable
        return shutil.which("python3") or shutil.which("python")
    if lang == "node":
        return os.environ.get("SANDBOX_NODE") or shutil.which("node")
    if lang in ("bash", "sh"):
        env = os.environ.get("SANDBOX_BASH")
        if env:
            return env
        if lang == "bash":
            win_paths = [
                r"C:\Program Files\Git\bin\bash.exe",
                r"C:\Program Files\Git\usr\bin\bash.exe",
                r"C:\Windows\System32\bash.exe",
                r"C:\msys64\usr\bin\bash.exe",
            ]
            found = _find_in_path("bash", win_paths)
            if found:
                return found
            return _resolve_interp("sh")
        sh_extra = [
            r"C:\Program Files\Git\bin\sh.exe",
            r"C:\Program Files\Git\usr\bin\sh.exe",
            r"C:\Windows\System32\sh.exe",
            r"C:\msys64\usr\bin\sh.exe",
        ]
        return _find_in_path("sh", sh_extra)
    if lang in ("pwsh", "powershell"):
        env = os.environ.get("SANDBOX_PWSH") or os.environ.get("SANDBOX_POWERSHELL")
        if env:
            return env
        if lang == "pwsh":
            pwsh = _find_in_path("pwsh",
                [r"C:\Program Files\PowerShell\7\pwsh.exe"])
            if pwsh:
                return pwsh
            return _resolve_interp("powershell")
        win_ps = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
        return _find_in_path("powershell", [win_ps])
    # === 通用解释型语言（eval -c/-e 风格） ===
    # perl: perl -e 'code'
    # ruby: ruby -e 'code'
    # tclsh: tclsh -c 'code'
    # lua: lua -e 'code'
    # php: php -r 'code'
    if lang in ("perl", "ruby", "lua", "luajit"):
        env_var = os.environ.get("SANDBOX_%s" % lang.upper())
        if env_var:
            return env_var
        return shutil.which(lang)
    if lang == "tclsh":
        return os.environ.get("SANDBOX_TCLSH") or shutil.which("tclsh")
    # === 编译型语言（需写文件→编译→执行） ===
    # rustc: rustc -O -o out.rs && ./out
    if lang == "rust":
        return os.environ.get("SANDBOX_RUSTC") or shutil.which("rustc")
    return None


# 编译型语言配置: lang -> {suffix, compile_flags, exec_extra, env_var}
COMPILED_LANGS = {
    "rust": {
        "suffix": ".rs",
        "compile_flags": ["-O"],
        "exec_prefix": [],
        "env_var": "SANDBOX_RUSTC",
    },
}


# 需要 stdin 输入而非 -c 参数的语言（如该 tclsh 在 -c 模式下输出 % 提示符）
STDIN_LANGS = {"tclsh"}


def _interp_args(interp: str, lang: str, code: str) -> list[str] | None:
    if lang == "python":
        return [interp, "-c", code]
    if lang == "node":
        return [interp, "-e", code]
    if lang in ("bash", "sh"):
        return [interp, "-c", code]
    if lang in ("pwsh", "powershell"):
        return [interp, "-c", code]
    if lang in ("perl", "ruby"):
        return [interp, "-e", code]
    if lang in ("tclsh",):
        # tclsh 某些构建在 -c 模式下会输出 % 提示符；用 stdin 模式
        return ["_STDIN_"]  # 标记走 stdin 模式
    if lang in ("lua", "luajit"):
        return [interp, "-e", code]
    if lang == "php":
        return [interp, "-r", code]
    # 编译型语言
    if lang in COMPILED_LANGS:
        return None
    return None


def _run_stdin(interp: str, code: str, timeout: int, env: dict) -> dict:
    """通过 stdin 输入代码（适用于 tclsh 等 -c 会输出提示符的解释器）。"""
    try:
        proc = subprocess.run([interp], input=code, capture_output=True, text=True, timeout=timeout, env=env)
        return {"output": proc.stdout or "", "error": proc.stderr or "", "exitCode": proc.returncode}
    except subprocess.TimeoutExpired as e:
        return {"output": (e.stdout or ""), "error": (e.stderr or "") + "\n[超时]",
                "exitCode": None, "timeout": True}
    except Exception as e:
        return {"output": "", "error": "执行失败: %s" % e, "exitCode": None}


def _run_compiled(interp: str, lang: str, code: str, timeout: int, env: dict) -> dict:
    """编译型语言：写临时源文件 → 编译 → 执行 → 清理"""
    import tempfile
    from pathlib import Path
    cfg = COMPILED_LANGS.get(lang)
    if not cfg:
        return {"output": "", "error": "不支持的编译型语言: %s" % lang, "exitCode": 1}
    suffix = cfg["suffix"]
    src = tempfile.NamedTemporaryFile(suffix=suffix, delete=False, mode="w")
    src.write(code); src.close()
    outfile = src.name + ".exe" if os.name == "nt" else src.name + ".out"
    try:
        # 编译用真实 HOME（防止蜜罐 HOME 覆盖使 rustup 找不到 toolchain）
        real_home = str(Path.home())
        comp_env = dict(env)
        comp_env["HOME"] = real_home
        comp_env["USERPROFILE"] = real_home
        comp_env["RUSTUP_HOME"] = str(Path.home() / ".rustup")
        comp_env["CARGO_HOME"] = str(Path.home() / ".cargo")
        compile_cmd = [interp] + cfg["compile_flags"] + ["-o", outfile, src.name]
        comp = subprocess.run(compile_cmd, capture_output=True, text=True, timeout=timeout, env=comp_env)
        if comp.returncode != 0:
            return {"output": "", "error": "编译错误:\n%s" % comp.stderr, "exitCode": comp.returncode}
        if not os.path.isfile(outfile):
            return {"output": "", "error": "编译后未产生可执行文件", "exitCode": 1}
        # 执行
        exec_cmd = cfg.get("exec_prefix", []) + [outfile]
        exec_res = subprocess.run(exec_cmd, capture_output=True, text=True, timeout=timeout, env=comp_env)
        return {"output": exec_res.stdout, "error": exec_res.stderr, "exitCode": exec_res.returncode}
    except subprocess.TimeoutExpired:
        return {"output": "", "error": "[超时] 编译/执行超过 %ds" % timeout, "exitCode": None, "timeout": True}
    except Exception as e:
        return {"output": "", "error": "编译/执行失败: %s" % e, "exitCode": None}
    finally:
        for f in (src.name, outfile):
            try: os.unlink(f)
            except: pass


def _proxy_env(proxy_port: int) -> dict:
    p = "http://127.0.0.1:%d" % proxy_port
    env = dict(os.environ)
    env.update({
        "HTTP_PROXY": p, "HTTPS_PROXY": p, "ALL_PROXY": p,
        "http_proxy": p, "https_proxy": p, "all_proxy": p,
        "PIP_PROXY": p, "NO_PROXY": "", "no_proxy": "",
    })
    # 透传外部工作目录到沙箱子进程
    wd = os.environ.get("SANDBOX_WORK_DIR", "")
    if wd:
        env["SANDBOX_WORK_DIR"] = wd
    return env


# ----------------------------- 诱饵蜜罐注入 -----------------------------
def _inject_honeypot_env(env: dict, event_log: "Path | None" = None) -> dict:
    """部署高仿真诱饵文件，并向沙箱子进程环境注入拦截 shim。

    - 策略一/三/四 在解释器内（sitecustomize / NODE_OPTIONS --require）生效。
    - 策略二 由网络代理关联：shim 把读诱饵事件写入共享事件日志，
      web 进程的代理读取该日志判定「读诱饵 + 外联」。
    - 本函数仅在 sandbox 启动时（web.py --sandbox）经由 run_code_isolated 调用，
      不会污染 web.py 宿主进程（HONEYPOT_ACTIVE 仅注入子进程）。
    """
    try:
        from src.sandbox import honeypot as sandbox_honeypot
    except Exception:
        return env
    # 部署诱饵（幂等；每次运行刷新假内容，确保高仿真）
    try:
        sandbox_honeypot.deploy_decoys()
    except Exception:
        pass
    # 统一事件日志路径：子进程 shim 与 web 代理单例必须指向同一文件
    event_log = Path(event_log) if event_log else sandbox_honeypot.EVENT_LOG_DEFAULT
    try:
        sandbox_honeypot.set_event_log(event_log)
    except Exception:
        pass

    env = dict(env)
    env["HONEYPOT_ACTIVE"] = "1"
    env["HONEYPOT_EVENT_LOG"] = str(event_log)
    env["HONEYPOT_KILL"] = os.environ.get("HONEYPOT_KILL", "1")
    # ~ 解析到诱饵根：AI 代码访问 ~/.ssh/id_rsa 等命中策略
    env["HOME"] = str(sandbox_honeypot.DECOY_ROOT)
    env["USERPROFILE"] = str(sandbox_honeypot.DECOY_ROOT)
    # PYTHONPATH 前置 shim 目录 → 触发 sitecustomize 劫持内置 I/O
    shim_dir = str(sandbox_honeypot.HONEYPOT_SHIM_DIR)
    cur_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (shim_dir + os.pathsep + cur_pp) if cur_pp else shim_dir
    # NODE_OPTIONS=--require 注入 Node shim（路径转 forward slash 避免转义）
    node_shim = str(sandbox_honeypot.HONEYPOT_SHIM_DIR / "honeypot_node.js").replace("\\", "/")
    node_proxy = str(sandbox_honeypot.HONEYPOT_SHIM_DIR / "node_proxy_shim.js").replace("\\", "/")
    env["NODE_OPTIONS"] = "--require %s --require %s" % (node_shim, node_proxy)
    # win32 受限账户读权限兜底（best-effort，需管理员；无管理员时走 fallback 同用户）
    if os.name == "nt" and SANDBOX_USER:
        _win32_grant(SANDBOX_USER, [sandbox_honeypot.DECOY_ROOT,
                                    sandbox_honeypot.HONEYPOT_SHIM_DIR])
    return env


def _win32_grant(user: str, paths: list):
    """best-effort：给受限账户授予目录读/执行权限（icacls，需管理员）。"""
    if os.name != "nt" or not user:
        return
    for p in paths:
        try:
            subprocess.run(
                ["icacls", str(p), "/grant:r", "%s:(RX)" % user, "/inheritance:e"],
                capture_output=True, text=True, check=False,
            )
        except Exception:
            pass


def _win32_parts():
    try:
        import win32security  # noqa
        import win32job  # noqa
        import win32api  # noqa
        import win32con  # noqa
        return True
    except Exception:
        return False


def run_code_isolated(lang: str, code: str, timeout: int = 10,
                      proxy_port: int = 18100) -> dict:
    interp = _resolve_interp(lang)
    if not interp:
        return {"output": "", "error": "未找到 %s 解释器（请用 SANDBOX_%s 环境变量或安装对应运行时）" % (lang, lang.upper()),
                "exitCode": None, "missing": True, "isolation": "none"}
    args = _interp_args(interp, lang, code)
    env = _proxy_env(proxy_port)
    env = _inject_honeypot_env(env)

    # 编译型语言（args is None）走编译流水线
    if args is None and lang in COMPILED_LANGS:
        return _run_compiled(interp, lang, code, timeout, env)

    # stdin 模式（tclsh 等 -c 会输出提示符）
    if args and args[0] == "_STDIN_":
        return _run_stdin(interp, code, timeout, env)

    # 解释型语言（必须能构造 args）
    if args is None:
        return {"output": "", "error": "不支持的语言: %s" % lang, "exitCode": None,
                "missing": True, "isolation": "none"}

    if os.name == "nt":
        if _win32_parts():
            try:
                return _run_win32(args, env, timeout)
            except Exception as e:
                return _run_with_job(args, env, timeout, note="win32 降级: %s" % e)
        return _run_with_job(args, env, timeout)
    return _run_fallback(args, env, timeout, note="非 Windows，使用降级隔离")


# -------- Job Object 隔离（ctypes，无 pywin32 依赖） --------
def _run_with_job(args: list[str], env: dict, timeout: int, note: str = "") -> dict:
    """Windows: 使用 Job Object 绑定进程树，超时整树强杀。仅依赖 ctypes（标准库）。"""
    try:
        import ctypes; from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        JOB_KILL = 0x2000
        # JOBOBJECT_BASIC_LIMIT_INFORMATION 紧凑结构
        info = (wintypes.DWORD * 16)(0); info[2] = JOB_KILL
        hJob = k32.CreateJobObjectW(None, None)
        if hJob:
            k32.SetInformationJobObject(hJob, 1, ctypes.byref(info), ctypes.sizeof(info))
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                env=env, creationflags=subprocess.CREATE_NO_WINDOW)
        if hJob:
            hProc = k32.OpenProcess(0x1F0FFF, False, proc.pid)
            if hProc:
                k32.AssignProcessToJobObject(hJob, hProc); k32.CloseHandle(hProc)
        try:
            out, err = proc.communicate(timeout=timeout)
            return {"output": out.decode("utf-8","replace"), "error": err.decode("utf-8","replace"),
                    "exitCode": proc.returncode, "isolation": "jobobject", "note": note}
        except subprocess.TimeoutExpired:
            if hJob: k32.TerminateJobObject(hJob, 1)
            out, err = proc.communicate()
            return {"output": (out or b"").decode("utf-8","replace"),
                    "error": (err or b"").decode("utf-8","replace") + "\n[超时] Job 整树强杀",
                    "exitCode": None, "timeout": True, "isolation": "jobobject", "note": note}
        finally:
            if hJob: k32.CloseHandle(hJob)
    except Exception as e:
        return _run_fallback(args, env, timeout, note="JobObject 失败降级: %s" % e)


def _run_fallback(args: list[str], env: dict, timeout: int, note: str = "") -> dict:
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout, env=env)
        return {"output": proc.stdout or "", "error": proc.stderr or "",
                "exitCode": proc.returncode, "isolation": "fallback",
                "note": note}
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or "")
        err = (e.stderr or "") + ("\n[超时] 执行超过 %ds 被中止" % timeout)
        return {"output": out, "error": err, "exitCode": None,
                "timeout": True, "isolation": "fallback", "note": note}
    except Exception as e:  # noqa
        return {"output": "", "error": "执行失败：%s" % e, "exitCode": None,
                "isolation": "fallback", "note": note}


def _run_win32(args: list[str], env: dict, timeout: int) -> dict:
    """真实受限账户 + Job Objects 执行（需管理员 + pywin32）。"""
    import win32security
    import win32job
    import win32con
    import win32api
    import win32file
    import win32process

    # 1) 确保沙箱账户存在
    _ensure_user()

    # 2) 以受限令牌登录（网络登录，无桌面交互）
    token = win32security.LogonUser(
        SANDBOX_USER, ".", SANDBOX_USER_PASS,
        win32security.LOGON32_LOGON_NETWORK, win32security.LOGON32_PROVIDER_DEFAULT,
    )
    try:
        # 3) 创建 Job 对象并设资源上限
        job = win32job.CreateJobObject(None, "ai_chat_sandbox")
        ext = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
        ext["ProcessMemoryLimit"] = JOB_MEMORY_LIMIT
        ext["BasicLimitInformation"]["LimitFlags"] |= (
            win32job.JOB_OBJECT_LIMIT_PROCESS_MEMORY
            | win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            | win32job.JOB_OBJECT_LIMIT_BREAKAWAY_OK
        )
        win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, ext)
        if hasattr(win32job, "JobObjectCpuRateHardCapInformation"):
            try:
                cap = {"CpuRate": JOB_CPU_RATE * 100, "Weight": 0, "MaxRate": 0, "MinRate": 0}
                win32job.SetInformationJobObject(
                    job, win32job.JobObjectCpuRateHardCapInformation, cap)
            except Exception:
                pass

        # 4) 尝试 CreateProcessAsUser（可能因权限不足失败）
        import tempfile, win32file, win32process
        out_tmp, out_path = tempfile.mkstemp(".stdout", "sbox_")
        err_tmp, err_path = tempfile.mkstemp(".stderr", "sbox_")
        os.close(out_tmp); os.close(err_tmp)
        startup = win32process.STARTUPINFO()
        startup.dwFlags = win32con.STARTF_USESTDHANDLES
        startup.hStdOutput = win32file.CreateFile(
            out_path, win32con.GENERIC_WRITE, win32con.FILE_SHARE_READ, None,
            win32con.CREATE_ALWAYS, win32con.FILE_ATTRIBUTE_NORMAL, None)
        startup.hStdError = win32file.CreateFile(
            err_path, win32con.GENERIC_WRITE, win32con.FILE_SHARE_READ, None,
            win32con.CREATE_ALWAYS, win32con.FILE_ATTRIBUTE_NORMAL, None)
        try:
            hproc, ht, pid, tid = win32process.CreateProcessAsUser(
                token, None, " ".join(args), None, None, True,
                win32con.CREATE_SUSPENDED | win32process.CREATE_BREAKAWAY_FROM_JOB | win32con.CREATE_NO_WINDOW,
                env, None, startup,
            )
        except win32process.error as e:
            # 错误码 1314 = 特权不足
            if getattr(e, "winerror", None) == 1314 or "privilege" in str(e).lower():
                _print_privilege_hint()
            _clean_tmp(out_path, err_path)
            raise  # 外部 catch 降级到 _run_with_job
        if startup.hStdOutput: win32api.CloseHandle(startup.hStdOutput)
        if startup.hStdError: win32api.CloseHandle(startup.hStdError)
        win32job.AssignProcessToJobObject(job, hproc)
        win32process.ResumeThread(ht)

        # 5) 等待结束（带超时强杀整树）
        deadline = time.time() + timeout
        while time.time() < deadline:
            ec = win32process.GetExitCodeProcess(hproc)
            if ec != win32con.STILL_ACTIVE:
                break
            time.sleep(0.1)
        else:
            win32job.TerminateJobObject(job, 1)
            _clean_tmp(out_path, err_path)
            return {"output": "", "error": "[超时] 超过 %ds，Job 整树强杀" % timeout,
                    "exitCode": None, "timeout": True, "isolation": "jobobject+restricted",
                    "pid": pid}
        out, err = "", ""
        try:
            out = Path(out_path).read_text(encoding="utf-8", errors="replace")
            err = Path(err_path).read_text(encoding="utf-8", errors="replace")
        except Exception:
            pass
        _clean_tmp(out_path, err_path)
        return {"output": out, "error": err, "exitCode": ec,
                "isolation": "jobobject+restricted", "pid": pid}
    finally:
        try:
            token.Close()
        except Exception:
            pass


def _print_privilege_hint():
    """输出提权指引（非阻塞、非报错）。"""
    import platform
    user = os.environ.get("USERNAME", os.environ.get("USER", "当前用户"))
    hint = (
        "\n[提示] 受限账户隔离未完全启用（CreateProcessAsUser 需要 SeAssignPrimaryTokenPrivilege 特权）。\n"
        "       若要启用完全隔离（whoami 不再泄露用户名），请以管理员身份运行以下命令：\n\n"
        "         ntrights +r SeAssignPrimaryTokenPrivilege -u %s\n\n"
        "       或通过「本地安全策略」→「用户权限分配」→「替换进程级令牌」添加用户 %s。\n"
        "       ntrights 工具可从 Windows SDK 或以下链接获取：\n"
        "       https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/ntrights\n\n"
        "       当前已降级到 Job Object 隔离（网络拦截 + 超时强杀仍生效）。\n"
    ) % (user, user)
    print(hint)


def _clean_tmp(*paths):
    for p in paths:
        try:
            os.unlink(p)
        except Exception:
            pass


def _ensure_user():
    import win32net  # type: ignore
    import win32netcon  # type: ignore
    try:
        win32net.NetUserGetInfo(None, SANDBOX_USER, 0)
    except Exception:
        win32net.NetUserAdd(None, 1, {
            "name": SANDBOX_USER,
            "password": SANDBOX_USER_PASS,
            "priv": 1,  # USER_PRIV_USER
            "flags": win32netcon.UF_NORMAL_ACCOUNT | win32netcon.UF_PASSWD_CANT_CHANGE,
        })


def _collect_std(hproc, ht):
    # 简化：若需结构化捕获 stdout/stderr，调用方应改用临时文件。
    # 此处返回空，超时/退出码仍可用。完整重定向需创建可继承管道。
    return "", ""


def ensure_user_cli():
    """供 start.bat / 安装脚本调用：确保沙箱账户存在（需管理员）。"""
    if _win32_parts() and os.name == "nt":
        try:
            _ensure_user()
            return {"ok": True, "user": SANDBOX_USER}
        except Exception as e:  # noqa
            return {"ok": False, "error": str(e)}
    return {"ok": False, "error": "需要 Windows + pywin32 + 管理员"}

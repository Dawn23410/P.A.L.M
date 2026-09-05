"""AI 代码沙箱 WebUI 服务端（仅依赖标准库 + src.sandbox）。

运行：
    start_sandbox.bat               # 中文菜单启动
    python web.py --sandbox         # 手动启动，默认 127.0.0.1:8080
    python web.py --sandbox --port 9000

沙箱端点：
  GET  /api/run              -> {enabled}
  POST /api/run              -> 执行代码 {lang, code}
  GET  /api/net/policy       -> 黑白名单策略
  GET  /api/net/pending      -> 待审网络请求
  POST /api/net/decision     -> 裁决 {id, action}
  POST /api/net/quota        -> 配额设/查
  GET  /api/net/quota        -> 配额状态
  GET  /api/honeypot/audit   -> 审计统计
  GET  /api/honeypot/decoys  -> 诱饵清单
  POST /api/honeypot/deploy  -> 重新部署诱饵
  POST /api/honeypot/ack     -> 确认告警
  POST /api/net/threat       -> 威胁检测
  POST /api/sandbox/analyze  -> AST 预分析
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# 系统指标采集（纯标准库 + ctypes）；与 web.py 同目录，可直接 import
try:
    import sysmetrics
except Exception:  # 极端情况下降级，避免影响其它路由
    sysmetrics = None

HERE = Path(__file__).resolve().parent          # 脚本所在目录（项目根）
FRONTEND_DIR = HERE / "frontend"
SANDBOX_DIR = HERE / "sandbox_runtime"

# ============ sys.path：使 from src.sandbox 可导入 ============
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from src.sandbox import net as sandbox_net
from src.sandbox import ast as sandbox_ast
from src.sandbox import threat as sandbox_threat
from src.sandbox import run as sandbox_run
from src.sandbox import honeypot as sandbox_honeypot

# ============ 沙箱配置 ============
SANDBOX_ENABLED = False
SANDBOX_TIMEOUT = 10  # 单次执行最长时间（秒）
SANDBOX_PROXY_PORT = int(os.environ.get("SANDBOX_PROXY_PORT", "18100"))
SANDBOX_ISOLATE_USER = os.environ.get("SANDBOX_USER")  # 物理隔离账户（可选）

# 外部工作目录：单次设定，后续不可改
_WORK_DIR = os.environ.get("SANDBOX_WORK_DIR", "").strip()
_WORK_DIR_LOCKED = bool(_WORK_DIR)  # 如果启动时已设环境变量则直接锁定


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


def _resolve_interp(lang: str):
    if lang == "python":
        env = os.environ.get("SANDBOX_PYTHON")
        if env:
            return env
        if sys.executable and "python" in os.path.basename(sys.executable).lower():
            return sys.executable
        return shutil.which("python3") or shutil.which("python")
    if lang == "node":
        env = os.environ.get("SANDBOX_NODE")
        if env:
            return env
        return shutil.which("node")
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
    # 通用解释型语言
    if lang in ("perl", "ruby", "lua", "luajit"):
        env_var = os.environ.get("SANDBOX_%s" % lang.upper())
        if env_var:
            return env_var
        return shutil.which(lang)
    if lang == "tclsh":
        return os.environ.get("SANDBOX_TCLSH") or shutil.which("tclsh")
    if lang == "php":
        return os.environ.get("SANDBOX_PHP") or shutil.which("php")
    # 编译型语言
    if lang == "rust":
        return os.environ.get("SANDBOX_RUSTC") or shutil.which("rustc")
    return None


def _interp_args(interp: str, lang: str, code: str):
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
        return ["_STDIN_"]  # 标记 stdin 模式（某些 tclsh -c 输出提示符）
    if lang in ("lua", "luajit"):
        return [interp, "-e", code]
    if lang == "php":
        return [interp, "-r", code]
    # 编译型语言不支持
    if lang in ("rust",):
        return None
    return None


COMPILED_LANGS = {
    "rust": {"suffix": ".rs", "compile_flags": ["-O"]},
}


def _run_compiled(interp: str, lang: str, code: str, timeout: int) -> dict:
    """编译型语言：写临时源文件 → 编译 → 执行 → 清理"""
    import tempfile
    from pathlib import Path
    cfg = COMPILED_LANGS.get(lang)
    if not cfg:
        return {"output": "", "error": "不支持的编译型语言: %s" % lang, "exitCode": 1}
    src = tempfile.NamedTemporaryFile(suffix=cfg["suffix"], delete=False, mode="w")
    src.write(code); src.close()
    outfile = src.name + ".exe" if os.name == "nt" else src.name + ".out"
    try:
        # 编译用真实 HOME（防止 rustup 找不到 toolchain）
        real_home = str(Path.home())
        comp_env = dict(os.environ)
        comp_env["HOME"] = real_home
        comp_env["USERPROFILE"] = real_home
        comp_env["RUSTUP_HOME"] = str(Path.home() / ".rustup")
        comp_env["CARGO_HOME"] = str(Path.home() / ".cargo")
        compile_cmd = [interp] + cfg["compile_flags"] + ["-o", outfile, src.name]
        comp = subprocess.run(compile_cmd, capture_output=True, text=True, timeout=timeout, env=comp_env)
        if comp.returncode != 0:
            return {"output": "", "error": "编译错误:\n%s" % comp.stderr, "exitCode": comp.returncode}
        exec_res = subprocess.run([outfile], capture_output=True, text=True, timeout=timeout)
        return {"output": exec_res.stdout, "error": exec_res.stderr, "exitCode": exec_res.returncode}
    except subprocess.TimeoutExpired:
        return {"output": "", "error": "[超时] 编译/执行超过 %ds" % timeout, "exitCode": None, "timeout": True}
    except Exception as e:
        return {"output": "", "error": "编译/执行失败: %s" % e, "exitCode": None}
    finally:
        for f in (src.name, outfile):
            try: os.unlink(f)
            except: pass


def run_code_sandbox(lang: str, code: str, timeout: int = SANDBOX_TIMEOUT) -> dict:
    interp = _resolve_interp(lang)
    if not interp:
        return {"output": "", "error": "未找到 %s 解释器（请用 SANDBOX_%s 环境变量或 PATH 提供）"
                % (lang, lang.upper()), "exitCode": None, "missing": True}
    args = _interp_args(interp, lang, code)
    # 编译型语言（rust）走编译流水线
    if args is None and lang in ("rust",):
        return _run_compiled(interp, lang, code, timeout)
    if args is None:
        return {"output": "", "error": "不支持的语言 %s" % lang, "exitCode": None, "missing": True}
    try:
        stdin_data = None
        run_args = args
        if args and args[0] == "_STDIN_":
            # stdin 模式（tclsh）
            stdin_data = code
            run_args = [interp]
        proc = subprocess.run(run_args, capture_output=True, text=True, timeout=timeout,
                              input=stdin_data)
        return {"output": proc.stdout or "", "error": proc.stderr or "", "exitCode": proc.returncode}
    except subprocess.TimeoutExpired as e:
        return {"output": proc.stdout or "", "error": proc.stderr or "", "exitCode": proc.returncode}
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or "")
        err = (e.stderr or "") + ("\n[超时] 执行超过 %ds 被中止" % timeout)
        return {"output": out, "error": err, "exitCode": None, "timeout": True}
    except Exception as e:
        return {"output": "", "error": "执行失败：%s" % e, "exitCode": None}


# ============ HTTP 处理器 ============

MIME_MAP = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "SandboxHTTP/0.1"

    # ---- CORS ----
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Max-Age", "86400")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    # ---- 工具 ----
    def _send_json(self, obj: dict, status: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_err(self, code: str, status: int = 0, extra: str = "") -> None:
        """发送统一错误响应。"""
        from src.sandbox import err_resp
        resp = err_resp(code, extra)
        if status:
            resp["errno"] = status
        self._send_json(resp, resp["errno"])

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def _serve_static(self, url_path: str) -> bool:
        """尝试提供 frontend/ 下的静态文件；返回 True 表示已处理。"""
        # 只允许安全的路径（禁止 .. 逃逸）
        clean = urllib.parse.unquote(url_path.split("?")[0].split("#")[0]).lstrip("/")
        if ".." in clean or "~" in clean:
            return False
        # 映射到 frontend/ 目录
        fpath = FRONTEND_DIR / clean
        # 若直接请求目录，尝试 index.html
        if fpath.is_dir():
            fpath = fpath / "index.html"
        if not fpath.is_file():
            return False
        ext = fpath.suffix.lower()
        ctype = MIME_MAP.get(ext) or mimetypes.guess_type(str(fpath))[0] or "application/octet-stream"
        if "text" in ctype or "javascript" in ctype:
            ctype += "; charset=utf-8" if "charset" not in ctype else ""
        try:
            data = fpath.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return True
        except Exception:
            return False

    # ---- GET ----
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path.rstrip("/") or "/"

        # ====== 沙箱状态 ======
        if path == "/api/run":
            return self._send_json({"enabled": SANDBOX_ENABLED})

        # ====== 控制台终端：项目上下文执行（探测） ======
        if path == "/api/console/exec":
            return self._send_json({"enabled": True})

        # ====== 控制台：系统指标 / 模块状态 ======
        if path == "/api/metrics":
            if sysmetrics is None:
                return self._send_err("METRICS_UNAVAILABLE")
            return self._send_json(sysmetrics.collect_metrics())

        if path == "/api/modules":
            if sysmetrics is None:
                return self._send_err("MODULES_UNAVAILABLE")
            return self._send_json(sysmetrics.collect_modules(SANDBOX_ENABLED))

        # ====== 网络策略 ======
        if path == "/api/net/policy":
            if not SANDBOX_ENABLED:
                return self._send_err("SANDBOX_DISABLED")
            itc = sandbox_net.get_interceptor()
            if not itc:
                return self._send_err("INTERNAL_ERROR", extra="interceptor not started")
            return self._send_json(itc.policy.snapshot())

        if path == "/api/net/pending":
            if not SANDBOX_ENABLED:
                return self._send_err("SANDBOX_DISABLED")
            itc = sandbox_net.get_interceptor()
            if not itc:
                return self._send_err("INTERNAL_ERROR", extra="interceptor not started")
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            since = 0
            try:
                since = int((qs.get("since") or [0])[0])
            except (ValueError, TypeError):
                pass
            return self._send_json(itc.list_pending(since=since))

        if path == "/api/net/quota":
            if not SANDBOX_ENABLED:
                return self._send_err("SANDBOX_DISABLED")
            itc = sandbox_net.get_interceptor()
            if not itc:
                return self._send_err("INTERNAL_ERROR", extra="interceptor not started")
            return self._send_json(itc.status())

        # ====== 蜜罐审计 ======
        if path == "/api/honeypot/audit":
            if not SANDBOX_ENABLED:
                return self._send_err("SANDBOX_DISABLED")
            return self._send_json(sandbox_honeypot.get_honeypot().get_audit())

        if path == "/api/honeypot/decoys":
            if not SANDBOX_ENABLED:
                return self._send_err("SANDBOX_DISABLED")
            return self._send_json({
                "decoy_root": str(sandbox_honeypot.DECOY_ROOT),
                "event_log": str(sandbox_honeypot.EVENT_LOG_DEFAULT),
                "decoys": sandbox_honeypot.list_decoys(),
            })

        # ====== 工作目录 ======
        if path == "/api/workdir":
            global _WORK_DIR, _WORK_DIR_LOCKED
            return self._send_json({
                "work_dir": _WORK_DIR or None,
                "locked": bool(_WORK_DIR_LOCKED),
            })

        # ====== 静态文件 ======
        if self._serve_static(self.path):
            return

        self._send_err("NOT_FOUND", extra=path)

    # ---- POST ----
    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path.rstrip("/") or "/"
        try:
            body = self._read_body()
        except Exception:
            return self._send_err("BAD_REQUEST", extra="invalid JSON")

        # ====== 代码执行 ======
        if path == "/api/run":
            if not SANDBOX_ENABLED:
                return self._send_err("SANDBOX_DISABLED")
            lang = body.get("lang", "python")
            code = body.get("code", "")
            toastr = body.get("toastr", True)
            timeout = body.get("timeout", SANDBOX_TIMEOUT)
            result = sandbox_run.run_code_isolated(
                lang, code, timeout=timeout, proxy_port=SANDBOX_PROXY_PORT,
            )
            # 若 run_code_isolated 因降级返回空，回退到简单的 subprocess.run
            if not result.get("output") and not result.get("error"):
                result = run_code_sandbox(lang, code, timeout=timeout)
            if toastr and result.get("exitCode") is None:
                result.setdefault("error", "")
                result["error"] += "\n[提示] 沙箱降级为当前用户+超时模式（网络拦截仍生效）"
            return self._send_json(result)

        # ====== 控制台终端：项目上下文执行（轻量，不触发网络拦截/防火墙） ======
        if path == "/api/console/exec":
            lang = body.get("lang", "python")
            code = body.get("code", "")
            if not code.strip():
                return self._send_json({"output": "", "error": "空命令", "exitCode": 1})
            try:
                timeout = int(body.get("timeout", 30))
            except (TypeError, ValueError):
                timeout = 30
            result = run_code_sandbox(lang, code, timeout=timeout)
            return self._send_json(result)

        # ====== 网络裁决 ======
        if path == "/api/net/decision":
            if not SANDBOX_ENABLED:
                return self._send_err("SANDBOX_DISABLED")
            itc = sandbox_net.get_interceptor()
            if not itc:
                return self._send_err("INTERNAL_ERROR", extra="interceptor not started")
            req_id = body.get("id")
            action = body.get("action")
            if not req_id or action not in ("allow_once", "allow_session", "deny_permanent"):
                return self._send_err("BAD_REQUEST", extra="invalid id or action")
            result = itc.decide(req_id, action)
            return self._send_json({"ok": result, "id": req_id, "action": action})

        # ====== 配额设置 ======
        if path == "/api/net/quota":
            if not SANDBOX_ENABLED:
                return self._send_err("SANDBOX_DISABLED")
            itc = sandbox_net.get_interceptor()
            if not itc:
                return self._send_err("INTERNAL_ERROR", extra="interceptor not started")
            max_bytes = body.get("max_bytes")
            if max_bytes is not None:
                itc.quota.set_max(int(max_bytes))
            if body.get("reset"):
                itc.quota.reset()
            return self._send_json(itc.status())

        # ====== 威胁检测 ======
        if path == "/api/net/threat":
            if not SANDBOX_ENABLED:
                return self._send_err("SANDBOX_DISABLED")
            host = body.get("host", "")
            ip = body.get("ip", "")
            result = sandbox_threat.check(host, ip)
            return self._send_json(result)

        # ====== AST 预分析 ======
        if path == "/api/sandbox/analyze":
            if not SANDBOX_ENABLED:
                return self._send_err("SANDBOX_DISABLED")
            lang = body.get("lang", "python")
            code = body.get("code", "")
            result = sandbox_ast.analyze(lang, code)
            return self._send_json(result)

        # ====== 蜜罐 ======
        if path == "/api/honeypot/deploy":
            if not SANDBOX_ENABLED:
                return self._send_err("SANDBOX_DISABLED")
            counts = sandbox_honeypot.deploy_decoys()
            return self._send_json({"ok": True, "files": counts.get("files", 0)})

        if path == "/api/honeypot/ack":
            if not SANDBOX_ENABLED:
                return self._send_err("SANDBOX_DISABLED")
            event_id = body.get("event_id")
            action = body.get("action", "kill")
            hp = sandbox_honeypot.get_honeypot()
            if action == "kill":
                itc2 = sandbox_net.get_interceptor()
                detail = hp.acknowledge(event_id)
                if itc2 and (ip := detail.get("target_ip")):
                    itc2.policy.deny_permanent.add(ip)
                    itc2.policy.save_deny()
                return self._send_json({"ok": True, "action": "kill+deny" if itc2 else "kill"})
            return self._send_json({"ok": True, "action": "ignore"})

        # ====== 工作目录（单次设定）======
        if path == "/api/workdir":
            global _WORK_DIR, _WORK_DIR_LOCKED
            if _WORK_DIR_LOCKED:
                return self._send_err("BAD_REQUEST", extra="workdir already locked")
            new_dir = (body.get("path") or "").strip()
            if not new_dir:
                return self._send_err("BAD_REQUEST", extra="path is empty")
            if not os.path.isdir(new_dir):
                try:
                    os.makedirs(new_dir, exist_ok=True)
                except Exception as e:
                    return self._send_err("BAD_REQUEST", extra="cannot create dir: %s" % e)
            _WORK_DIR = os.path.abspath(new_dir)
            os.environ["SANDBOX_WORK_DIR"] = _WORK_DIR
            _WORK_DIR_LOCKED = True
            return self._send_json({"ok": True, "work_dir": _WORK_DIR, "locked": True})

        # ====== 网络急救 (Feature 7) ======
        if path == "/api/net/emergency":
            return self._handle_emergency()

        # ====== 裁决引擎明文测试 ======
        if path == "/api/net/verdict":
            if not SANDBOX_ENABLED:
                return self._send_err("SANDBOX_DISABLED")
            required = ("target_ip", "port", "method")
            missing = [k for k in required if k not in body]
            if missing:
                return self._send_err("BAD_REQUEST", extra="missing: " + ", ".join(missing))
            v = sandbox_net._net_verdict(
                target_ip=body["target_ip"],
                port=body["port"],
                method=body.get("method", "GET"),
                path=body.get("path", ""),
                body_preview=body.get("body_preview", ""),
                is_private_ip=body.get("is_private_ip", False),
                rate=body.get("request_rate_per_minute", 0),
            )
            return self._send_json(v)

        self._send_err("NOT_FOUND", extra=path)

    # ---- 网络急救（Feature 7） ----
    def _handle_emergency(self) -> dict:
        """一键网络急救：DNS 刷新 + 网络重置 + 生成手机求助 Prompt。"""
        import subprocess, platform, datetime
        os_name = platform.system()
        commands_run = []
        errors = []
        # DNS 刷新
        try:
            if os_name == "Windows":
                subprocess.run("ipconfig /flushdns", shell=True, capture_output=True, timeout=15)
                commands_run.append("ipconfig /flushdns")
                subprocess.run("netsh int ip reset", shell=True, capture_output=True, timeout=30)
                commands_run.append("netsh int ip reset")
            elif os_name == "Linux":
                subprocess.run(["resolvectl", "flush-caches"], capture_output=True, timeout=15)
                commands_run.append("resolvectl flush-caches")
                try:
                    subprocess.run(["systemctl", "restart", "NetworkManager"],
                                   capture_output=True, timeout=30)
                    commands_run.append("systemctl restart NetworkManager")
                except Exception:
                    errors.append("NetworkManager 重启失败（可能需要 sudo）")
            elif os_name == "Darwin":
                subprocess.run(["dscacheutil", "-flushcache"], capture_output=True, timeout=15)
                commands_run.append("dscacheutil -flushcache")
                subprocess.run(["killall", "-HUP", "mDNSResponder"], capture_output=True, timeout=15)
                commands_run.append("killall -HUP mDNSResponder")
        except Exception as e:
            errors.append("网络重置失败: %s" % e)

        # 读取最近日志
        recent_logs = []
        try:
            log_dir = SANDBOX_DIR
            log_files = sorted(log_dir.glob("*.log"), key=os.path.getmtime, reverse=True)[:3]
            for lf in log_files:
                try:
                    content = lf.read_text(encoding="utf-8", errors="replace")[-2000:]
                    recent_logs.append("[%s]\n%s" % (lf.name, content))
                except Exception:
                    pass
        except Exception:
            pass

        # 生成 crash report
        crash = {
            "timestamp": datetime.datetime.now().isoformat(),
            "os": os_name,
            "host": platform.node(),
            "commands_executed": commands_run,
            "errors": errors,
            "recent_logs": recent_logs,
        }
        try:
            report_path = SANDBOX_DIR / "crash_report.txt"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                "=== Sandbox Crash Report ===\n"
                "Time: %(timestamp)s\n"
                "OS: %(os)s\n"
                "Host: %(host)s\n\n"
                "Commands Executed:\n  %(commands)s\n\n"
                "Errors:\n  %(errors)s\n\n"
                "Recent Logs:\n%(logs)s\n" % {
                    "timestamp": crash["timestamp"],
                    "os": crash["os"],
                    "host": crash["host"],
                    "commands": "\n  ".join(crash["commands_executed"]),
                    "errors": "\n  ".join(crash["errors"]) if crash["errors"] else "(none)",
                    "logs": "\n---\n".join(crash["recent_logs"]) if crash["recent_logs"] else "(none)",
                }
            )
        except Exception:
            pass

        # 生成手机求助 Prompt
        prompt = (
            "我是电脑 AI 助手，网络连接出现问题，已尝试以下操作：\n"
            + "\n".join("  - " + c for c in commands_run)
            + "\n\n"
            + ("错误信息：\n" + "\n".join("  - " + e for e in errors) + "\n\n" if errors else "")
            + "当前状态：\n"
            + "  - 操作系统：%s\n" % os_name
            + "  - 主机名：%s\n" % platform.node()
            + "  - 已执行 DNS 刷新和网络重置\n"
            + ("  - 最后日志见：crash_report.txt\n" if recent_logs else "")
            + "\n请帮我继续诊断网络问题。谢谢！"
        )

        return self._send_json({
            "ok": True,
            "commands_run": commands_run,
            "errors": errors,
            "prompt": prompt,
            "crash_report": str(report_path) if 'report_path' in dir() else None,
        })

    def log_message(self, fmt, *args):
        """抑制默认日志（改用 print 精简输出）。"""
        if args and "OPTIONS" in args[0]:
            return  # 不打印 OPTIONS 预检
        print("[%s] %s" % (self.client_address[0], fmt % args))


# ============ 入口 ============

def main():
    global SANDBOX_ENABLED
    ap = argparse.ArgumentParser(description="AI 代码沙箱服务")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--sandbox", action="store_true", help="启用代码沙箱 + 网络拦截")
    args = ap.parse_args()

    SANDBOX_ENABLED = bool(args.sandbox) or (os.environ.get("ENABLE_SANDBOX") == "1")

    if SANDBOX_ENABLED:
        print("🔒 沙箱模式已启用")
        # 检测管理员模式是否可完整启用（CreateProcessAsUser 需要 SeAssignPrimaryTokenPrivilege）
        force_global = False
        if SANDBOX_ISOLATE_USER:
            try:
                import ctypes
                is_admin = ctypes.windll.shell32.IsUserAnAdmin()
                if is_admin:
                    from src.sandbox.run import _win32_parts
                    if _win32_parts():
                        # 快速测试 CreateProcessAsUser 是否可用
                        import win32security, win32con
                        try:
                            tok = win32security.OpenProcessToken(
                                ctypes.windll.kernel32.GetCurrentProcess(),
                                win32con.TOKEN_DUPLICATE | win32con.TOKEN_QUERY)
                            tok.Close()
                        except Exception:
                            force_global = True
                    else:
                        force_global = True  # 无 pywin32 → _run_with_job → 防火墙应全局
                else:
                    force_global = True  # 非管理员 → _run_with_job
            except Exception:
                force_global = True
        itc = sandbox_net.start_interceptor(SANDBOX_PROXY_PORT, sandbox_net.DEFAULT_QUOTA,
                                            SANDBOX_ISOLATE_USER, force_global_fw=force_global)
        print("🔒 透明网络拦截代理已启动：127.0.0.1:%d（默认断网，需用户授权）" % SANDBOX_PROXY_PORT)
        if itc and itc.firewall is not None:
            fw = itc.fw_status or {}
            if fw.get("applied"):
                mode = "全局规则" if fw.get("global") else ("用户规则: " + fw.get("user", "?"))
                print("   🛡️  防火墙已应用：%s" % mode)
            else:
                print("   [提示] 防火墙未生效：%s（代理拦截仍工作）" % fw.get("reason", "unknown"))
        sandbox_honeypot.set_event_log(sandbox_honeypot.EVENT_LOG_DEFAULT)
        sandbox_honeypot.get_honeypot(sandbox_honeypot.EVENT_LOG_DEFAULT)
        counts = sandbox_honeypot.deploy_decoys()
        print("  🍯 %s 个诱饵已部署 @ %s" % (counts.get("files", 0), sandbox_honeypot.DECOY_ROOT))
    else:
        print("⚠️  沙箱模式未启用。使用 --sandbox 启用代码执行。")

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print("沙箱服务已启动：http://%s:%d" % (args.host, args.port))
    print("管理面板：http://%s:%d/sandbox_panel.html" % (args.host, args.port))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止。")
        if SANDBOX_ENABLED:
            itc = sandbox_net.get_interceptor()
            if itc:
                itc.stop()
        server.server_close()


if __name__ == "__main__":
    main()

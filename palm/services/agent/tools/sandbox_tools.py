"""沙箱工具 —— 代码执行器（调用 AI 代码沙箱引擎）。"""
from __future__ import annotations

import base64
import logging
import os
import shlex
import socket
import subprocess
import tempfile
import threading

from palm._core.config import settings
from palm._core.container import registry
from ..tool_base import Tool, ToolSpec, agent_conversation_id, agent_model, agent_is_wakeup
from palm._core.interop import get_evolution_api

_LOGGER = logging.getLogger(__name__)

# 沙箱执行串行锁：SANDBOX_WORK_DIR 是进程级环境变量，并发执行会互相覆盖
_SANDBOX_LOCK = threading.Lock()
# 输出大小硬限制（50KB），防止巨量输出撑爆 LLM 上下文
_MAX_OUTPUT_CHARS = 50000

# 延迟导入沙箱引擎（避免启动时加载过重）
_sandbox_run = None
_sandbox_net = None
_sandbox_honeypot = None


def _ensure_sandbox():
    """惰性加载沙箱引擎模块（经沙箱砖 capabilities 取用）。"""
    global _sandbox_run, _sandbox_net, _sandbox_honeypot
    if _sandbox_run is not None:
        return
    brick = container.get("sandbox")
    engine_fn = brick.capabilities.get("sandbox_engine") if brick else None
    if engine_fn is None:
        _LOGGER.warning("沙箱砖未注册或引擎能力缺失")
        return
    try:
        mods = engine_fn()
        _sandbox_run = mods["run"]
        _sandbox_net = mods["net"]
        _sandbox_honeypot = mods["honeypot"]
    except ImportError as exc:
        _LOGGER.warning("沙箱引擎不可用: %s", exc)


def _restore_module():
    """惰性取沙箱砖还原点模块；砖/能力缺失时返回 None（铁律：缺失降级）。"""
    brick = container.get("sandbox")
    restore_fn = brick.capabilities.get("restore_point") if brick else None
    return restore_fn() if restore_fn else None


class RunCodeTool(Tool):
    """在隔离沙箱中执行代码，支持 Python / Node / Bash / PowerShell / cmd。"""
    _detect_cache: dict = {}
    _last_artifacts: list = []

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="run_code",
            permission="sandbox.run_code",
            description="在安全沙箱中执行代码。支持 python / node / bash / pwsh / cmd。返回执行结果（输出/错误/退出码）。\n\n提示：GUI 命令如 `start msedge`、`start notepad`、`explorer C:\\Users` 等无 stdout 输出是正常的，退出码 0 即视为成功。如需查看运行结果，调用 `take_screenshot` 截图。\n\n生成图片或文件：请保存到环境变量 `SANDBOX_WORK_DIR` 指向的目录（如 `os.environ.get('SANDBOX_WORK_DIR', '.')`），执行后系统会自动把新增图片回传展示给用户。",
            parameters={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "要执行的完整代码内容",
                    },
                    "language": {
                        "type": "string",
                        "enum": ["auto", "python", "node", "bash", "pwsh", "cmd"],
                        "description": "代码语言，auto 表示自动检测",
                        "default": "auto",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "执行超时秒数",
                        "default": 15,
                    },
                    "need_elevation": {
                        "type": "boolean",
                        "description": "是否请求以当前用户身份提权执行（绕过沙箱隔离账户，获得当前用户权限）。"
                                      "启用后会弹出授权确认，需用户亲自同意才会真正提权；默认 False（隔离执行）。",
                        "default": False,
                    },
                },
                "required": ["code"],
            },
            event_type="process.execute",
        )

    async def execute(self, code: str, language: str = "auto", timeout: int = 15,
                      need_elevation: bool = False) -> str:
        # 离线护栏：离线模式下禁止代码中的外网访问（沙箱子进程不走 httpx 拦截）
        from palm._core.gateway import is_offline
        if is_offline():
            _net_hints = ("http://", "https://", "curl", "wget", "requests",
                          "urllib", "socket", "ftp", "smtp", "aiohttp",
                          "httpx", "fetch(", "invoke-webrequest", "invoke-restmethod")
            if any(h in code.lower() for h in _net_hints):
                return "离线模式已开启：禁止代码执行中的外网访问（检测到网络操作）。本地计算/文件处理不受影响，请去掉网络相关代码后重试。"
        _ensure_sandbox()
        if _sandbox_run is None:
            return "沙箱引擎不可用，请确认已正确安装 sandbox 模块"

        # 语言自动检测
        lang = language
        if lang == "auto":
            lang = self._detect_lang(code)

        # 产物目录：沙箱子进程 cwd 指向它，执行后扫描新增图片回传前端
        artifacts_dir = self._prepare_artifacts_dir()
        before = self._snapshot_images(artifacts_dir)

        # 串行执行：SANDBOX_WORK_DIR 是进程级环境变量，并发会互相覆盖
        import asyncio
        async with asyncio.Lock():
            result = await asyncio.to_thread(
                self._run_in_sandbox_locked, lang, code, timeout, artifacts_dir, need_elevation)

        self._last_artifacts = self._collect_artifacts(artifacts_dir, before)
        return self._format_result(result, lang)

    def _detect_lang(self, code: str) -> str:
        """启发式语言检测。"""
        code_stripped = code.strip()
        if not code_stripped:
            return "python"
        lines = code_stripped.splitlines()
        first = lines[0].strip() if lines else ""

        if first.startswith(("#!/usr/bin/env python", "#!/usr/bin/python")):
            return "python"
        if first.startswith(("#!/usr/bin/env node", "#!/usr/bin/node")):
            return "node"
        if first.startswith(("#!/bin/bash", "#!/usr/bin/bash")):
            return "bash"
        if first.startswith("#!/usr/bin/pwsh"):
            return "pwsh"

        py = {"def ", "class ", "import ", "print(", "if __name__", "  "}
        node = {"console.log", "require(", "module.exports", "=>", "process."}
        pwsh = {"Write-Host", "Get-", "Set-", "$"}
        cmd = {"@echo off", "echo ", "setlocal", "chcp"}
        bash = {"export ", "source ", "function ", "fi", "done"}

        score = {"python": 0, "node": 0, "bash": 0, "pwsh": 0, "cmd": 0}
        for line in lines:
            s = line.strip()
            for sig in py:
                if sig in s: score["python"] += 1
            for sig in node:
                if sig in s: score["node"] += 1
            for sig in pwsh:
                if sig.lower() in s.lower(): score["pwsh"] += 1
            for sig in cmd:
                if sig.lower() in s.lower(): score["cmd"] += 1
            for sig in bash:
                if sig in s: score["bash"] += 1

        best = max(score, key=score.get)
        return best if score[best] >= 2 else "python"

    def _run_in_sandbox(self, lang: str, code: str, timeout: int, artifacts_dir: str,
                        elevation: bool = False) -> dict:
        """在沙箱中同步执行代码。"""
        # 分配临时端口供网络拦截器使用
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            proxy_port = s.getsockname()[1]

        interceptor = None
        try:
            # 启动网络拦截
            if _sandbox_net:
                interceptor = _sandbox_net.NetInterceptor(port=proxy_port)
                interceptor.start()
            if _sandbox_honeypot:
                _sandbox_honeypot.deploy_decoys()

            # 执行（cwd 指向产物目录，便于模型把图片 savefig 到这里）
            exec_result = _sandbox_run.run_code_isolated(
                lang=lang, code=code, timeout=timeout,
                proxy_port=proxy_port, work_dir=artifacts_dir,
                elevation=elevation,
            )
            return {
                "ok": True,
                "output": exec_result.get("output", ""),
                "error": exec_result.get("error", ""),
                "exit_code": exec_result.get("exitCode"),
                "isolation": exec_result.get("isolation", "none"),
                "timeout": exec_result.get("timeout", False),
            }
        except Exception as exc:
            _LOGGER.error("沙箱执行异常: %s", exc)
            return {"ok": False, "error": str(exc)}
        finally:
            if interceptor:
                interceptor.stop()

    def _run_in_sandbox_locked(self, lang: str, code: str, timeout: int,
                               artifacts_dir: str, elevation: bool = False) -> dict:
        """串行包装：在 threading.Lock 内设置 SANDBOX_WORK_DIR 并执行沙箱。"""
        with _SANDBOX_LOCK:
            os.environ["SANDBOX_WORK_DIR"] = artifacts_dir
            return self._run_in_sandbox(lang, code, timeout, artifacts_dir, elevation)

    def _format_result(self, result: dict, lang: str) -> str:
        """把沙箱原始执行结果透传给 AI：stderr/stdout 原样返回，超出 50KB 硬截断。"""
        output = result.get("output", "") or ""
        error = result.get("error", "") or ""
        # 输出大小硬限制：防止巨量输出（如 cat 大文件）撑爆 LLM 上下文
        if len(output) > _MAX_OUTPUT_CHARS:
            output = output[:_MAX_OUTPUT_CHARS] + f"\n…[输出截断，共 {len(output)} 字符，已截取前 {_MAX_OUTPUT_CHARS} 字符]"
        if len(error) > _MAX_OUTPUT_CHARS:
            error = error[:_MAX_OUTPUT_CHARS] + f"\n…[错误截断，共 {len(error)} 字符，已截取前 {_MAX_OUTPUT_CHARS} 字符]"
        exit_code = result.get("exit_code")
        is_timeout = result.get("timeout", False)
        missing = result.get("missing", False)

        if missing:
            return f"语言={lang} 解释器不可用（仅支持 python/node/系统 shell）。原始信息: {error}"
        if not result.get("ok", True):
            return f"语言={lang} 执行异常: {error}"

        # 单行元数据仅用于判断成败，不喧宾夺主
        meta = f"[语言 {lang} | 退出码 {exit_code}{' | 超时' if is_timeout else ''}]"
        parts = [meta]
        if error:
            parts.append("— stderr（原始报错）—")
            parts.append(error)  # 原始报错，完整透传
        if output:
            parts.append("— stdout（原始输出）—")
            parts.append(output)  # 原始输出，完整透传
        if not error and not output:
            parts.append("（无输出）")
        return "\n".join(parts)

    # ---- 产物（图片）收集：执行后扫描 SANDBOX_WORK_DIR 新增图片，回传前端 ----
    _IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg"}
    _IMAGE_MIME = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
        ".svg": "image/svg+xml",
    }

    def _prepare_artifacts_dir(self) -> str:
        """准备专用产物目录（位于存储池下），沙箱子进程 cwd 指向它。"""
        d = os.path.join(settings.STORAGE_POOL_DIR, "agent_artifacts")
        os.makedirs(d, exist_ok=True)
        return d

    def _snapshot_images(self, d: str) -> set:
        """记录目录当前已有图片文件名，供执行后比对新增。"""
        if not os.path.isdir(d):
            return set()
        return {f for f in os.listdir(d)
                if os.path.splitext(f)[1].lower() in self._IMAGE_EXTS}

    def _index_artifact(self, filename: str, disk_path: str) -> None:
        # 把已落盘的产物登记进存储池索引，使其可被统计/删除/GC 追踪，避免成为无索引孤儿。
        brick = container.get("storage")
        if not brick:
            return
        fn = (getattr(brick, "capabilities", {}) or {}).get("index_existing_file")
        if not callable(fn):
            return
        try:
            fn("agent_artifacts", filename, disk_path)
        except Exception:  # noqa: BLE001
            pass

    def _collect_artifacts(self, d: str, before: set) -> list:
        """扫描执行后新增的图片，转 base64 回传（限大小与数量）。"""
        items: list = []
        if not os.path.isdir(d):
            return items
        for f in sorted(os.listdir(d)):
            ext = os.path.splitext(f)[1].lower()
            if ext not in self._IMAGE_EXTS or f in before:
                continue
            path = os.path.join(d, f)
            try:
                if os.path.getsize(path) > 5 * 1024 * 1024:
                    continue
                with open(path, "rb") as fh:
                    data = base64.b64encode(fh.read()).decode("ascii")
            except OSError:
                continue
            self._index_artifact(f, path)
            items.append({
                "type": "image",
                "name": f,
                "mime": self._IMAGE_MIME.get(ext, "application/octet-stream"),
                "data": data,
            })
            if len(items) >= 8:
                break
        return items


class CreateRestorePointTool(Tool):
    """创建系统还原点（Windows 专属，best-effort）。

    作为 AI 执行高危/系统级操作前的安全网：先建还原点，若操作搞砸系统
    （注册表/驱动/系统设置），可在「系统还原」回滚。不保护用户个人文件。
    """
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="create_restore_point",
            permission="system.restore",
            description="创建 Windows 系统还原点（安全网）。在执行可能改动系统设置/注册表/驱动的高危操作前调用，"
                        "以便出问题时系统还原回滚。需要管理员权限且系统保护已开启；失败会返回原因。"
                        "参数 description 为还原点说明。",
            parameters={
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "还原点说明（将加 P.A.L.M AI 前缀，便于识别）",
                        "default": "AI 操作前快照",
                    },
                },
                "required": [],
            },
            event_type="system.restore",
        )

    async def execute(self, description: str = "AI 操作前快照") -> str:
        restore = _restore_module()
        if restore is None:
            return "系统还原点模块不可用（沙箱砖未注册）。"
        r = restore.create_system_restore_point(description)
        if r["ok"]:
            return ("已创建系统还原点：%s（序号 %s）。若后续操作搞砸系统，"
                    "可在「系统还原」中回滚到该点。注意：还原点不保护用户个人文件。"
                    % (r["point_name"], r["seq"]))
        return "创建还原点失败：%s。需以管理员身份运行且系统保护已开启。" % r["error"]


class CleanupRestorePointsTool(Tool):
    """安全清理本程序创建的系统还原点（Windows 无按序号删点 API，只能删最旧卷影）。"""
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="cleanup_restore_points",
            permission="system.restore",
            description="清理本程序（P.A.L.M）创建的全部系统还原点。现代 Windows 没有"
                        "「按序号删单点」的公开 API，本工具通过删除最旧卷影副本的方式循环清理，"
                        "遇到最旧还原点是系统自建点时自动停止，绝不误删系统还原点。"
                        "用于操作完成后回收临时快照。",
            parameters={"type": "object", "properties": {}, "required": []},
            event_type="system.restore",
        )

    async def execute(self) -> str:
        restore = _restore_module()
        if restore is None:
            return "系统还原点模块不可用（沙箱砖未注册）。"
        r = restore.cleanup_palm_restore_points()
        if not r["ok"]:
            return "清理还原点失败。"
        n = r["deleted_count"]
        if n == 0:
            return "没有本程序创建的还原点需要清理。"
        return "已清理 %d 个本程序创建的还原点。" % n


def _spawn_detached_process(command: str, log_file) -> subprocess.Popen:
    """派生脱离当前进程树的子进程，使对话/沙箱退出后后台任务仍存活。

    日志写入 log_file（由调用方打开），避免管道写满导致死锁。
    """
    if os.name == "nt":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        return subprocess.Popen(
            ["cmd", "/c", command],
            stdout=log_file, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, creationflags=flags,
            close_fds=True,
        )
    return subprocess.Popen(
        ["sh", "-c", command],
        stdout=log_file, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, start_new_session=True,
        close_fds=True,
    )


class StartBackgroundTaskTool(Tool):
    """登记一个后台长任务（受控路径），让 AI 可以开子进程但必须闭环。

    与 run_code 的区别：run_code 同步阻塞（适合短任务）；start_background_task 由后端
    直接派生**脱离沙箱 job** 的子进程，对话结束后不会被强杀，完成后由调度器自动唤醒 AI
    继续处理或总结。AI 不得在 run_code 里自行 Popen 后不等——那会丢失结果（见系统提示纪律）。
    """

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="start_background_task",
            permission="sandbox.run_code",
            description="登记一个后台长任务（如训练、构建、长耗时脚本、起一个本地服务）。"
                        "任务由系统直接派生并脱离对话进程，完成后会自动提醒并唤醒我继续处理或总结——"
                        "因此你登记后可以结束本轮对话，不必干等。\n"
                        "参数 command 为要执行的命令行（支持 shell 语法，如 `python train.py` / `npm run build`）；"
                        "description 为任务说明；timeout 为超时秒数（默认 3600，超时将被强杀）。\n"
                        "禁止使用场景：自动唤醒轮内不可再登记（会无限套娃），如需继续请直接处理或总结。",
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "要后台执行的命令行（shell 语法）",
                    },
                    "description": {
                        "type": "string",
                        "description": "任务说明，便于唤醒时识别",
                        "default": "后台任务",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "超时秒数，超时强杀",
                        "default": 3600,
                    },
                },
                "required": ["command"],
            },
            event_type="process.execute",
        )

    async def execute(self, command: str, description: str = "后台任务",
                      timeout: int = 3600) -> str:
        # 防套娃：自动唤醒轮内禁止再登记后台任务
        if agent_is_wakeup.get():
            return ("本轮为后台任务完成后的自动唤醒，禁止再登记后台任务（会无限套娃）。"
                    "请基于已给出的任务结果直接继续处理用户需求或给出总结，不要调用 start_background_task。")

        conversation_id = agent_conversation_id.get()
        model = agent_model.get()
        if not conversation_id:
            return "无法登记后台任务：缺少会话标识（conversation_id 未注入）。请改用 run_code 同步执行。"

        # 子进程脱离当前进程树：调度器心跳独立检测其退出，对话/沙箱退出后任务仍存活
        log_fd, log_path = tempfile.mkstemp(prefix="palm_bg_", suffix=".log")
        os.close(log_fd)
        log_file = open(log_path, "w", encoding="utf-8", errors="replace")
        try:
            proc = _spawn_detached_process(command, log_file)
        except Exception as exc:
            log_file.close()
            try:
                os.remove(log_path)
            except OSError:
                pass
            return "登记后台任务失败：%s" % exc

        task_id = get_evolution_api().scheduler.register(
            conversation_id=conversation_id, model=model, command=command,
            description=description, proc=proc, log_path=log_path,
            timeout=float(timeout),
        )
        # 子进程已脱离，关闭父端文件句柄（日志由子进程继续写）
        log_file.close()
        return ("已登记后台任务 %s（命令：%s）。任务完成或超时后，系统会自动提醒并唤醒我"
                "继续处理或总结，你可以先结束本轮对话，不必干等结果。" % (task_id, command))


# 导出注册列表（StartBackgroundTaskTool 已定义）
SANDBOX_TOOLS = [RunCodeTool, CreateRestorePointTool, CleanupRestorePointsTool, StartBackgroundTaskTool]
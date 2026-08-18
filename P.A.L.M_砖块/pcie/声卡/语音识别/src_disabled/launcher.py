"""把 STT 引擎（sherpa-onnx）作为独立子进程拉起，并管理就绪探测与退出。

标准砖块模式：推理依赖安装在砖块内独立 venv（bricks/stt/.venv-stt），经 `python -m
app.bricks.stt.engine.server` 在 backend 目录下启动（cwd=backend 使 -m 可导入），
重 ML 运行时隔离在独立进程，绝不塞进 P.A.L.M 进程。
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import time
from pathlib import Path

from palm_sdk.bricks._shared.paths import brick_local

import httpx

# 相对导入防模块双份（dev.py 以 backend.app.main 启动，绝对导入 app.* 会
# 产生第二份 registry/settings，导致本砖注册或配置取到孤立实例）。
from palm_sdk.core.config import settings


def discover_venv_python() -> str | None:
    """定位独立 venv 的 Python（engine 的运行解释器）。

    探测顺序：
    1. STT_VENV_PYTHON 环境变量（用户显式指定）
    2. 项目根 .venv-stt/Scripts/python.exe（Windows）
    3. 项目根 .venv-stt/bin/python（Linux/macOS）
    """
    if settings.STT_VENV_PYTHON and os.path.isfile(settings.STT_VENV_PYTHON):
        return settings.STT_VENV_PYTHON
    # 独立 venv 随砖块就位：launcher.py 位于 bricks/stt/，venv 即同目录 .venv-stt。
    stt_dir = Path(__file__).resolve().parent
    candidates = [
        stt_dir / ".venv-stt" / "Scripts" / "python.exe",
        stt_dir / ".venv-stt" / "bin" / "python",
    ]
    for path in candidates:
        if path.is_file():
            return str(path)
    return None


def backend_dir() -> Path:
    """STT 引擎子进程日志/工作目录：砖根（位置无关，砖可随意移动）。

    引擎以绝对路径直跑脚本（非 -m 模块），cwd 仅影响日志落点，不影响导入。
    """
    return Path(brick_local(__file__))


def build_launch_cmd() -> list[str]:
    python = discover_venv_python()
    if python is None:
        raise FileNotFoundError(
            "未找到 .venv-stt 虚拟环境，无法自动拉起 STT 引擎。"
            "请先运行 `python backend/app/bricks/stt/install.py` 安装依赖。"
        )
    # 直跑脚本而非 -m 模块：避免触发 app.bricks.__init__ 导入全部砖块
    #（其依赖主 venv 的 fastapi 等，.venv-stt 中不存在）。
    engine_server = Path(__file__).resolve().parent / "engine" / "server.py"
    return [
        python, str(engine_server),
        "--port", str(settings.STT_API_PORT),
        "--sample-rate", str(settings.STT_SAMPLE_RATE),
        "--vad", settings.STT_VAD_MODEL,
        "--asr-dir", settings.STT_ASR_MODEL,
        "--kws-dir", settings.STT_KWS_MODEL,
        "--kws-keywords", settings.STT_KWS_KEYWORDS,
    ]


def spawn_runtime() -> subprocess.Popen:
    cmd = build_launch_cmd()
    # cwd=backend：`python -m` 会把 cwd 加入 sys.path，engine 才能被导入。
    log_path = os.path.join(backend_dir(), "stt_runtime.log")
    log_fh = open(log_path, "a", encoding="utf-8", errors="replace")
    return subprocess.Popen(cmd, cwd=str(backend_dir()), stdout=log_fh, stderr=log_fh)


async def probe_ready(upstream_url: str, timeout: int = 30) -> bool:
    # 引擎只加载 ONNX 模型，就绪较快；仅探测连通性。
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                resp = await client.get(upstream_url.rstrip("/") + "/status")
            if resp.status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        await asyncio.sleep(1)
    return False


def shutdown_runtime(proc: subprocess.Popen, upstream_url: str) -> None:
    try:
        httpx.get(upstream_url.rstrip("/") + "/control", params={"command": "exit"}, timeout=5)
    except httpx.HTTPError:
        pass
    if proc.poll() is None:
        proc.terminate()
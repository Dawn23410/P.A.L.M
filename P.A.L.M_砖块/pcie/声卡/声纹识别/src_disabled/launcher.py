"""把声纹引擎（CAM++ / sherpa-onnx）作为独立子进程拉起，并管理就绪探测与退出。

标准砖块模式（与 stt 一致）：推理依赖安装在砖块内独立 venv（声纹识别/.venv-speaker），
经 `python server_speaker.py` 直跑脚本，重 ML 运行时隔离在独立进程，绝不塞进 P.A.L.M 进程。
模型/库路径由主进程从环境变量解析后作为命令行参数传入，引擎子进程不 import palm_sdk。
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import time
from pathlib import Path

import httpx


def _brick_dir() -> Path:
    # launcher.py 位于 声纹识别/src/，砖根为上级目录。
    return Path(__file__).resolve().parent.parent


def _src_dir() -> Path:
    return Path(__file__).resolve().parent


def _config() -> dict:
    """从环境变量解析配置，带内置默认值（不依赖 palm_sdk settings 代理）。"""
    brick = _brick_dir()
    return {
        "host": os.environ.get("SPEAKER_API_HOST", "127.0.0.1"),
        "port": int(os.environ.get("SPEAKER_API_PORT", "19510")),
        "model": os.environ.get(
            "SPEAKER_MODEL_PATH",
            str(_src_dir() / "speaker_models" / "campplus_zh_en_fp16.onnx"),
        ),
        "store": os.environ.get(
            "SPEAKER_STORE_PATH", str(brick / "data" / "speakers.json")
        ),
        "sample_rate": int(os.environ.get("SPEAKER_SAMPLE_RATE", "16000")),
        "threshold": float(os.environ.get("SPEAKER_THRESHOLD", "0.31")),
        "auto_launch": os.environ.get("SPEAKER_AUTO_LAUNCH", "true").lower() == "true",
    }


def discover_venv_python() -> str | None:
    """定位独立 venv 的 Python（engine 的运行解释器）。"""
    override = os.environ.get("SPEAKER_VENV_PYTHON")
    if override and os.path.isfile(override):
        return override
    brick = _brick_dir()
    candidates = [
        brick / ".venv-speaker" / "Scripts" / "python.exe",
        brick / ".venv-speaker" / "bin" / "python",
    ]
    for path in candidates:
        if path.is_file():
            return str(path)
    return None


def engine_url() -> str:
    cfg = _config()
    return f"http://{cfg['host']}:{cfg['port']}"


def build_launch_cmd() -> list[str]:
    python = discover_venv_python()
    if python is None:
        raise FileNotFoundError(
            "未找到 .venv-speaker 虚拟环境，无法自动拉起声纹引擎。"
            "请先运行 `python 声纹识别/src/install.py` 安装依赖并下载模型。"
        )
    cfg = _config()
    server = _src_dir() / "server_speaker.py"
    return [
        python, str(server),
        "--port", str(cfg["port"]),
        "--model", cfg["model"],
        "--store", cfg["store"],
        "--sample-rate", str(cfg["sample_rate"]),
        "--threshold", str(cfg["threshold"]),
    ]


def spawn_runtime() -> subprocess.Popen:
    cmd = build_launch_cmd()
    log_path = _brick_dir() / "speaker_runtime.log"
    log_fh = open(log_path, "a", encoding="utf-8", errors="replace")
    return subprocess.Popen(cmd, stdout=log_fh, stderr=log_fh)


async def probe_ready(upstream_url: str, timeout: int = 30) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                resp = await client.get(upstream_url.rstrip("/") + "/status")
            if resp.status_code == 200 and resp.json().get("ready"):
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

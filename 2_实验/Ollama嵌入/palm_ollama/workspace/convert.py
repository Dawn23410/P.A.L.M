"""Ollama 直转与模型拉取工具。

不再包含 llama.cpp SafeTensors → GGUF 转换。模型获取改用 `ollama pull` 从官方库拉取。
"""
from __future__ import annotations

import os
import re
import subprocess
from typing import AsyncIterator, Optional

# ---- Ollama CLI 检测 ----

_ollama_cache: Optional[str] = None


def _ollama_bin() -> Optional[str]:
    """查找本机 ollama 可执行文件路径（PATH + 常见安装目录），结果缓存。"""
    global _ollama_cache
    if _ollama_cache is not None:
        return _ollama_cache or None
    # 1) PATH
    for p in os.environ.get("PATH", "").split(os.pathsep):
        if not p:
            continue
        candidate = os.path.join(p.strip('"'), "ollama.exe" if os.name == "nt" else "ollama")
        if os.path.isfile(candidate):
            _ollama_cache = candidate
            return candidate
    # 2) Windows 常见安装目录
    if os.name == "nt":
        for base in (
            os.environ.get("LOCALAPPDATA", ""),
            os.environ.get("ProgramFiles", ""),
            os.environ.get("ProgramFiles(x86)", ""),
            os.environ.get("ProgramW6432", ""),
        ):
            if not base:
                continue
            candidate = os.path.join(base, "Ollama", "ollama.exe")
            if os.path.isfile(candidate):
                _ollama_cache = candidate
                return candidate
    # 3) macOS / Linux 常见路径
    for p in ("/usr/local/bin/ollama", "/opt/homebrew/bin/ollama", "/usr/bin/ollama"):
        if os.path.isfile(p):
            _ollama_cache = p
            return p
    _ollama_cache = ""
    return None


def is_ollama_capable() -> bool:
    """本机是否装有 ollama CLI。"""
    return _ollama_bin() is not None


def _ollama_model_name(key: str) -> str:
    """把模型标识规整为 Ollama 合法模型名（小写 + [a-z0-9._-]）。"""
    name = re.sub(r"[^a-z0-9._-]", "-", (key or "").lower())
    return name or "palm-model"


# ---- Ollama library pull（流式） ----

def _parse_pull_line(line: str) -> Optional[dict]:
    """解析 ``ollama pull`` 的进度行，返回 ``{status, completed, total}`` 或 None。"""
    line = line.strip()
    if not line:
        return None
    # 匹配：pulling manifest 或 pulling sha256:xxx...  12% ▕████▏ 2.1G/5.2G
    m = re.search(r"pulling\s+(\S+)\s+(\d+)%\s+\S+\s+([\d.]+[KMGTP]?)/([\d.]+[KMGTP]?)", line)
    if m:
        return {
            "status": "pulling",
            "digest": m.group(1),
            "percent": int(m.group(2)),
            "completed": m.group(3),
            "total": m.group(4),
        }
    # 匹配：success 或 error
    if "success" in line.lower():
        return {"status": "success"}
    if "error" in line.lower():
        return {"status": "error", "message": line}
    return {"status": "progress", "message": line}


async def ollama_pull_stream(name: str) -> AsyncIterator[dict]:
    """流式执行 ``ollama pull <name>``，逐行产生活动。

    Yields
    ------
    dict with keys:
        - ``status``: "pulling" | "success" | "error" | "progress"
        - ``digest``, ``percent``, ``completed``, ``total`` (when status=="pulling")
        - ``message`` (when status=="progress" or "error")
    """
    binp = _ollama_bin()
    if not binp:
        yield {"status": "error", "message": "未检测到 Ollama CLI 可执行文件"}
        return
    yield {"status": "progress", "message": f"开始拉取 {name}..."}
    try:
        proc = await asyncio_create_subprocess_exec(
            binp, "pull", name,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        # 读取 stderr（ollama pull 进度输出到 stderr）
        if proc.stderr:
            async for line in _aiter_lines(proc.stderr):
                parsed = _parse_pull_line(line)
                if parsed:
                    yield parsed
                if parsed and parsed.get("status") == "success":
                    break
                if parsed and parsed.get("status") == "error":
                    break
        await proc.wait()
        if proc.returncode == 0:
            yield {"status": "success", "message": f"{name} 已就绪"}
        else:
            yield {"status": "error", "message": f"ollama pull 退出码 {proc.returncode}"}
    except FileNotFoundError:
        yield {"status": "error", "message": "ollama 可执行文件未找到"}
    except Exception as e:
        yield {"status": "error", "message": f"ollama pull 异常：{e}"}


# ---- 辅助：异步 subprocess/line iteration ----

try:
    import asyncio
    asyncio_create_subprocess_exec = asyncio.create_subprocess_exec
except ImportError:
    asyncio_create_subprocess_exec = None

async def _aiter_lines(stream) -> AsyncIterator[str]:
    """异步逐行读取文本流。"""
    while True:
        line = await stream.readline()
        if not line:
            break
        yield line.rstrip("\n\r")

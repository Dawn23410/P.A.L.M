"""
P.A.L.M · 一键启动引擎
======================
启动脚本的核心逻辑：
1. 启动 GSV Runtime Server（端口 5000）
2. 启动模块管理 API 服务（端口 9090）
3. 扫描 modules/ 下的所有已安装模块并启动
4. 启动前端 Vite 服务
5. 前端就绪后清理子进程并自动退出
"""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
MODULES_DIR = PROJECT_ROOT / "modules"
RUNTIME_SERVER_PORT = 5000
MANAGER_PORT = 9090
FRONTEND_PORT = 43210

PYTHON = sys.executable
# 如果系统 Python 中没有 py7zr/psutil，回退到项目 venv
_VENV_PY = PROJECT_ROOT / "runtime" / "venv" / "Scripts" / "python.exe"
if _VENV_PY.exists():
    PYTHON = str(_VENV_PY)

# ── 全局进程跟踪 ────────────────────────────────────────────────

_procs: list[subprocess.Popen] = []
_pids: list[int] = []


def log(msg: str):
    print(f"  [{time.strftime('%H:%M:%S')}] {msg}")


def track(proc: subprocess.Popen):
    """注册进程到跟踪列表"""
    _procs.append(proc)
    if proc.pid:
        _pids.append(proc.pid)


def cleanup_all():
    """清理所有子进程"""
    log("Shutting down all services...")
    if sys.platform == "win32":
        for pid in _pids:
            try:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                               capture_output=True, timeout=5)
            except Exception:
                pass
    else:
        for proc in _procs:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except Exception:
                pass
    _procs.clear()
    _pids.clear()
    log("All processes terminated.")


def kill_residual(port: int):
    """杀掉占用指定端口的残留进程（纯 Python，无 shell 注入风险）"""
    if sys.platform != "win32":
        return
    try:
        result = subprocess.run(['netstat', '-ano'], capture_output=True, text=True, timeout=5)
        for line in result.stdout.strip().split("\n"):
            if f":{port} " not in line and f":{port}\r" not in line:
                continue
            parts = line.strip().split()
            # netstat 输出格式: proto localaddr foreignaddr state pid
            if len(parts) >= 5 and 'LISTENING' in line:
                pid = parts[-1]
                if pid.isdigit():
                    subprocess.run(['taskkill', '/F', '/PID', pid],
                                   capture_output=True, timeout=5)
    except Exception:
        pass


def wait_for_port(port: int, timeout: int = 15) -> bool:
    """轮询等待端口可用"""
    for _ in range(timeout):
        try:
            import socket
            s = socket.socket()
            s.settimeout(1)
            s.connect(("127.0.0.1", port))
            s.close()
            return True
        except Exception:
            time.sleep(1)
    return False


def find_valid_modules() -> list[dict]:
    """扫描 modules/ 目录，读取 MANIFEST.json，返回有效的模块列表"""
    if not MODULES_DIR.exists():
        log("[Setup] No modules/ directory found")
        return []
    modules = []
    for entry in sorted(MODULES_DIR.iterdir()):
        if not entry.is_dir():
            continue
        manifest_path = entry / "MANIFEST.json"
        if not manifest_path.exists():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if all(k in manifest for k in ["module", "version", "entry"]):
                modules.append({
                    "name": manifest["module"],
                    "version": manifest["version"],
                    "entry": str(entry / manifest["entry"]),
                    "path": str(entry),
                    "description": manifest.get("description", ""),
                    "config": manifest.get("config", {}),
                })
                log(f"  Found module: {manifest['module']} v{manifest['version']}")
        except Exception as e:
            log(f"  [WARN] Skipping {entry.name}: {e}")
    return modules


def main():
    print()
    print("  ╔══════════════════════════════════════════════╗")
    print("  ║      P.A.L.M · Launch Engine                ║")
    print("  ╚══════════════════════════════════════════════╝")
    print()

    # ── 1. 启动 GSV Runtime Server -----------------------------------------
    RUNTIME_PORT = 5000
    RUNTIME_PY = PROJECT_ROOT / "runtime" / "server.py"
    RUNTIME_VENV_PY = PROJECT_ROOT / "runtime" / "venv" / "Scripts" / "python.exe"

    log("[1/5] Starting GSV Runtime Server...")
    kill_residual(RUNTIME_PORT)

    if RUNTIME_VENV_PY.exists():
        runtime_proc = subprocess.Popen(
            [str(RUNTIME_VENV_PY), str(RUNTIME_PY)],
            cwd=str(PROJECT_ROOT / "runtime"),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    else:
        runtime_proc = subprocess.Popen(
            [PYTHON, str(RUNTIME_PY)],
            cwd=str(PROJECT_ROOT / "runtime"),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    track(runtime_proc)

    if wait_for_port(RUNTIME_PORT):
        log(f"  GSV Runtime Server ready at http://127.0.0.1:{RUNTIME_PORT}")
    else:
        log(f"  [WARN] GSV Runtime Server did not start in time")

    # ── 2. 启动模块管理 API ------------------------------------------------
    log("[2/5] Starting Module Manager API...")
    kill_residual(MANAGER_PORT)

    p = subprocess.Popen(
        [PYTHON, "-m", "uvicorn", "manager.app:app", "--host", "127.0.0.1",
         "--port", str(MANAGER_PORT)],
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    track(p)

    if wait_for_port(MANAGER_PORT):
        log(f"  Module Manager API ready at http://127.0.0.1:{MANAGER_PORT}")
    else:
        log(f"  [WARN] Module Manager API did not start in time")

    # ── 3. 扫描已安装模块 -------------------------------------------------
    log("[3/5] Scanning modules...")
    modules = find_valid_modules()

    if modules:
        log(f"  Found {len(modules)} module(s):")
        for m in modules:
            port = m["config"].get("port", "-") if isinstance(m["config"], dict) else "-"
            log(f"    {m['name']:20s} v{m['version']:8s}  port {str(port):>5s}")
        print()

        # ── 4. 启动所有模块 ------------------------------------------------
        log("[4/5] Starting modules...")
        for m in modules:
            entry = m["entry"]
            log(f"  Starting {m['name']}...")
            if entry.endswith(".py"):
                proc = subprocess.Popen(
                    [PYTHON, entry], cwd=m["path"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                )
            elif entry.endswith((".bat", ".cmd")):
                proc = subprocess.Popen(
                    [entry], cwd=m["path"], shell=True,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                )
            else:
                proc = subprocess.Popen(
                    [entry], cwd=m["path"], shell=True,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            track(proc)
            time.sleep(0.3)

        log("  Waiting for modules to initialize...")
        time.sleep(3)
        log("  All modules initialized")
    else:
        log("  No modules installed (skip start)")
        print()

    # ── 5. 启动前端 -------------------------------------------------------
    log("[5/5] Starting Frontend (Vite)...")
    npm = "npm.cmd" if sys.platform == "win32" else "npm"
    frontend = subprocess.Popen(
        [npm, "run", "dev"],
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    track(frontend)

    if wait_for_port(FRONTEND_PORT, timeout=15):
        log(f"  Frontend ready at http://localhost:{FRONTEND_PORT}/dashboard")
        import webbrowser
        webbrowser.open(f"http://localhost:{FRONTEND_PORT}/dashboard")
    else:
        log(f"  [WARN] Frontend did not start in time")

    print()

    log("=" * 50)
    log("  All systems ready!")
    log(f"  Module Manager: http://127.0.0.1:{MANAGER_PORT}")
    log(f"  API Docs:       http://127.0.0.1:{MANAGER_PORT}/docs")
    log(f"  Frontend:       http://localhost:{FRONTEND_PORT}")
    log("=" * 50)
    print()

    # launcher 退出，子进程继续运行


if __name__ == "__main__":
    main()

"""STT 砖依赖安装器：在砖块内创建 .venv-stt 并安装 sherpa-onnx 推理依赖。

用法：`python backend/app/bricks/stt/install.py`（用任意 Python 3.10+ 运行）。
优先使用 uv（若在 PATH 中）创建虚拟环境并安装；无 uv 时回退 venv + pip。
依赖说明：Python 3.13 下 numpy<2.0 无预编译 wheel（numpy 1.26 最高支持 3.12），
故此处安装 numpy>=2.0（sherpa-onnx>=1.10 已兼容 numpy 2）。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

STT_DIR = Path(__file__).resolve().parent  # install.py 位于 bricks/stt/
VENV_DIR = STT_DIR / ".venv-stt"

DEPENDENCIES = ["sherpa-onnx>=1.10", "sounddevice>=0.4", "numpy>=2.0"]


def _venv_python() -> Path:
    if sys.platform == "win32":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def create_venv() -> Path:
    if _venv_python().is_file():
        print(f"[stt] 已存在 {VENV_DIR}，跳过创建。")
        return _venv_python()
    uv = shutil.which("uv")
    if uv:
        subprocess.run([uv, "venv", "--python", f"{sys.version_info.major}.{sys.version_info.minor}", str(VENV_DIR)], check=True)
    else:
        subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], check=True)
    print(f"[stt] 已创建虚拟环境 {VENV_DIR}")
    return _venv_python()


def install_dependencies(python: Path) -> None:
    uv = shutil.which("uv")
    if uv:
        cmd = [uv, "pip", "install", "--python", str(python), *DEPENDENCIES]
    else:
        cmd = [str(python), "-m", "pip", "install", *DEPENDENCIES]
    subprocess.run(cmd, check=True)
    print("[stt] 依赖安装完成。")


def main() -> None:
    python = create_venv()
    install_dependencies(python)
    print("[stt] 安装完成。模型请放入 Data/stt_models/{vad,kws,asr}（详见 docs/voice_subsystem_impl_spec.md）。")


if __name__ == "__main__":
    os.chdir(PROJECT_ROOT)
    main()

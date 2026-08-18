"""声纹识别砖依赖安装器：在砖块内创建 .venv-speaker 并安装 sherpa-onnx 推理依赖，
随后下载 CAM++ 说话人模型（fp16 优先，回退 fp32）到 src/speaker_models/。

用法：`python 声纹识别/src/install.py`（用任意 Python 3.10+ 运行）。
遵循「权重内聚 + 自带依赖」铁律：venv 与模型均落在砖目录内，物理复制、不软链，
使砖可独立搬运。

注意：pip 安装须 --no-cache-dir（本环境 safe-delete 守卫会拦截 pip 的 wheel 缓存
临时文件删除，导致安装失败）。建议在沙箱外运行。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

SPEAKER_DIR = Path(__file__).resolve().parent  # install.py 位于 声纹识别/src/
BRICK_DIR = SPEAKER_DIR.parent
VENV_DIR = BRICK_DIR / ".venv-speaker"
MODELS_DIR = SPEAKER_DIR / "speaker_models"

DEPENDENCIES = ["sherpa-onnx", "onnxruntime", "sounddevice", "numpy", "httpx", "soundfile"]

# CAM++ 说话人模型（HuggingFace 镜像）：fp16 仅 14MB，CPU 推理 ~70ms/句。
_MODEL_BASE = "https://hf-mirror.com/Luigi/campplus-zh-en-onnx/resolve/main/"
_MODEL_CANDIDATES = ["campplus_zh_en_fp16.onnx", "campplus_zh_en_fp32.onnx"]


def _venv_python() -> Path:
    if sys.platform == "win32":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def create_venv() -> Path:
    if _venv_python().is_file():
        print(f"[speaker] 已存在 {VENV_DIR}，跳过创建。")
        return _venv_python()
    uv = shutil.which("uv")
    if uv:
        subprocess.run([uv, "venv", "--python", f"{sys.version_info.major}.{sys.version_info.minor}", str(VENV_DIR)], check=True)
    else:
        subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], check=True)
    print(f"[speaker] 已创建虚拟环境 {VENV_DIR}")
    return _venv_python()


def install_dependencies(python: Path) -> None:
    cmd = [str(python), "-m", "pip", "install", "--no-cache-dir", *DEPENDENCIES]
    subprocess.run(cmd, check=True)
    print("[speaker] 依赖安装完成。")


def download_model() -> None:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    for fname in _MODEL_CANDIDATES:
        dest = MODELS_DIR / fname
        if dest.is_file():
            print(f"[speaker] 模型已存在：{dest}")
            return
        url = _MODEL_BASE + fname
        try:
            print(f"[speaker] 下载模型：{url}")
            urllib.request.urlretrieve(url, dest)
            print(f"[speaker] 模型已下载：{dest} ({dest.stat().st_size} 字节)")
            return
        except Exception as exc:  # noqa: BLE001  镜像不可达时尝试下一档
            print(f"[speaker] 下载失败（{fname}）：{exc}")
            if dest.is_file():
                dest.unlink()
    print("[speaker] 警告：模型下载失败，请手动下载 CAM++ onnx 放入 src/speaker_models/。")


def main() -> None:
    python = create_venv()
    install_dependencies(python)
    download_model()
    print("[speaker] 安装完成。启动 P.A.L.M 后将自动拉起声纹引擎。")


if __name__ == "__main__":
    main()

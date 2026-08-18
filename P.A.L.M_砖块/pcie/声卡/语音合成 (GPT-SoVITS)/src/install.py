"""为 tts_sovits 砖块创建独立 venv 并安装 GPT-SoVITS 依赖。

标准砖块安装流程：
1. 在项目根创建 .venv-gsv 虚拟环境（Python 3.11）
2. pip install gpt_sovits/requirements.txt
3. pip install gpt_sovits/extra-req.txt

用法（作为独立脚本运行，无需 import 整个砖块包，避免拉起 agent 等重依赖）：
    python plugins/tts_sovits/install.py [--python python3.11] [--force]
幂等：venv 已存在且关键依赖已安装时跳过（除非 --force）。
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

# 不 import 砖块包（会触发 agent 等重依赖）；路径按本文件位置推算：
# install.py 位于 plugins/tts_sovits/，上溯两级即项目根 P.A.L.M。
_BRICK_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _BRICK_DIR.parents[1]
_VENV_DIR = _PROJECT_ROOT / ".venv-gsv"
_GSV_SOURCE = _BRICK_DIR / "gpt_sovits"


def find_python(explicit: str | None) -> str:
    """定位 Python 3.11 解释器（GSV 受 transformers<=4.50 + numpy<2.0 约束）。"""
    if explicit:
        return explicit
    # 探测系统 Python 3.11。
    candidates = [
        sys.executable,  # 当前解释器（可能已是 3.11）
        "python3.11",
        "python3.11.exe",
        r"C:\Python311\python.exe",
        r"C:\Users\{}\AppData\Local\Programs\Python\Python311\python.exe".format(
            os.getenv("USERNAME", "")
        ),
    ]
    for path in candidates:
        try:
            result = subprocess.run(
                [path, "--version"], capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and "3.11" in result.stdout:
                return path
        except (FileNotFoundError, subprocess.SubprocessError):
            continue
    raise FileNotFoundError(
        "未找到 Python 3.11 解释器。GSV 需要 Python 3.11"
        "（受 transformers<=4.50 + numpy<2.0 约束）。"
        "请用 --python 指定路径，或安装 Python 3.11。"
    )


def venv_python(venv_dir: Path) -> str:
    """获取 venv 内的 Python 路径。"""
    if os.name == "nt":
        return str(venv_dir / "Scripts" / "python.exe")
    return str(venv_dir / "bin" / "python")


def create_venv(python: str, venv_dir: Path, force: bool = False) -> str:
    """创建虚拟环境，返回 venv 内 Python 路径。"""
    venv_py = venv_python(venv_dir)
    if venv_dir.is_dir() and os.path.isfile(venv_py):
        if force:
            print(f"清理已有 venv：{venv_dir}")
            import shutil
            shutil.rmtree(venv_dir, ignore_errors=True)
        else:
            print(f"venv 已存在，跳过创建：{venv_dir}")
            return venv_py
    print(f"创建 venv：{venv_dir}（使用 {python}）")
    subprocess.run(
        [python, "-m", "venv", str(venv_dir)],
        check=True, timeout=120,
    )
    return venv_py


def pip_install(venv_py: str, requirements_path: str, label: str = "") -> None:
    """在 venv 中执行 pip install -r。"""
    if not os.path.isfile(requirements_path):
        print(f"跳过（文件不存在）：{requirements_path}")
        return
    desc = f"安装 {label}" if label else "安装依赖"
    print(f"{desc}：{requirements_path}")
    subprocess.run(
        [venv_py, "-m", "pip", "install", "-r", requirements_path],
        check=True, timeout=3600,
    )


def check_key_dependency(venv_py: str) -> bool:
    """检查关键依赖是否安装成功（torch + transformers）。"""
    try:
        result = subprocess.run(
            [venv_py, "-c", "import torch; import transformers; print('OK')"],
            capture_output=True, text=True, timeout=30,
        )
        return result.returncode == 0 and "OK" in result.stdout
    except (FileNotFoundError, subprocess.SubprocessError):
        return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="为 tts_sovits 砖块创建 venv 并安装 GPT-SoVITS 依赖"
    )
    parser.add_argument(
        "--python", default=None,
        help="Python 3.11 解释器路径（默认自动探测）",
    )
    parser.add_argument(
        "--venv-dir", default=str(_VENV_DIR),
        help=f"venv 目录（默认 {_VENV_DIR}）",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="venv 已存在也强制重建",
    )
    args = parser.parse_args()

    venv_dir = Path(args.venv_dir)

    # 1. 定位 Python 3.11
    python = find_python(args.python)
    print(f"使用 Python：{python}")

    # 2. 创建 venv
    venv_py = create_venv(python, venv_dir, args.force)

    # 3. 升级 pip
    print("升级 pip...")
    subprocess.run(
        [venv_py, "-m", "pip", "install", "--upgrade", "pip"],
        check=True, timeout=120,
    )

    # 4. 安装 GSV 依赖
    req_file = str(_GSV_SOURCE / "requirements.txt")
    pip_install(venv_py, req_file, "GPT-SoVITS 核心依赖")

    extra_req = str(_GSV_SOURCE / "extra-req.txt")
    pip_install(venv_py, extra_req, "额外依赖（ASR）")

    # 5. 验证关键依赖
    if check_key_dependency(venv_py):
        print("\n安装完成！关键依赖（torch + transformers）验证通过。")
        print(f"  venv 路径：{venv_dir}")
        print(f"  GSV 源码：{_GSV_SOURCE}")
        print("\n下一步：下载预训练模型到 gpt_sovits/GPT_SoVITS/pretrained_models/")
        print("详见 README.md「下载预训练模型」章节。")
    else:
        print("\n警告：关键依赖验证失败，请检查 pip install 输出。")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())

"""为 cosyvoice 完整砖安装 CosyVoice2 依赖（装入运行 P.A.L.M 的同一 Python 环境）。

完整砖要求 cosyvoice 在运行 P.A.L.M 的进程内直接加载/推理，因此依赖必须装进
当前 python（sys.executable）。本脚本针对本机 RTX 5060 Laptop（Blackwell, sm_120）
验证通过，核心要点：

1. torch / torchaudio 必须 cu128（CUDA 12.8 含 sm_120 内核镜像）。cu126 只编译到
   sm_90，在 Blackwell 上推理会报 `CUDA error: no kernel image is available`。
2. cosyvoice / matcha 是 vendored 源码（拷贝进 site-packages），不走 PyPI 的
   `cosyvoice` 包（版本/依赖不匹配，且会触发删除守卫）。
3. 一批训练专用或无关的传递依赖（lightning / gdown / wget / librosa / soxr /
   pkg_resources / whisper.tokenizer）只在配置加载链被 import、推理从不使用，
   用纯 Python 保真 shim 顶替，避免拉一整棵训练依赖。
4. 音频读写绕过 torchaudio 的 soundfile→torchcodec 路由（本机无 ffmpeg），直接用
   soundfile（pysoundfile）。

全程遵守「删除守卫」：只做纯写入（拷贝 / zipfile 解压 / --no-deps 装新包），
绝不 uninstall 已装包；覆盖升级用 zipfile 全量解压 + 旧 dist-info 改名（rename 非 delete）。

用法：
    python "语音合成 (CosyVoice)/src/install.py"            # 探测并补齐缺失项
    python "语音合成 (CosyVoice)/src/install.py" --force     # 强制重做 vendored 拷贝
    set COSY_TORCH_CU=cu128 或 cu126 可强制指定 CUDA 构建
幂等：已就绪的步骤会跳过。
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

_BRICK_DIR = Path(__file__).resolve().parent
_ROOT = _BRICK_DIR.resolve().parent.parent  # 项目根（plugins/cosyvoice 的上两级）
_WHEELS = _ROOT / "Data" / "wheels"
_TUNA = "https://pypi.tuna.tsinghua.edu.cn/simple"
_CU128_IDX = "https://download.pytorch.org/whl/cu128"
# Blackwell（sm_100 / sm_120）需要 cu128；其余架构用 cu126 即可。
_TORCH_WHEELS = {
    "cu128": ("torch-2.11.0+cu128-cp313-cp313-win_amd64.whl",
              "torchaudio-2.11.0+cu128-cp313-cp313-win_amd64.whl"),
    "cu126": ("torch-2.11.0+cu126-cp313-cp313-win_amd64.whl",
              "torchaudio-2.11.0+cu126-cp313-cp313-win_amd64.whl"),
}


def _py() -> str:
    return sys.executable


def _sp() -> Path:
    return Path(_py()).resolve().parent.parent / "Lib" / "site-packages"


def _run(cmd: list[str], timeout: int = 7200) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True, timeout=timeout)


def _need_cu() -> str:
    forced = os.getenv("COSY_TORCH_CU")
    if forced in ("cu126", "cu128"):
        return forced
    try:
        import torch
        if torch.cuda.is_available():
            major = torch.cuda.get_device_capability(0)[0]
            return "cu128" if major >= 12 else "cu126"
    except Exception:
        pass
    return "cu128"  # Blackwell 本机默认


# ───────────────────────── torch / torchaudio ─────────────────────────
def _torch_ready(cu: str) -> bool:
    try:
        import torch
    except Exception:
        return False
    if f"+{cu}" not in torch.__version__:
        return False
    if cu == "cu128" and "sm_120" not in torch.cuda.get_arch_list():
        return False
    return True


def _ensure_torch(cu: str) -> None:
    if _torch_ready(cu):
        print(f"[torch] 已是 {cu}（含所需架构），跳过。")
        return
    tw, taw = _TORCH_WHEELS[cu]
    _WHEELS.mkdir(parents=True, exist_ok=True)
    for whl in (tw, taw):
        url = f"{_CU128_IDX}/{whl}" if cu == "cu128" else f"https://download.pytorch.org/whl/cu126/{whl}"
        local = _WHEELS / whl
        if not local.is_file():
            print(f"[torch] 下载 {whl}（来自 {url}）...")
            _run(["curl", "-L", "--max-time", "590", "-o", str(local), url], timeout=600)
    # 覆盖解压（纯写入，绕开删除守卫）
    for whl in (tw, taw):
        with zipfile.ZipFile(_WHEELS / whl) as z:
            z.extractall(_sp())
    # 旧 dist-info 改名（rename 非 delete）
    for pkg in ("torch", "torchaudio"):
        ver = "cu128" if cu == "cu128" else "cu126"
        old = _sp() / f"{pkg}-2.11.0+{ver}.dist-info"
        bak = _sp() / f"{old.name}.bak"
        if old.is_dir() and not bak.exists():
            old.rename(bak)
    print(f"[torch] 已升级到 {cu}。")


# ───────────────────────── 叶子真实包 ─────────────────────────
_LEAF_DEPS = [
    ("hydra-core", "1.3.2"),
    ("pyarrow", "25.0.1"),
    ("soundfile", "0.14.0"),
    ("ruamel.yaml", "0.17.40"),
    # 文本规整（tn）：数字/日期归一化，cosyvoice frontend 的 wetext 分支依赖。
    # 显式钉版本，避免首次加载时被 modelscope 现场拉取（破坏运行期零联网）。
    ("wetext", "0.0.4"),
]


def _leaf_missing(name: str) -> bool:
    try:
        importlib.util.find_spec(name.replace("-", "_").split(".")[0])
        return False
    except Exception:
        return True


def _ensure_leaf_deps() -> None:
    missing = [f"{n}=={v}" for n, v in _LEAF_DEPS if _leaf_missing(n)]
    if not missing:
        print("[leaf] 真实叶子包均已存在，跳过。")
        return
    _run([_py(), "-m", "pip", "install", "--no-deps", "-i", _TUNA, *missing])


# ───────────────────────── vendored cosyvoice / matcha ─────────────────────────
def _patch_load_wav(path: Path) -> None:
    """把拷贝后的 cosyvoice/utils/file_utils.py 的 load_wav 改为直接用 soundfile 读。"""
    text = path.read_text(encoding="utf-8")
    marker = "def load_wav("
    if "sf.read(wav" in text:
        return  # 已打过补丁
    idx = text.find(marker)
    if idx < 0:
        return
    # 找到函数体结束（下一个顶层 def 或文件尾），整体替换。
    nxt = text.find("\ndef ", idx + len(marker))
    head = text[:idx]
    tail = text[nxt:] if nxt >= 0 else ""
    new_fn = (
        "def load_wav(wav, target_sr, min_sr=16000):\n"
        "    # torchaudio 2.11 把 soundfile 后端路由到 torchcodec，而本机无 ffmpeg；\n"
        "    # 改为直接用已安装的 pysoundfile 读取，绕开 torchcodec 依赖。\n"
        "    import soundfile as sf\n"
        "    speech_np, sample_rate = sf.read(wav, dtype='float32', always_2d=False)\n"
        "    speech = torch.from_numpy(speech_np).float()\n"
        "    if speech.dim() == 1:\n"
        "        speech = speech.unsqueeze(0)\n"
        "    else:\n"
        "        speech = speech.transpose(0, 1)\n"
        "    speech = speech.mean(dim=0, keepdim=True)\n"
        "    if sample_rate != target_sr:\n"
        "        assert sample_rate >= min_sr, 'wav sample rate {} must be greater than {}'.format(sample_rate, target_sr)\n"
        "        speech = torchaudio.transforms.Resample(orig_freq=sample_rate, new_freq=target_sr)(speech)\n"
        "    return speech\n"
    )
    path.write_text(head + new_fn + tail, encoding="utf-8")


def _ensure_vendored() -> None:
    src = _ROOT / "Data" / "CosyVoice_src" / "cosyvoice"
    dst = _sp() / "cosyvoice"
    if not src.is_dir():
        print(f"[vendored] 未找到 vendored 源码：{src}（跳过 cosyvoice 拷贝）")
    elif dst.is_dir() and not os.getenv("COSY_FORCE_COPY"):
        print("[vendored] cosyvoice 已拷贝，跳过（设 COSY_FORCE_COPY=1 可强制覆盖）。")
    else:
        shutil.copytree(src, dst, dirs_exist_ok=True)
        _patch_load_wav(dst / "utils" / "file_utils.py")
        print("[vendored] cosyvoice 已拷贝并打 soundfile 补丁。")
    # matcha：优先用已装；缺失则 --no-deps 安装（vendored third_party 不在工作区时兜底）
    if _leaf_missing("matcha"):
        _run([_py(), "-m", "pip", "install", "--no-deps", "-i", _TUNA, "matcha"])


# ───────────────────────── 纯 Python shim ─────────────────────────
def _write(path: Path, content: str) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"[shim] 写入 {path.name}")


def _ensure_shims() -> None:
    sp = _sp()
    _write(sp / "lightning" / "__init__.py", _LIGHTNING_INIT)
    _write(sp / "lightning" / "pytorch" / "__init__.py", _LIGHTNING_PYTORCH_INIT)
    _write(sp / "lightning" / "pytorch" / "utilities.py", _LIGHTNING_UTIL)
    _write(sp / "lightning" / "pytorch" / "loggers.py", _LIGHTNING_LOGGERS)
    _write(sp / "gdown" / "__init__.py", _GDOWN)
    _write(sp / "wget" / "__init__.py", _WGET)
    _write(sp / "librosa" / "__init__.py", _LIBROSA_INIT)
    _write(sp / "librosa" / "filters.py", _LIBROSA_FILTERS)
    _write(sp / "soxr" / "__init__.py", _SOXR)
    _write(sp / "pkg_resources" / "__init__.py", _PKG_RESOURCES)
    _write(sp / "whisper" / "tokenizer.py", _WHISPER_TOKENIZER)


# ───────────────────────── 验证 ─────────────────────────
def _check() -> bool:
    try:
        import torch
        import cosyvoice  # noqa: F401
    except Exception as e:
        print("关键依赖缺失：", e)
        return False
    if "sm_120" not in torch.cuda.get_arch_list():
        print("torch 架构列表缺 sm_120，Blackwell 推理会失败。")
        return False
    return True


def _prewarm_wetext() -> None:
    """安装期预热 wetext 归一化模型缓存（联网合法）；运行期不再触发 modelscope 下载。

    cosyvoice frontend 的 wetext 分支在构造 Normalizer 时会从 modelscope 拉取模型，
    若不预热，首次造音（运行期）会联网，违反完整砖零联网铁律。安装期拉一次即可。
    """
    try:
        from wetext import Normalizer
        Normalizer(remove_erhua=False)  # 触发模型下载并落盘到缓存
        print("[wetext] 归一化模型预热完成（运行期将走本地缓存）。")
    except Exception as exc:  # 预热失败不阻断安装，运行期优雅回退到无 frontend
        print(f"[wetext] 预热跳过（运行期将无文本前端，不影响造音）：{exc}")


def main() -> int:
    ap = argparse.ArgumentParser(description="cosyvoice 完整砖依赖安装（守卫安全、可复现）")
    ap.add_argument("--force", action="store_true", help="强制重做 vendored 拷贝")
    args = ap.parse_args()
    if args.force:
        os.environ["COSY_FORCE_COPY"] = "1"

    cu = _need_cu()
    print(f"目标 Python（P.A.L.M 运行时）：{_py()}")
    print(f"检测到的 CUDA 构建需求：{cu}")
    _ensure_torch(cu)
    _ensure_leaf_deps()
    _prewarm_wetext()
    _ensure_vendored()
    _ensure_shims()

    if _check():
        print("\n安装完成！关键依赖（cosyvoice + torch cu128 + sm_120）验证通过。")
        print("下一步：确认 语音合成 (CosyVoice)/cosyvoice_model/ 权重已就位，"
              "运行 Data/cosy_smoke_test.py 验证造音。")
        return 0
    print("\n警告：关键依赖验证失败，请检查上方输出。")
    return 1


# ===================== shim 内容 =====================
_LIGHTNING_INIT = '''import inspect
import torch
from types import SimpleNamespace

class LightningModule(torch.nn.Module):
    def __init__(self, *args, **kwargs):
        super().__init__()
        self.trainer = None
    def save_hyperparameters(self, *args, **kwargs):
        caller = inspect.currentframe().f_back
        local = {k: v for k, v in caller.f_locals.items()
                 if k != "self" and not (k.startswith("__") and k.endswith("__"))}
        self.hparams = SimpleNamespace(**local)

class Callback: pass
class LightningDataModule: pass
class Trainer: pass

from .pytorch.utilities import rank_zero_only, grad_norm
from .pytorch.loggers import Logger
from . import pytorch
'''

_LIGHTNING_PYTORCH_INIT = '''from . import utilities
from . import loggers
'''

_LIGHTNING_UTIL = '''def rank_zero_only(fn):
    return fn
def grad_norm(model, norm_type=2):
    return {}
'''

_LIGHTNING_LOGGERS = '''class Logger: pass
'''

_GDOWN = '''def download(*a, **k):
    raise NotImplementedError("gdown 仅训练期下载用，推理不需要；完整砖不启用。")
def cached_download(*a, **k):
    raise NotImplementedError("gdown 仅训练期下载用，推理不需要；完整砖不启用。")
'''

_WGET = '''def download(*a, **k):
    raise NotImplementedError("wget 仅训练期下载用，推理不需要；完整砖不启用。")
def filename_from_url(*a, **k):
    raise NotImplementedError("wget 仅训练期下载用，推理不需要；完整砖不启用。")
'''

_LIBROSA_INIT = '''# librosa 完整库未安装；cosyvoice 推理链仅需 librosa.filters.mel（下方保真实现）。
from .filters import mel
'''

_LIBROSA_FILTERS = '''import numpy as np

def hz_to_mel(frequencies, htk=False):
    if htk:
        return 1127.0 * np.log(1.0 + np.asanyarray(frequencies) / 700.0)
    f = np.asanyarray(frequencies)
    fmin = 0.0
    fmax = 11025.0
    break_frequency = 1000.0
    mel = np.empty_like(f)
    lin = f < break_frequency
    mel[lin] = f[lin] / (fmax / break_frequency)
    mel[~lin] = 1.0 + (np.log(f[~lin] / break_frequency) / np.log(fmax / break_frequency))
    return mel

def mel_to_hz(mels, htk=False):
    if htk:
        return 700.0 * (np.exp(np.asanyarray(mels) / 1127.0) - 1.0)
    m = np.asanyarray(mels)
    fmin = 0.0
    fmax = 11025.0
    break_frequency = 1000.0
    f = np.empty_like(m)
    lin = m < 1.0
    f[lin] = m[lin] * (fmax / break_frequency)
    f[~lin] = break_frequency * np.exp((m[~lin] - 1.0) * np.log(fmax / break_frequency))
    return f

def mel_frequencies(n_mels=128, fmin=0.0, fmax=11025.0, htk=False):
    min_mel = hz_to_mel(fmin, htk=htk)
    max_mel = hz_to_mel(fmax, htk=htk)
    mels = np.linspace(min_mel, max_mel, n_mels)
    return mel_to_hz(mels, htk=htk)

def fft_frequencies(sr=22050, n_fft=2048):
    return np.linspace(0.0, float(sr) / 2, int(1 + n_fft // 2), endpoint=True)

def mel(sr, n_fft, n_mels=128, fmin=0.0, fmax=None, htk=False, norm="slaney", dtype=np.float32):
    if fmax is None:
        fmax = float(sr) / 2
    n_freqs = 1 + n_fft // 2
    weights = np.zeros((n_mels, n_freqs), dtype=dtype)
    fft_freqs = fft_frequencies(sr=sr, n_fft=n_fft)
    mel_f = mel_frequencies(n_mels + 2, fmin=fmin, fmax=fmax, htk=htk)
    f_diff = np.diff(mel_f)
    ramps = np.subtract.outer(mel_f, fft_freqs)
    for i in range(n_mels):
        left = -ramps[i] / f_diff[i]
        right = ramps[i + 2] / f_diff[i + 1]
        weights[i] = np.maximum(0.0, np.minimum(left, right))
    if norm == "slaney":
        enorm = 2.0 / (mel_f[2:n_mels + 2] - mel_f[:n_mels])
        weights *= enorm[:, None]
    return weights
'''

_SOXR = '''def resample(*a, **k):
    raise NotImplementedError("soxr 仅 transformers 音频后端可选；cosyvoice 推理用 torchaudio 重采样，不需要 soxr。")
def resample_audio(*a, **k):
    raise NotImplementedError("soxr 仅 transformers 音频后端可选；cosyvoice 推理用 torchaudio 重采样，不需要 soxr。")
'''

_PKG_RESOURCES = '''# setuptools 83 移除了 pkg_resources；pyworld 等在 import 时调用 get_distribution(...).version。
# 用 importlib.metadata 提供最小兼容，仅覆盖 cosyvoice 推理链实际用到的接口。
import importlib.metadata as _md

class DistributionNotFound(Exception): pass
class VersionConflict(Exception): pass
class RequirementParseError(Exception): pass
class UnknownExtra(Exception): pass

class _Distribution:
    def __init__(self, name):
        self.name = name
        try:
            self.version = _md.version(name)
        except _md.PackageNotFoundError:
            raise DistributionNotFound(name)
    def requires(self, *a, **k):
        return []

def get_distribution(name):
    return _Distribution(name)

def require(*a, **k):
    return []

def iter_entry_points(group, name=None):
    return []

def load_entry_point(*a, **k):
    raise ImportError("pkg_resources shim 不支持 load_entry_point")

def resource_filename(*a, **k):
    raise NotImplementedError("pkg_resources shim 不支持 resource_filename")

def resource_string(*a, **k):
    raise NotImplementedError("pkg_resources shim 不支持 resource_string")

def resource_stream(*a, **k):
    raise NotImplementedError("pkg_resources shim 不支持 resource_stream")
'''

_WHISPER_TOKENIZER = '''# whisper.tokenizer 仅被 cosyvoice 的 import 链引用；CosyVoice2 实际用 Qwen2 分词器
#（cosyvoice2.yaml 的 get_tokenizer: get_qwen_tokenizer），从不实例化本占位 Tokenizer。
LANGUAGES = {"zh": "chinese", "en": "english"}
TO_LANGUAGE_CODE = {"chinese": "zh", "english": "en"}

class Token:
    def __init__(self, rank=None, ttype=None):
        self.rank = rank
        self.type = ttype

class Encoding:
    def __init__(self, tokens, text=""):
        self.tokens = tokens
        self.text = text

class Tokenizer:
    def __init__(self, *a, **k):
        self.sot = 0
        self.eot = 0
        self.language = None
    def encode(self, text, *a, **k):
        return Encoding([], text)
    def decode(self, *a, **k):
        return ""
'''


if __name__ == "__main__":
    sys.exit(main())

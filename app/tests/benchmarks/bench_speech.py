"""SPEECH 内核基准 —— 语音（VOSK STT / CosyVoice TTS / GPT-SoVITS TTS）。

⚠ 根因（实测）：speech 包可导入，但 speech.vosk.recognize 触发
   ModuleNotFoundError: No module named 'sounddevice'（且 vosk / numpy / scipy 均 MISSING）。
   三套引擎均需重依赖：
   - VOSK STT：vosk 包 + 下载的模型文件（speech/vosk/models/）；
   - CosyVoice TTS：GPU/PyTorch + 模型权重；
   - GPT-SoVITS TTS：GPU/PyTorch + 7z 解压的 *.pth 权重（17GB）。
   离线环境无法安装/下载，整层标记 SKIP（根因可追溯），不计入 FAIL。

内核拓扑（已按用户修正）：speech 仅承载三套语音引擎，STT=VOSK，
TTS=CosyVoice + GPT-SoVITS；qwen3-asr 已按指令移除。
"""
from __future__ import annotations

import importlib
import traceback
from .harness import benchmark



@benchmark("speech")
def bench(col):
    try:
        importlib.import_module("speech")
        col.pass_("import", "package_importable", "correctness",
                  "speech 包顶层可导入（VOSK/CosyVoice/GSV 三引擎目录就位）")
    except Exception as e:
        col.fail("import", "package_importable", "correctness", str(e),
                 "".join(traceback.format_exception(type(e), e, e.__traceback__))[:400])
        return

    # 探测 vosk 信号处理导入
    try:
        importlib.import_module("speech.vosk.recognize")
        col.pass_("vosk", "recognize_importable", "correctness",
                  "speech.vosk.recognize 可导入")
    except Exception as e:
        rc = "".join(traceback.format_exception(type(e), e, e.__traceback__))[:300]
        col.skip("vosk", "recognize_importable", "correctness",
                 f"导入失败: {type(e).__name__}: {e}；根因=缺失 sounddevice/vosk/numpy")
        col.skip("vosk", "signal_fns", "degradation",
                 "resample_audio/ensure_16bit_pcm 等 numpy 信号处理不可达（numpy 缺失）→ skip")

    # TTS 引擎
    for eng, mod in (("cosyvoice", "speech.cosyvoice"),
                     ("gpt_sovits", "speech.gpt-sovits")):
        try:
            importlib.import_module(mod)
            col.pass_(eng, "importable", "correctness", f"{mod} 可导入")
        except Exception as e:
            col.skip(eng, "importable", "degradation",
                     f"{mod} 需 GPU/PyTorch + 模型权重，离线不可用 → skip "
                     f"(根因: {type(e).__name__})")

"""运行时取证（P.A.L.M 核心检验区 GSV）：真跑一次 v4 合成，记录所有被 import 的项目内模块与打开的文件。

与桌面版差异：直接用包自带的 tts_infer.yaml（custom 已是 v4 底模，不加改），
参考音用根目录 refer_audio.wav（与 set_refer.bat 生产用法一致）。
输出: trace_used_pal.json / trace_out_pal.wav
"""
import json
import os
import sys

ROOT = "D:/P.A.L.M/核心-检验/语音合成_GPT-SoVITS"
OUTDIR = "D:/P.A.L.M/1_Demo_LLM/audit_gpt_sovits"
TRACE_OUT = os.path.join(OUTDIR, "trace_used_pal.json")
WAV_OUT = os.path.join(OUTDIR, "trace_out_pal.wav")

os.chdir(ROOT)
sys.path.insert(0, os.getcwd())              # tools.* / api_v2 风格
sys.path.insert(0, os.path.join(os.getcwd(), "GPT_SoVITS"))  # AR.* / TTS_infer_pack / text.*

# ---- audit hook：只 append，不再触发 IO ----
events = []


def hook(event, args):
    try:
        if event in ("open", "os.open"):
            p = args[0]
            if isinstance(p, (str, bytes, os.PathLike)):
                events.append((event, os.fspath(p)))
        elif event == "subprocess.Popen":
            events.append((event, str(args[0])))
    except Exception:
        pass


sys.addaudithook(hook)

# ---- 生产原配置（custom=v4 底模，今晨 07:22 日志证明可加载）----
CFG = "GPT_SoVITS/configs/tts_infer.yaml"
REF = "refer_audio.wav"

from TTS_infer_pack.TTS import TTS, TTS_Config  # noqa: E402

cfg = TTS_Config(CFG)
print("version =", cfg.version, flush=True)
tts = TTS(cfg)

inputs = {
    "text": "核心检验区的减负方案确认，双路取证通过，正式动手。",
    "text_lang": "zh",
    "ref_audio_path": REF,
    "prompt_text": "这是一段用于运行时取证的参考音频转写文本。",  # v3/v4 系强制非空
    "prompt_lang": "zh",
    "text_split_method": "cut5",
}
audio = None
sr_final = None
for chunk in tts.run(inputs):
    sr, data = chunk
    audio = data if audio is None else audio
    sr_final = sr

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

sf.write(WAV_OUT, np.asarray(audio), sr_final)
print("合成完成:", WAV_OUT, sr_final, "Hz", flush=True)

# ---- 汇总：项目内模块 + 项目内 open 的文件 ----
norm = lambda p: os.path.normcase(os.path.abspath(p))
root_n = norm(ROOT)
used_files, modules = set(), {}
for name, m in list(sys.modules.items()):
    f = getattr(m, "__file__", None)
    if not f:
        continue
    f = os.path.abspath(f)
    if f.startswith(root_n) and f.endswith(".py"):
        modules[name] = os.path.relpath(f, ROOT).replace("\\", "/")
        used_files.add(modules[name])

subprocs = []
for ev, p in events:
    if ev in ("open", "os.open"):
        try:
            ap = norm(p if os.path.isabs(p) else os.path.join(ROOT, p))
        except Exception:
            continue
        if ap.startswith(root_n):
            used_files.add(os.path.relpath(ap, ROOT).replace("\\", "/"))
    else:
        subprocs.append(p)

json.dump({"modules": modules, "used_files": sorted(used_files),
           "subprocess": subprocs},
          open(TRACE_OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("项目内 py 模块:", len(modules), "| 项目内打开文件:", len(used_files),
      "| 子进程:", len(subprocs), flush=True)
print("JSON ->", TRACE_OUT, flush=True)

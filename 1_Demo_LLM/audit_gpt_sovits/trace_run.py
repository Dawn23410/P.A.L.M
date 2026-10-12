"""运行时取证：真跑一次 v4 合成，记录所有被 import 的项目内模块与打开的文件。

不改用户配置：把 tts_infer.yaml 的 custom 段改写为 v4 后落到临时 yaml。
输出: trace_used.json (used_files / modules / subprocess / wav)
"""
import json
import os
import sys

ROOT = "C:/Users/24459/Desktop/GPT-SoVITS-1007-cu128"
OUTDIR = "D:/P.A.L.M/1_Demo_LLM/audit_gpt_sovits"
TRACE_OUT = os.path.join(OUTDIR, "trace_used.json")
WAV_OUT = os.path.join(OUTDIR, "trace_out.wav")

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

# ---- 生成 v4 临时配置 ----
import yaml  # noqa: E402

with open("GPT_SoVITS/configs/tts_infer.yaml", "r", encoding="utf-8") as f:
    cfg_yaml = yaml.safe_load(f)

REF = r"C:\Users\24459\Desktop\v4\芙宁娜_ZH\reference_audios\中文\emotions\【默认】根据故事走向，前往特定情景吗？听起来挺新颖。所以信封里写了什么？.wav"
cfg_yaml["custom"] = {
    "device": "cuda",
    "is_half": True,  # transformers 5.x + peft 0.21 下 fp32 路径有 dtype 残留，half 路径一致
    "version": "v4",
    "t2s_weights_path": r"C:\Users\24459\Desktop\v4\芙宁娜_ZH\芙宁娜_ZH-e10.ckpt",
    "vits_weights_path": r"C:\Users\24459\Desktop\v4\芙宁娜_ZH\芙宁娜_ZH_e10_s950_l32.pth",
    "cnhuhbert_base_path": "GPT_SoVITS/pretrained_models/chinese-hubert-base",
    "bert_base_path": "GPT_SoVITS/pretrained_models/chinese-roberta-wwm-ext-large",
}
TMP_YAML = os.path.join(OUTDIR, "_trace_tts_infer.yaml")
with open(TMP_YAML, "w", encoding="utf-8") as f:
    yaml.safe_dump(cfg_yaml, f, allow_unicode=True)

# ---- 合成 ----
from TTS_infer_pack.TTS import TTS, TTS_Config  # noqa: E402

cfg = TTS_Config(TMP_YAML)
print("version =", cfg.version, "| device =", cfg.device if hasattr(cfg, "device") else "?", flush=True)
tts = TTS(cfg)

inputs = {
    "text": "鱼片，裁剪方案我看过了，值得动手，那就开工吧。",
    "text_lang": "zh",
    "ref_audio_path": REF,
    "prompt_text": "根据故事走向，前往特定情景吗？听起来挺新颖。所以信封里写了什么？",
    "prompt_lang": "zh",
    "text_split_method": "cut5",
}
sr = None
audio = None
for chunk in tts.run(inputs):
    sr, data = chunk
    audio = data if audio is None else None
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

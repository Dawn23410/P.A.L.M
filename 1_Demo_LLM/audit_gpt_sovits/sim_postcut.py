"""模拟裁剪后状态：把保留文件复制到临时目录并跑 codequal 对比。
只读原目录，不修改任何原文件。"""
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import slim_analyze as S  # noqa: E402

ROOT = "C:/Users/24459/Desktop/GPT-SoVITS-1007-cu128"
SIM = os.path.abspath("_sim_kept")

d = json.load(open("slim_reach.json", encoding="utf-8"))
UN = {x["path"] for x in d["unreachable"]}

if os.path.isdir(SIM):
    shutil.rmtree(SIM)

n = 0
for p in S.iter_py(ROOT):
    rel = S.rel(ROOT, p)
    if rel in UN:
        continue
    dst = os.path.join(SIM, rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(p, dst)
    n += 1
print(f"已复制 {n} 个保留文件 -> {SIM}")

SK = os.path.expanduser("~/.workbuddy/skills/palm-metrics/scripts/codequal.py")
EX = ("runtime/|pretrained_models/|__pycache__|f5_tts/|eres2net/|BigVGAN/|"
      "feature_extractor/|uvr5/|AP_BWE_main/|denoise-model/|tools/asr/")

for tag, extra in (("全量(含vendored残留)", []), ("自研核心口径", ["--exclude", EX])):
    out = f"codequal_postcut_{('full' if not extra else 'selfdev')}.json"
    r = subprocess.run([sys.executable, SK, SIM, "--dims", "all", "--top", "5",
                        "--json", out] + extra,
                       capture_output=True, text=True)
    txt = r.stdout
    for line in txt.splitlines():
        if any(k in line for k in ("项目总分", "文件数", "重复率", "平均 MI", "近似克隆")):
            print(f"  [{tag}] {line.strip()}")
    print(f"  [{tag}] JSON -> {out}")

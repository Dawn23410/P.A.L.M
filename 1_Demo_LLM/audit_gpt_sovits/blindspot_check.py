"""盲区查证：可达文件里有没有运行时(subprocess/字符串)引用被砍脚本。
静态 import 分析看不见这类引用，是裁剪的最大风险源。"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import slim_analyze as S  # noqa: E402

ROOT = "C:/Users/24459/Desktop/GPT-SoVITS-1007-cu128"
d = json.load(open("slim_reach.json", encoding="utf-8"))
UN = {x["path"] for x in d["unreachable"]}

allf = [S.rel(ROOT, p) for p in S.iter_py(ROOT)]
reach = [p for p in allf if p not in UN]
gone = set(UN)

# 1) 可达 py 源码里是否出现对被砍 .py 的字符串引用（subprocess/拼接）
pat = re.compile(r"""['"\s]([A-Za-z0-9_/\.\-]+\.py)['"]""")
hits = []
for rel in reach:
    ap = os.path.join(ROOT, rel)
    try:
        txt = open(ap, encoding="utf-8", errors="replace").read()
    except Exception:
        continue
    for i, line in enumerate(txt.splitlines(), 1):
        for m in pat.finditer(line):
            ref = m.group(1).lstrip("./")
            base = os.path.basename(ref)
            # 归一成项目内相对路径候选
            cand = [p for p in gone if p.endswith("/" + ref) or p == ref
                    or os.path.basename(p) == base]
            if cand:
                hits.append((rel, i, ref, cand[:2]))

print("=== 盲区1：可达代码对被砍脚本的字符串/subprocess 引用 ===")
if not hits:
    print("  无 ✓")
for rel, i, ref, c in hits:
    print(f"  {rel}:{i}  ->  {ref}   (命中 {c})")

# 2) 非 py 资源（yaml/json/bat/ps1/md）里引用被砍路径
res_hits = []
for dp, dn, fn in os.walk(ROOT):
    dn[:] = [x for x in dn if x not in {"runtime", "pretrained_models", "__pycache__", ".git",
                                        "models", "uvr5_weights", "custom_refs", "cache",
                                        "outputs", "runtime_logs", "7-Zip", "Aria2"}]
    if os.path.abspath(dp) == os.path.abspath(os.path.join(ROOT, "models")):
        continue
    for f in fn:
        if f.rsplit(".", 1)[-1].lower() not in {"yaml", "yml", "json", "bat", "ps1", "cmd", "toml", "ini", "cfg"}:
            continue
        ap = os.path.join(dp, f)
        try:
            txt = open(ap, encoding="utf-8", errors="replace").read()
        except Exception:
            continue
        rel = S.rel(ROOT, ap)
        for i, line in enumerate(txt.splitlines(), 1):
            low = line.lower()
            for g in ("train_util", "s2_train", "s1_train", "train_cli", "prepare_datasets",
                      "slice_audio", "slicer2", "cmd-denoise", "subfix", "uvr5", "webui.py",
                      "api.py", "tools/asr", "onnx_export", "export_torch_script",
                      "my_utils", "models_onnx", "attentions_onnx"):
                if g in low:
                    res_hits.append((rel, i, g, line.strip()[:110]))
                    break

print("\n=== 盲区2：配置/脚本资源文件对被砍目标的引用 ===")
seen = set()
for rel, i, g, line in res_hits:
    k = (rel, g)
    if k in seen:
        continue
    seen.add(k)
    print(f"  {rel}:{i} [{g}] {line}")
if not res_hits:
    print("  无 ✓")

# 3) 被砍文件里有多少安全 HIGH（量化攻击面收益）
sec = json.load(open("dynprobe_sec_selfdev.json", encoding="utf-8"))
finds = sec.get("findings") or sec.get("alerts") or []
by_file = {}
for f in finds:
    loc = (f.get("loc") or "").replace("\\", "/")
    p, _, lineno = loc.rpartition(":")
    sev = f.get("severity", "")
    by_file.setdefault(p, {"HIGH": 0, "MED": 0, "LOW": 0})
    k = "HIGH" if sev.upper().startswith("H") else ("MED" if sev.upper().startswith("M") else "LOW")
    by_file[p][k] += 1

cut_high = kept_high = 0
cut_files = []
unknown = []
for p, c in by_file.items():
    rel = p.replace(ROOT + "/", "")
    if rel in gone:
        cut_high += c["HIGH"]
        cut_files.append((rel, c["HIGH"]))
    elif rel.startswith("C:/") or rel.startswith("/"):
        unknown.append((p, c["HIGH"]))
    else:
        kept_high += c["HIGH"]
print("\n=== 盲区3：安全 HIGH 的归属（砍掉 vs 留下） ===")
print(f"  砍掉文件里的 HIGH: {cut_high}")
for p, h in sorted(cut_files, key=lambda x: -x[1]):
    print(f"    {h:>3}  {p}")
print(f"  留下文件里的 HIGH: {kept_high}")
if unknown:
    print(f"  [warn] 未归类 {len(unknown)} 条，样例: {unknown[:3]}")

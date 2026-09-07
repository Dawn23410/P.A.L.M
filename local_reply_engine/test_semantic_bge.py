# -*- coding: utf-8 -*-
"""语义升级( bge-m3 稠密检索 )可行性实测：能否真正分离域内/域外，代价多大。

背景：字符级 lexical(BM25+n-gram) 检索的域内/域外分数完全重叠，
      调阈值只能拿"域内召回"换"OOD误命中"（89%→46% 才能把误命中压到 0）。
本脚本验证：换成 bge-m3 稠密语义向量后，分离度与代价分别如何。

运行（需 onnxruntime+numpy+tokenizers）：
  C:/Users/Dawn/.workbuddy/binaries/python/envs/default/Scripts/python.exe test_semantic_bge.py
"""
import sys, os, glob, json, time
import numpy as np

sys.path.insert(0, r"C:/Users/Dawn/Desktop/local_reply_engine")
import local_reply.engine.hub as hub

# 指向本机已有的 bge-m3 权重（570MB，P.A.L.M 向量记忆同源）
WEIGHTS = r"C:/Users/Dawn/Desktop/P.A.L.M/memory/domain_memory/weights"
hub._BGE_M3_DIR = WEIGHTS

from local_reply import StitchEngine
from local_reply.engine import core
from tune_ood_threshold import IN_CORPUS, OOD

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "local_reply", "engine", "data")
os.makedirs(DATA, exist_ok=True)
VEC = os.path.join(DATA, "stitching_vectors.json")
CRP = os.path.join(DATA, "stitching_corpus.jsonl")

hub_obj = hub.Hub()
print("embedder.available():", hub_obj.embedder.available(), "| kind:", hub_obj.embedder.kind)
if not hub_obj.embedder.available():
    print("!! bge 权重不可用，退出"); sys.exit(1)

# 1) 构建稠密向量（首次）
part_files = sorted(glob.glob(os.path.join(HERE, "local_reply", "engine", "corpus", "mengyao_hq_part*.jsonl")))
records = core.load_persona_bank(part_files)
print(f"语料 {len(records)} 条，开始编码…")
t0 = time.perf_counter()
vecs = hub_obj.embedder.encode([r["q"] for r in records])
build_s = time.perf_counter() - t0
print(f"编码耗时 {build_s:.1f}s，dim={len(vecs[0])}")
with open(VEC, "w", encoding="utf-8") as fh: json.dump(vecs, fh)
with open(CRP, "w", encoding="utf-8") as fh:
    for r in records: fh.write(json.dumps(r, ensure_ascii=False) + "\n")

# 2) 冷启动 + 切到 semantic 模式
t0 = time.perf_counter()
eng = StitchEngine(hub=hub_obj)
cold_s = time.perf_counter() - t0
print(f"StitchEngine 冷启动 {cold_s:.1f}s | mode={eng.mode}")

M = np.asarray(vecs, dtype=np.float32)
M /= (np.linalg.norm(M, axis=1, keepdims=True) + 1e-9)

def sims(q):
    v = np.asarray(hub_obj.embedder.encode([q])[0], dtype=np.float32)
    v /= (np.linalg.norm(v) + 1e-9)
    return M @ v

# 3) 分离度：域内 vs 域外 top1 余弦
in_s, ood_s = [], []
t0 = time.perf_counter()
for q in IN_CORPUS: in_s.append(float(sims(q).max()))
for q in OOD:       ood_s.append(float(sims(q).max()))
enc_s = (time.perf_counter() - t0) / (len(IN_CORPUS) + len(OOD))
print(f"\n单查询编码均耗时 {enc_s*1000:.1f} ms")

print(f"\nIN  top1余弦: min={min(in_s):.3f} 中位={sorted(in_s)[len(in_s)//2]:.3f} max={max(in_s):.3f}")
print(f"OOD top1余弦: min={min(ood_s):.3f} 中位={sorted(ood_s)[len(ood_s)//2]:.3f} max={max(ood_s):.3f}")

print(f"\n{'阈值':>6} {'域内召回':>8} {'OOD误命中':>9}")
best = None
for th in [x / 100 for x in range(30, 86, 5)]:
    r = sum(1 for v in in_s if v >= th) / len(in_s)
    f = sum(1 for v in ood_s if v >= th) / len(ood_s)
    print(f"{th:>6.2f} {r:>8.3f} {f:>9.3f}")
    if best is None or (r - f) > best[2]: best = (th, r, r - f, f)
print(f"\n最佳权衡点: 阈值={best[0]:.2f} 域内召回={best[1]:.3f} OOD误命中={best[3]:.3f}")
print("\n对比 lexical(mock) 现状: 域内召回=0.893 时 OOD误命中=0.750；压到 OOD误命中=0.0 时 域内召回仅=0.464")

# -*- coding: utf-8 -*-
"""语料规模 → 泛化能力曲线

目的：定量回答"扩语料能提多少"。
方法：从 733 条里随机抽 N 条建语义索引，用**语料外**的未见句测 top1 命中率，
画出规模-命中率曲线，并外推到 1500/3000 条。

代理指标：语义 top1 余弦 > 阈值(0.72) 的比例。
说明：绕开引擎直接测检索层，未含 mock 兜底与后续逻辑，故绝对值与引擎实测略有出入，
但**趋势**是有效的——这正是要回答的问题。
"""
import sys, json, random, importlib.util, time

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"C:/Users/Dawn/Desktop/local_reply_engine")
import numpy as np
from local_reply import StitchEngine
from local_reply.engine import embed as E

ENGINE_DIR = r"C:/Users/Dawn/Desktop/local_reply_engine"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


v30 = _load("v30", ENGINE_DIR + "/bench_chat_v3.0_blind.py")
v32 = _load("v32", ENGINE_DIR + "/bench_chat_v3.2_freq.py")

UNSEEN = [q for q in v30.CANDIDATES]          # 68 条，语料外
FREQ = [q for _, q in v32.FREQ]               # 56 条，高频句

eng = StitchEngine(semantic=True)
records = eng.records
all_q = [r.get("q", "") for r in records]
mat_all = np.asarray(eng._sem_index, dtype=np.float32)
print(f"全量语料 {len(all_q)} 条, 矩阵 {mat_all.shape}")

qv_unseen = np.asarray(E.embed(UNSEEN), dtype=np.float32)
qv_freq = np.asarray(E.embed(FREQ), dtype=np.float32)

SIZES = [100, 200, 300, 450, 600, 733]
THR = 0.72
ROUNDS = 5

rows = []
for n in SIZES:
    acc_u, acc_f = [], []
    for rnd in range(ROUNDS):
        rng = random.Random(1000 + rnd)
        idx = rng.sample(range(len(all_q)), n)
        sub = mat_all[idx]
        su = (sub @ qv_unseen.T).max(axis=0)
        sf = (sub @ qv_freq.T).max(axis=0)
        acc_u.append(float((su > THR).mean()))
        acc_f.append(float((sf > THR).mean()))
    ru = sum(acc_u) / ROUNDS
    rf = sum(acc_f) / ROUNDS
    rows.append({"n": n, "unseen_hit": round(ru, 3), "freq_hit": round(rf, 3)})
    print(f"  N={n:4d}  未见句命中 {ru:.1%}   高频句命中 {rf:.1%}")

# 线性外推（对 log(n) 做线性拟合，语义检索的规模收益通常是对数型）
import math
xs = [math.log(r["n"]) for r in rows]
yu = [r["unseen_hit"] for r in rows]
n_ = len(xs)
mx = sum(xs) / n_
my = sum(yu) / n_
num = sum((a - mx) * (b - my) for a, b in zip(xs, yu))
den = sum((a - mx) ** 2 for a in xs)
k = num / den if den else 0
b0 = my - k * mx
print(f"\n拟合: unseen_hit = {k:.4f}*ln(N) + {b0:.4f}")
extrap = {}
for n in [1000, 1500, 2000, 3000, 5000]:
    v = k * math.log(n) + b0
    extrap[n] = round(min(v, 1.0), 3)
    print(f"  外推 N={n:5d} → 未见句命中 {min(v,1.0):.1%}")

out = {"thr": THR, "rounds": ROUNDS, "curve": rows,
       "fit": {"k": round(k, 4), "b": round(b0, 4)}, "extrapolation": extrap}
with open(ENGINE_DIR + "/bench_corpus_scale.json", "w", encoding="utf-8") as fh:
    json.dump(out, fh, ensure_ascii=False, indent=2)
print("\n已写入 bench_corpus_scale.json")

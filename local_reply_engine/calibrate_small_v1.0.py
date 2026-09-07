# -*- coding: utf-8 -*-
"""小模型阈值标定：域内句（T2 改写 + 语料抽样）与 OOD 句的 top1 分数分布，
找「域内召回高 + OOD 误命中低」的阈值。"""
import sys, io, os, json, random
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
os.environ["PALM_EMBED_MODEL"] = "small"
sys.path.insert(0, r"C:\Users\Dawn\Desktop\local_reply_engine")
from local_reply.engine import embed

# 域内：T2 最小改写 30 条（bench_chat_v3.1_robust.PARAPHRASE）+ 语料随机抽样
import importlib.util
spec = importlib.util.spec_from_file_location("v31", r"C:\Users\Dawn\Desktop\local_reply_engine\bench_chat_v3.1_robust.py")
# 注意：该脚本 import 时会执行 main？——检查过有 if __name__ 保护则安全；直接读文件更稳
paraphrase = []
import re
txt = open(r"C:\Users\Dawn\Desktop\local_reply_engine\bench_chat_v3.1_robust.py", encoding="utf-8").read()
m = re.search(r"PARAPHRASE\s*=\s*\[(.*?)\]\n", txt, re.S)
for a, b in re.findall(r'\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\)', m.group(1)):
    paraphrase.append(b)

random.seed(7)
corpus_qs = []
import glob
for f in glob.glob(r"C:\Users\Dawn\Desktop\local_reply_engine\local_reply\engine\corpus\mengyao_hq_part*.jsonl"):
    for line in open(f, encoding="utf-8"):
        if line.strip():
            corpus_qs.append(json.loads(line)["conversations"][0]["value"])
corpus_sample = random.sample(corpus_qs, 200)

# OOD：知识/咨询/闲聊但语料外（v3.0 D 类 + 构造）
OOD = [
    "预算三千买什么手机好", "合租好还是整租好", "这个礼物送女生合适吗",
    "你觉得我这个人有什么缺点", "宇宙有多大", "光速是多少", "量子力学讲什么",
    "怎么写快速排序", "Python 和 Java 哪个好", "人民币汇率现在多少",
    "明天会下雨吗", "帮你写个周报", "帮我订明天的闹钟", "把这段翻译成英文",
    "1 加 1 等于几", "地球到月球多远", "怎么退税", "股票开户流程",
    "今天股市行情", "给我讲讲相对论", "怎么办理护照", "房贷利率多少",
    "wifi 速度重要吗", "推荐一台洗碗机", "怎么报游泳班", "地球是圆的吗",
    "怎么修理汽车发动机", "如何申请专利", "讲讲唐朝历史", "什么是区块链",
]

vecs = embed.embed(paraphrase + corpus_sample + OOD)
qs = paraphrase + corpus_sample + OOD
n_p, n_c, n_o = len(paraphrase), len(corpus_sample), len(OOD)
import numpy as np
M = np.array(corpus_qs[:0] or [])  # placeholder
# 索引：全语料向量
idx_vecs = embed.embed(corpus_qs)
MI = np.array(idx_vecs, dtype=np.float32)

def top1(v):
    return float((MI @ np.array(v, dtype=np.float32)).max())

in_scores = [top1(v) for v in vecs[:n_p + n_c]]
ood_scores = [top1(v) for v in vecs[n_p + n_c:]]

def pct(xs, p):
    xs = sorted(xs)
    return xs[int(len(xs) * p)]

print(f"域内({len(in_scores)}): min={min(in_scores):.3f} p1={pct(in_scores,0.01):.3f} p5={pct(in_scores,0.05):.3f} p10={pct(in_scores,0.10):.3f} median={pct(in_scores,0.5):.3f}")
print(f"OOD({len(ood_scores)}): max={max(ood_scores):.3f} p95={pct(ood_scores,0.95):.3f} p99={pct(ood_scores,0.99):.3f} median={pct(ood_scores,0.5):.3f}")
for thr in (0.55, 0.58, 0.60, 0.62, 0.65, 0.68, 0.70):
    rec = sum(1 for s in in_scores if s >= thr) / len(in_scores)
    ood_hit = sum(1 for s in ood_scores if s >= thr) / len(ood_scores)
    print(f"thr={thr}: 域内召回 {rec*100:.1f}%  OOD 误命中 {ood_hit*100:.1f}%")
print("\nOOD 超过 0.65 的句子：")
for q, s in zip(qs[n_p + n_c:], ood_scores):
    if s >= 0.65:
        print(f"  {s:.3f} {q}")
print("\n域内低于 0.65 的句子：")
for q, s in zip(qs[:n_p + n_c], in_scores):
    if s < 0.65:
        print(f"  {s:.3f} {q}")

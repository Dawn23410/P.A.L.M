# -*- coding: utf-8 -*-
"""延迟归因消融：全开 / 关 reranker / 关 coherence / 关两者，同一混合负载对比
+ 单组件耗时（embed / 检索点积 / rerank 单次）
"""
import sys, io, json, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, r"C:\Users\Dawn\Desktop\local_reply_engine")
from local_reply.engine.engine import StitchEngine, FEATURES

QUERIES = [
    "你好", "在吗", "吃了吗", "晚安", "我好累", "好烦啊", "不开心", "想你了",
    "被领导骂了", "房租又涨了", "快递丢件了", "面试完感觉凉了", "养的猫生病了",
    "跟室友吵了一架", "感冒了鼻子堵得慌", "连续加班一周了", "今天穿什么",
    "晚饭吃什么", "周末有啥安排", "推荐个下饭剧呗", "考试挂了", "涨工资了",
    "下冰雹了", "回南天墙壁冒水",
    "今天开了一下午会，脑子嗡嗡的，想听你说说话",
    "刚跟家里通完电话，被催婚了，烦", "外面下雨了，突然有点想你",
]

def bench(eng, label):
    for q in QUERIES:
        eng.respond(q)  # 预热
    lat = []
    for q in QUERIES:
        t0 = time.perf_counter()
        eng.respond(q)
        lat.append((time.perf_counter() - t0) * 1000)
    lat.sort()
    n = len(lat)
    rr = getattr(eng, "_rerank_calls", 0)
    r = {"label": label, "n": n,
         "median": round(lat[n // 2], 1), "p90": round(lat[int(n * 0.9)], 1),
         "max": round(lat[-1], 1), "rerank_calls": rr}
    print(r)
    return r

rows = []

eng = StitchEngine(semantic=True)
rows.append(bench(eng, "full"))

FEATURES["reranker"] = False
rows.append(bench(eng, "no_reranker"))

FEATURES["reranker"] = True
FEATURES["coherence"] = False
rows.append(bench(eng, "no_coherence"))

FEATURES["reranker"] = False
rows.append(bench(eng, "neither"))

FEATURES["reranker"] = True
FEATURES["coherence"] = True

# 单组件：embed 一次 vs 检索一次
from local_reply.engine import embed as emb_mod
t0 = time.perf_counter()
emb_mod.embed(["随便一句话测试性能"])
emb_ms = (time.perf_counter() - t0) * 1000
t0 = time.perf_counter()
for _ in range(20):
    emb_mod.embed(["随便一句话测试性能"])
emb_steady = (time.perf_counter() - t0) / 20 * 1000

t0 = time.perf_counter()
for _ in range(50):
    eng._retrieve_scored("被领导骂了")
ret_ms = (time.perf_counter() - t0) / 50 * 1000

t0 = time.perf_counter()
from local_reply.engine import reranker
reranker.rerank("被领导骂了", [(0, 0.8, "老板骂我"), (1, 0.7, "先顺气，别憋着")], max_len=96)
rr_ms = (time.perf_counter() - t0) * 1000

comp = {"embed_first_ms": round(emb_ms, 1), "embed_steady_ms": round(emb_steady, 1),
        "retrieve_embed_plus_dot_ms": round(ret_ms, 1), "rerank_one_pair_ms": round(rr_ms, 1)}
print(comp)

with open(r"C:\Users\Dawn\Desktop\local_reply_engine\perf_attribution_v1.0.json", "w", encoding="utf-8") as fh:
    json.dump({"ablation": rows, "components": comp}, fh, ensure_ascii=False, indent=2)

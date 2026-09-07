# -*- coding: utf-8 -*-
"""内存分组件测量：mock 档 / 去重排 / 去 T5 / 全血 + ORT arena 策略对比
每个变体独立子进程，避免 arena 残留污染测量。
"""
import sys, io, json, subprocess, time

VENV = r"C:/Users/Dawn/.workbuddy/binaries/python/envs/default/Scripts/python.exe"

CHILD = r'''
import sys, io, json, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, r"C:\Users\Dawn\Desktop\local_reply_engine")
import psutil
proc = psutil.Process()
def mb(): return round(proc.memory_info().rss / 1024 / 1024, 1)

variant = sys.argv[1]
out = {"variant": variant, "python_base_mb": mb()}

from local_reply.engine import reranker, embed as emb_mod

if variant == "mock":
    from local_reply.engine.engine import StitchEngine
    t0 = time.perf_counter()
    eng = StitchEngine()
    out["boot_s"] = round(time.perf_counter() - t0, 2)
    out["boot_mb"] = mb()
    out["mode"] = eng.mode
    eng.respond("我好累"); eng.respond("晚安")
    out["warm_mb"] = mb()
    lat = []
    for q in ("我好累", "晚安", "吃了吗", "被领导骂了"):
        t0 = time.perf_counter(); eng.respond(q); lat.append((time.perf_counter()-t0)*1000)
    lat.sort(); out["mock_median_ms"] = round(lat[len(lat)//2], 1)

elif variant == "semantic_full":
    from local_reply.engine.engine import StitchEngine
    t0 = time.perf_counter()
    eng = StitchEngine(semantic=True)
    out["boot_s"] = round(time.perf_counter() - t0, 2)
    out["boot_mb"] = mb()
    eng.respond("我好累")
    out["warm_mb"] = mb()

elif variant == "no_rerank_warmup":
    reranker.warmup = lambda: None
    from local_reply.engine.engine import StitchEngine
    eng = StitchEngine(semantic=True)
    out["boot_mb"] = mb()
    eng.respond("我好累")
    out["warm_mb"] = mb()
    # 惰性触发一次 rerank 看真实代价
    from local_reply.engine import reranker as rr
    t0 = time.perf_counter()
    rr.rerank("被领导骂了", [(0, 0.8, "老板骂我"), (1, 0.7, "先顺气")], max_len=96)
    out["lazy_rerank_s"] = round(time.perf_counter() - t0, 2)
    out["after_lazy_rerank_mb"] = mb()

elif variant == "no_rerank_no_t5":
    reranker.warmup = lambda: None
    import local_reply.engine.hub as hub
    _orig = hub.Rewriter.available
    hub.Rewriter.available = lambda self: False
    from local_reply.engine.engine import StitchEngine
    eng = StitchEngine(semantic=True)
    out["boot_mb"] = mb()
    eng.respond("我好累")
    out["warm_mb"] = mb()

print(json.dumps(out, ensure_ascii=False))
'''

CASES = {
    "mock": "纯 mock 档",
    "semantic_full": "满血基线",
    "no_rerank_warmup": "去 reranker 预热（惰性）",
    "no_rerank_no_t5": "去 reranker + 去 T5",
}
results = []
for name, desc in CASES.items():
    r = subprocess.run([VENV, "-c", CHILD, name], capture_output=True, text=True, timeout=600)
    try:
        out = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        out = {"variant": name, "error": r.stdout[-200:] + r.stderr[-400:]}
    results.append(out)
    print(desc, "->", json.dumps(out, ensure_ascii=False))

with open(r"C:\Users\Dawn\Desktop\local_reply_engine\mem_tiers_v1.0.json", "w", encoding="utf-8") as fh:
    json.dump(results, fh, ensure_ascii=False, indent=2)

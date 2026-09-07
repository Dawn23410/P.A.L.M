# -*- coding: utf-8 -*-
"""三档对比基准 v1.0：full / balanced / lite
每档独立子进程测量：内存（boot→warm→多轮压力→峰值）、延迟（单轮/多轮）、
T2/T3/T4-56 命中。输出 json 供汇总。
"""
import sys, io, json, subprocess, time

VENV = r"C:/Users/Dawn/.workbuddy/binaries/python/envs/default/Scripts/python.exe"

CHILD = r'''
import sys, io, json, time, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, r"C:\Users\Dawn\Desktop\local_reply_engine")
import psutil, importlib.util
tier = sys.argv[1]
proc = psutil.Process()
def mb(): return round(proc.memory_info().rss/1024/1024, 1)

from local_reply.engine.engine import StitchEngine
out = {"tier": tier, "base_mb": mb()}
t0 = time.perf_counter()
eng = StitchEngine(tier=tier)
out["boot_s"] = round(time.perf_counter() - t0, 2)
out["boot_mb"] = mb()

# 延迟探针（单轮）
probe = ["我好累", "晚安", "吃了吗", "在吗", "讲个笑话", "安慰我",
         "被领导骂了", "今天穿什么", "宇宙有多大", "推荐个电影", "抱抱我", "然后呢"]
lat = []
for q in probe:
    t0 = time.perf_counter(); eng.respond(q); lat.append((time.perf_counter()-t0)*1000)
lat.sort()
out["single_ms"] = {"median": round(lat[len(lat)//2], 1), "p90": round(lat[int(len(lat)*0.9)], 1)}

# 多轮压力（含上文 → full 触发 coherence；观察 balanced 是否内存炸）
mt = ["我今天在公司被领导当说了几句", "也不是什么大事，就是心里堵得慌",
      "你说我是不是太敏感了", "嗯，听你这么说好受多了",
      "对了，你晚上一般干嘛", "那明天再找你聊"]
hist = []
mt_lat = []
for u in mt:
    t0 = time.perf_counter()
    r = eng.respond(u, hist)
    mt_lat.append((time.perf_counter()-t0)*1000)
    hist.append((u, r.get("reply", "")))
out["multi_mb"] = mb()
mt_lat.sort()
out["multi_ms"] = {"median": round(mt_lat[len(mt_lat)//2], 1), "max": round(mt_lat[-1], 1)}
out["peak_mb"] = mb()
out["threads"] = proc.num_threads()

# T2/T3/T4 命中
def load_mod(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
v30 = load_mod("v30", r"C:\Users\Dawn\Desktop\local_reply_engine\bench_chat_v3.0_blind.py")
t2 = re.findall(r'\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\)',
    re.search(r"PARAPHRASE\s*=\s*\[(.*?)\]\n",
        open(r"C:\Users\Dawn\Desktop\local_reply_engine\bench_chat_v3.1_robust.py", encoding="utf-8").read(), re.S).group(1))
t2 = [b for a, b in t2]
t3 = re.findall(r'\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\)',
    re.search(r"FREQ\s*=\s*\[(.*?)\]\n\n",
        open(r"C:\Users\Dawn\Desktop\local_reply_engine\bench_chat_v3.2_freq.py", encoding="utf-8").read(), re.S).group(1))
t3 = [b for a, b in t3]
cq = v30.load_corpus_queries()
cg = [(v30.grams(q), q) for q in cq]
t4 = [q for q in v30.CANDIDATES if q not in set(cq) and v30.max_sim(q, cg)[0] < 0.6]
out["t4_n"] = len(t4)
def hit(q):
    r = eng.respond(q, [])
    return bool(r.get("recall_real")) or (not r.get("suggest_llm") and r.get("mode") == "semantic")
for name, items in (("T2", t2), ("T3", t3), ("T4", t4)):
    hits = sum(1 for q in items if hit(q))
    out[f"{name}_hit"] = f"{hits}/{len(items)}"
print(json.dumps(out, ensure_ascii=False))
'''

results = []
for tier in ("full", "balanced", "lite"):
    r = subprocess.run([VENV, "-c", CHILD, tier], capture_output=True, text=True, timeout=900)
    try:
        out = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        out = {"tier": tier, "error": (r.stdout[-300:] + r.stderr[-400:])}
    results.append(out)
    print(json.dumps(out, ensure_ascii=False))

with open(r"C:\Users\Dawn\Desktop\local_reply_engine\tier_compare_v1.0.json", "w", encoding="utf-8") as fh:
    json.dump(results, fh, ensure_ascii=False, indent=2)

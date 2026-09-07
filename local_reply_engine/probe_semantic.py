# -*- coding: utf-8 -*-
"""语义检索（bge-m3）启用探针 —— P0 验证

1) 核实语料实际加载条数（jsonl 行数 vs unique vs 引擎 records）
2) 构建 bge-m3 稠密索引，测首次构建耗时与缓存命中耗时
3) 抽样对比 mock(lexical) vs semantic 的 top1 命中差异
"""
import sys, glob, json, time, os

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"C:/Users/Dawn/Desktop/local_reply_engine")
from local_reply import StitchEngine
from local_reply.engine import embed as _embed

ENGINE_DIR = r"C:/Users/Dawn/Desktop/local_reply_engine"

# ---- 1) 语料条数核实 ----
raw_lines, raw_q = 0, []
for f in sorted(glob.glob(ENGINE_DIR + "/local_reply/engine/corpus/*.jsonl")):
    for line in open(f, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        raw_lines += 1
        try:
            d = json.loads(line)
        except Exception:
            continue
        for c in d.get("conversations", []):
            if c.get("from") == "human":
                raw_q.append(c.get("value", ""))
print(f"jsonl 行数        : {raw_lines}")
print(f"human 句总数      : {len(raw_q)}")
print(f"去重后            : {len(set(raw_q))}")

eng_mock = StitchEngine()
print(f"引擎 records 条数 : {len(eng_mock.records)}   (mode={eng_mock.mode})")

# 看看被 load_persona_bank 过滤掉的是什么
qs_in_records = [r.get("q", "") for r in eng_mock.records]
print(f"records 内 q 去重 : {len(set(qs_in_records))}")
missing = [q for q in set(raw_q) if q not in set(qs_in_records)]
print(f"未进入 records 的 q: {len(missing)}  样例: {missing[:8]}")

# stitching_corpus 另算
stitch = ENGINE_DIR + "/local_reply/engine/data/stitching_corpus.jsonl"
if os.path.exists(stitch):
    n = sum(1 for _ in open(stitch, encoding="utf-8") if _.strip())
    print(f"data/stitching_corpus.jsonl 行数 : {n}")

# ---- 2) 语义索引构建 ----
print("\n--- bge-m3 语义索引 ---")
print("embed.is_available():", _embed.is_available())
t0 = time.perf_counter()
eng_sem = StitchEngine(semantic=True)
t1 = time.perf_counter()
print(f"构建/加载耗时: {(t1-t0)*1000:.0f} ms   mode={eng_sem.mode}  "
      f"index={0 if eng_sem._sem_index is None else len(eng_sem._sem_index)}  "
      f"阈值={eng_sem.confidence_threshold}")

t0 = time.perf_counter()
eng_sem2 = StitchEngine(semantic=True)
t1 = time.perf_counter()
print(f"二次启动(缓存命中)耗时: {(t1-t0)*1000:.0f} ms   mode={eng_sem2.mode}")

# ---- 3) 抽样对比 ----
PROBE = ["我渴了", "安慰我", "脑袋疼", "好疲惫", "早上好", "你会什么",
         "被领导骂了", "房租又涨了", "刚到家", "周末有啥安排", "我好累", "你好"]
print("\n--- mock vs semantic top1 对比 ---")
for q in PROBE:
    m = eng_mock.respond(q, [])
    s = eng_sem.respond(q, [])
    print(f"\nQ: {q}")
    print(f"  mock    hit={bool(m.get('recall_real'))}  {m.get('reply','')[:52]}")
    print(f"  semantic hit={bool(s.get('recall_real'))}  {s.get('reply','')[:52]}")

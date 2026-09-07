# -*- coding: utf-8 -*-
"""纯聊盲测 v3.10 —— v3.0 候选集 × 当前语料(2705簇) × 产线 semantic 引擎
目的：更新"等效多少 B"口径。先 2-gram≥0.6 剔除已入语料的句子，再跑未见句。
判分（GOOD/WEAK/FAIL）由 AI 逐句盲评，规则同 v3.0：
  GOOD = 贴题 + 人格一致 + 有推进；WEAK = 命中但敷衍/微跑题；FAIL = 兜底/跑题/复读
"""
import sys, json, importlib.util, time, random

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"C:/Users/Dawn/Desktop/local_reply_engine")
from local_reply import StitchEngine

ENGINE_DIR = r"C:/Users/Dawn/Desktop/local_reply_engine"

def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

v30 = _load("v30mod", ENGINE_DIR + "/bench_chat_v3.0_blind.py")  # 只取其函数与 CANDIDATES

random.seed(11)
cq = v30.load_corpus_queries()
cgrams = [(v30.grams(q), q) for q in cq]
cqset = set(cq)

kept, dropped = [], []
for q in v30.CANDIDATES:
    if q in cqset:
        dropped.append((q, "exact", 1.0))
        continue
    sim, near = v30.max_sim(q, cgrams)
    if sim >= 0.6:
        dropped.append((q, near, round(sim, 2)))
    else:
        kept.append(q)

print(f"候选 {len(v30.CANDIDATES)}  剔除(已入语料/高度重合) {len(dropped)}  未见句 {len(kept)}")
for a, b, c in dropped:
    print(f"  [剔除] {a}  ~{b} ({c})")

eng = StitchEngine(semantic=True)
rows = []
for q in kept:
    t0 = time.perf_counter()
    try:
        r = eng.respond(q, [])
    except Exception as e:
        rows.append({"q": q, "error": repr(e)})
        continue
    ms = (time.perf_counter() - t0) * 1000
    rows.append({
        "q": q,
        "recall_real": bool(r.get("recall_real")),
        "fallback": bool(r.get("suggest_llm")),
        "conf": round(float(r.get("confidence") or 0), 3),
        "ms": round(ms, 1),
        "reply": r.get("reply", ""),
    })

out = {
    "candidates": len(v30.CANDIDATES),
    "dropped": len(dropped),
    "kept_unseen": len(kept),
    "rows": rows,
}
with open(ENGINE_DIR + "/bench_result_v3.10.json", "w", encoding="utf-8") as fh:
    json.dump(out, fh, ensure_ascii=False, indent=2)

hit = sum(1 for r in rows if r.get("recall_real"))
fb = sum(1 for r in rows if r.get("fallback"))
print(f"\n未见句 {len(kept)}：命中 {hit}，兜底 {fb}（命中率 {hit/max(1,len(kept))*100:.0f}%）")
print("--- 逐句回复（供盲评） ---")
for r in rows:
    tag = "FB " if r.get("fallback") else ("HIT" if r.get("recall_real") else "REC")
    print(f"[{tag}] {r['q']}")
    print(f"      {r.get('reply', 'ERR')[:110]}")

# -*- coding: utf-8 -*-
"""三档等效评测数据采集：每档 fresh 进程跑 T2/T3/T4-56/T5，落盘逐句回复供盲评。
每个 (query, reply) 只在汇总时判一次，跨档复用判定。"""
import sys, io, json, re, importlib.util, subprocess

VENV = r"C:/Users/Dawn/.workbuddy/binaries/python/envs/default/Scripts/python.exe"
ROOT = r"C:\Users\Dawn\Desktop\local_reply_engine"

CHILD = r'''
import sys, io, json, re, importlib.util, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, r"C:\Users\Dawn\Desktop\local_reply_engine")
tier = sys.argv[1]
from local_reply.engine.engine import StitchEngine
eng = StitchEngine(tier=tier)

def load_mod(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
v30 = load_mod("v30", r"C:\Users\Dawn\Desktop\local_reply_engine\bench_chat_v3.0_blind.py")
t2 = [b for a, b in re.findall(r'\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\)',
    re.search(r"PARAPHRASE\s*=\s*\[(.*?)\]\n",
        open(r"C:\Users\Dawn\Desktop\local_reply_engine\bench_chat_v3.1_robust.py", encoding="utf-8").read(), re.S).group(1))]
t3 = [b for a, b in re.findall(r'\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\)',
    re.search(r"FREQ\s*=\s*\[(.*?)\]\n\n",
        open(r"C:\Users\Dawn\Desktop\local_reply_engine\bench_chat_v3.2_freq.py", encoding="utf-8").read(), re.S).group(1))]
cq = v30.load_corpus_queries()
cg = [(v30.grams(q), q) for q in cq]
t4 = [q for q in v30.CANDIDATES if q not in set(cq) and v30.max_sim(q, cg)[0] < 0.6]

rows = []
for setname, items in (("T2", t2), ("T3", t3), ("T4", t4)):
    for q in items:
        r = eng.respond(q, [])
        rows.append({"set": setname, "q": q,
                     "fallback": bool(r.get("suggest_llm")),
                     "reply": r.get("reply", "")})
# T5 多轮（7 轮，带真实上下文）
mt = ["你好", "我今天在公司被领导当众说了几句", "也不是什么大事，就是心里堵得慌",
      "你说我是不是太敏感了", "嗯，听你这么说好受多了", "对了，你晚上一般干嘛", "那明天再找你聊"]
hist = []
for u in mt:
    r = eng.respond(u, hist)
    rows.append({"set": "T5", "q": u, "fallback": bool(r.get("suggest_llm")),
                 "reply": r.get("reply", ""), "ctx": len(hist)})
    hist.append((u, r.get("reply", "")))
print("@@JSON@@" + json.dumps({"tier": tier, "rows": rows}, ensure_ascii=False))
'''

all_rows = []
for tier in ("full", "balanced", "lite"):
    r = subprocess.run([VENV, "-c", CHILD, tier], capture_output=True, text=True, timeout=900)
    line = next((l for l in r.stdout.splitlines() if l.startswith("@@JSON@@")), None)
    if not line:
        print(tier, "FAILED:", r.stderr[-300:])
        continue
    data = json.loads(line[len("@@JSON@@"):])
    all_rows.append(data)
    n_fb = sum(1 for x in data["rows"] if x["fallback"])
    print(f"{tier}: {len(data['rows'])} 句，兜底 {n_fb}")

with open(ROOT + r"\tier_equiv_data_v1.0.json", "w", encoding="utf-8") as fh:
    json.dump(all_rows, fh, ensure_ascii=False, indent=1)
print("saved tier_equiv_data_v1.0.json")

# -*- coding: utf-8 -*-
"""拟人度抽检探针（多轮）：python sample_probe.py <queries.txt> <seed> <draws>"""
import sys, io, random
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, r"C:\Users\Dawn\Desktop\local_reply_engine")
from local_reply.engine.engine import StitchEngine

qfile, seed, draws = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
CASES = [l.strip() for l in open(qfile, encoding="utf-8") if l.strip()]
random.seed(seed)
eng = StitchEngine(semantic=True)
for q in CASES:
    print("## Q:", q)
    for i in range(draws):
        r = eng.respond(q)
        print(f"  {i+1}.", r.get("reply").replace("\n", " / "))
    print()

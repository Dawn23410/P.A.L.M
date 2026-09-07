# -*- coding: utf-8 -*-
"""语句本身的人机感复检：跑一批固定输入，人工读回复。"""
import sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, r"C:\Users\Dawn\Desktop\local_reply_engine")

from local_reply.engine.engine import StitchEngine

CASES = [
    "今天上班好累啊",
    "我有点想哭",
    "你真可爱",
    "我不开心",
    "真的好想睡觉",
    "周末去哪玩比较好",
    "好饿啊现在",
    "考试挂了，烦死了",
    "今天好热",
    "你真厉害",
    "帮帮我",
    "我分手了",
    "想露营吗",
    "手冻红了",
    "在干嘛",
    "晚安",
]

eng = StitchEngine(semantic=True)
print("engine ready\n")
for q in CASES:
    t0 = time.perf_counter()
    r = eng.respond(q)
    ms = (time.perf_counter() - t0) * 1000
    print(f"[{ms:5.0f}ms] Q: {q}")
    print(f"       A: {r.get('text', r)}")
    print()

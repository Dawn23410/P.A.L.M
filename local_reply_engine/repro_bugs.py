# -*- coding: utf-8 -*-
"""复现三个已知未修 bug：姓名误存 / 通用求助语错配 / 天气误触发"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, r"C:\Users\Dawn\Desktop\local_reply_engine")
from local_reply.engine.engine import StitchEngine

eng = StitchEngine(semantic=True)

print("== bug1 姓名误存 ==")
for q in ("我是不是想太多了", "我是不是很没用", "我是不是该睡了"):
    eng.respond(q)
    print(f"  {q!r} -> name={eng.memory.get('user_name')!r}")
eng.memory["user_name"] = None

print("== bug2 通用求助语 ==")
for q in ("安慰我", "帮帮我", "然后呢", "为什么"):
    r = eng.respond(q)
    print(f"  [{q}] conf={r.get('confidence', 0):.3f} fallback={r.get('suggest_llm')}")
    print(f"    {r.get('reply', '')[:70]}")

print("== bug3 天气误触发 ==")
for q in ("今天好热", "今天好冷", "热死了", "冷死了"):
    r = eng.respond(q)
    print(f"  [{q}] conf={r.get('confidence', 0):.3f}")
    print(f"    {r.get('reply', '')[:70]}")

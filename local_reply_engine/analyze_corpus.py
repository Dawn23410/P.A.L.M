# -*- coding: utf-8 -*-
"""语料结构诊断：四要素覆盖 + 域内漏召回定位。零依赖，系统Python3.10可跑。"""
import sys, glob, os, json, re
sys.path.insert(0, r"C:/Users/Dawn/Desktop/local_reply_engine")
from local_reply import StitchEngine
from local_reply.engine.core import parse_reply, load_persona_bank

eng = StitchEngine()
recs = eng.records
N = len(recs)

# 1) 四要素覆盖统计
fe = {"action": 0, "manner": 0, "inner": 0, "body_only": 0, "full": 0}
for r in recs:
    a = bool(r.get("action"))
    m = bool(r.get("manner"))
    i = bool(r.get("inner"))
    if a: fe["action"] += 1
    if m: fe["manner"] += 1
    if i: fe["inner"] += 1
    if a and m and i: fe["full"] += 1
    if not (a or m or i): fe["body_only"] += 1
print(f"=== 语料 {N} 段 四要素覆盖 ===")
for k, v in fe.items():
    print(f"  {k:10s}: {v:4d}  ({v/N:.1%})")

# 2) 域内漏召回定位（IN_CORPUS 28 条）
IN_CORPUS = [("你好","问候"),("早安","问候"),("午安","问候"),("晚上好","问候"),
    ("作业好多写不完","学习陪伴"),("作业写完了没","学习陪伴"),("考试好难","学习陪伴"),
    ("我好困","状态"),("我好累","状态"),("好无聊啊","状态"),("睡不着","状态"),
    ("今天好开心呀","情绪分享"),("中奖了嘿","情绪分享"),
    ("我很难过","情绪倾诉"),("想哭","情绪倾诉"),("失恋了","情绪倾诉"),
    ("你真讨厌","互动"),("你是谁","互动"),("陪我聊会儿天","陪伴"),
    ("吃饭了吗","日常"),("今天吃什么","日常"),
    ("晚安","道别"),("还没睡呀","道别"),
    ("谢谢","致谢"),("感谢你","致谢"),
    ("想你了","亲昵"),("喜欢你","亲昵"),("爱你哟","亲昵")]
print(f"\n=== IN_CORPUS 命中诊断（阈值={eng.confidence_threshold}）===")
miss = []
for q, topic in IN_CORPUS:
    r = eng.respond(q, [])
    top = r["matches"][0] if r["matches"] else ("(无)", 0)
    flag = "OK " if r["recognized"] else "MISS"
    if not r["recognized"]:
        miss.append((q, topic, top[0], top[1]))
    print(f"  [{flag}] {q:10s} 顶配={top[0][:14]:14s} 分={top[1]:.3f} conf={r['confidence']:.3f}")
print(f"\n漏召回 {len(miss)}/{len(IN_CORPUS)}：")
for q, t, mq, ms in miss:
    print(f"   {q:10s} [{t}] -> 最近语料「{mq[:16]}」分{ms:.3f}")

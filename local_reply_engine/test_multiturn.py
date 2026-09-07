# -*- coding: utf-8 -*-
"""多轮连贯 + 追问处理 诊断（找下一处短板）。零依赖。"""
import sys, random
sys.path.insert(0, r"C:/Users/Dawn/Desktop/local_reply_engine")
from local_reply import StitchEngine

random.seed(7)
eng = StitchEngine()
hist = []

print("=== A. 多轮连贯（看记忆桥接/状态层是否生效）===")
for u in ["你好", "我考试没考好", "好难过", "陪我聊会儿天", "谢谢"]:
    r = eng.respond(u, hist)
    hist.append(r["reply"])
    print(f"你：{u}")
    print(f"梦瑶：{r['reply']}")
    print(f"  [情绪={r['emotion']} | 记忆topics={eng.memory['topics'][-6:]} | 好感={eng.memory['affinity']}]")
    print()

print("=== B. 追问/碎片处理（8B 强项：上下文接续）===")
hist2 = []
for u in ["我养了只猫", "它叫咪咪", "怎么办", "为什么", "然后呢", "它最近老叫"]:
    r = eng.respond(u, hist2)
    hist2.append(r["reply"])
    print(f"你：{u}")
    print(f"梦瑶：{r['reply']}")
    print(f"  [识别={r['recognized']} | 置信={r['confidence']:.3f} | 建议LLM={r['suggest_llm']}]")
    print()

# -*- coding: utf-8 -*-
"""R9 天气泛化验证：变异句 + 重复抽取，检查是否命中 snow/晒被 误配或 fallback"""
import sys, io, random
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, r"C:\Users\Dawn\Desktop\local_reply_engine")
from local_reply.engine.engine import StitchEngine

CASES = [
    ("下冰雹了", ["冰雹砸窗户了", "外面下冰雹好吓人", "天上掉冰雹了"]),
    ("夏天蚊子多", ["被蚊子咬了好多包", "晚上蚊子嗡嗡吵得睡不着", "夏天蚊子太烦了"]),
    ("太阳好晒", ["紫外线超强", "出门被太阳晒得头晕", "今天太阳毒得很"]),
    ("回南天墙壁冒水", ["墙壁都在渗水好潮", "回南天地板全是水"]),
    ("雾霾好严重", ["今天雾霾伸手不见五指", "雾霾天出门要戴口罩"]),
    ("秋燥嗓子干", ["秋天嗓子干得冒烟", "换季嗓子疼"]),
]
BAD = ("堆小雪", "踩雪", "陪你踩，堆", "晒被", "出去踩。")
random.seed(909)
eng = StitchEngine(semantic=True)
fail = 0
for base, variants in CASES:
    for q in [base] + variants:
        hits = []
        for i in range(3):
            r = eng.respond(q)
            rep = r.get("reply") or ""
            if any(b in rep for b in BAD):
                hits.append((i, rep))
            if "……" == rep.strip() or len(rep.strip()) < 4:
                hits.append((i, rep + "  <疑似fallback>"))
        tag = "FAIL" if hits else "ok"
        if hits:
            fail += 1
        print(f"[{tag}] {q}")
        for i, rep in hits:
            print(f"    draw{i+1}: {rep}")
print()
print("R9 generalization:", "PASS" if fail == 0 else f"FAIL ({fail} bad)")

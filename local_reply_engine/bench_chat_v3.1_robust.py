# -*- coding: utf-8 -*-
"""纯聊能力盲测 v3.1 —— 同义改写鲁棒性 + 多轮一致性

v3.0 已暴露：未见句命中率极低。v3.1 回答两个更致命的问题：
  Q1: 把语料里的句子做**同义改写**（换几个字/换语序），还能不能命中？
      → 命中 = 有一定泛化；不命中 = 纯背诵（memorization）。
  Q2: 多轮连续聊天时，上下文承接/指代/不复读能撑几轮？
"""
import sys, json, glob, time

sys.path.insert(0, r"C:/Users/Dawn/Desktop/local_reply_engine")
from local_reply import StitchEngine

ENGINE_DIR = r"C:/Users/Dawn/Desktop/local_reply_engine"

# (语料原句, 同义改写句) —— 改写保持语义一致，只换措辞
PARAPHRASE = [
    ("你好", "你好啊"),
    ("你好", "哈喽"),
    ("早安", "早上好"),
    ("早安", "早啊"),
    ("晚安", "晚安啦"),
    ("我好累", "我好累啊"),
    ("我好累", "累死了"),
    ("我好累", "好疲惫"),
    ("我饿了", "肚子饿了"),
    ("我饿了", "饿死我了"),
    ("想睡觉", "好想睡"),
    ("想睡觉", "困死了"),
    ("谢谢", "谢谢你"),
    ("谢谢", "感谢啦"),
    ("对不起", "抱歉啊"),
    ("我难过", "我好伤心"),
    ("我难过", "心里难受"),
    ("陪我聊会儿天呗", "陪我聊会天"),
    ("陪我聊会儿天呗", "跟我聊聊天嘛"),
    ("讲个笑话", "说个笑话听"),
    ("你在干嘛", "你在做什么"),
    ("今天天气真好", "今天天气不错"),
    ("我头疼", "头好痛"),
    ("我头疼", "脑袋疼"),
    ("作业写完了没", "作业写完了吗"),
    ("我好孤单", "好孤独啊"),
    ("我喜欢你", "我好喜欢你"),
    ("你真可爱", "你好可爱"),
    ("吃饭了吗", "吃了吗"),
    ("今天过得怎么样", "今天怎么样"),
]

MULTITURN = [
    "你好",
    "我今天在公司被领导当众说了几句",
    "也不是什么大事，就是心里堵得慌",
    "你说我是不是太敏感了",
    "嗯，听你这么说好受多了",
    "对了，你晚上一般干嘛",
    "那明天再找你聊",
]


def main():
    eng = StitchEngine()
    print("=== Q1 同义改写鲁棒性（语料原句 → 改写句）===")
    hit = 0
    rows = []
    for orig, para in PARAPHRASE:
        r0 = eng.respond(orig, [])
        r1 = eng.respond(para, [])
        ok0 = bool(r0.get("recall_real"))
        ok1 = bool(r1.get("recall_real"))
        hit += 1 if ok1 else 0
        rows.append({"orig": orig, "para": para, "orig_hit": ok0, "para_hit": ok1,
                     "para_reply": r1.get("reply", "")[:70]})
        print(f"  {'HIT ' if ok1 else 'MISS'} {orig} -> {para}   |  {r1.get('reply','')[:46]}")
    n = len(PARAPHRASE)
    print(f"\n改写命中率: {hit}/{n} = {hit/n:.1%}  （原句命中率作为对照）")
    orig_hits = sum(1 for r in rows if r["orig_hit"])
    print(f"原句命中率: {orig_hits}/{n} = {orig_hits/n:.1%}")

    print("\n=== Q2 多轮上下文承接（7 轮连续）===")
    eng2 = StitchEngine()
    hist = []
    mt = []
    for u in MULTITURN:
        r = eng2.respond(u, hist)
        hist.append((u, r.get("reply", "")))
        mt.append({"u": u, "recognized": r.get("recognized"), "recall_real": r.get("recall_real"),
                   "reply": r.get("reply", "")})
        flag = "OK " if r.get("recall_real") else ("REC" if r.get("recognized") else "FB ")
        print(f"  [{flag}] 用户：{u}")
        print(f"        梦瑶：{r.get('reply','')[:80]}")
    real = sum(1 for m in mt if m["recall_real"])
    replies = [m["reply"] for m in mt]
    print(f"\n多轮真实命中: {real}/{len(mt)}   去重率: {len(set(replies))/len(replies):.2f}")

    out = {"paraphrase": {"n": n, "para_hit": hit, "para_rate": round(hit / n, 3),
                          "orig_hit": orig_hits, "orig_rate": round(orig_hits / n, 3),
                          "rows": rows},
           "multiturn": {"n": len(mt), "real_hit": real,
                         "distinct_rate": round(len(set(replies)) / len(replies), 3),
                         "rows": mt}}
    with open(ENGINE_DIR + "/bench_result_v3.1.json", "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()

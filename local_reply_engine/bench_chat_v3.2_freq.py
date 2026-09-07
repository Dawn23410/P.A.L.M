# -*- coding: utf-8 -*-
"""纯聊能力盲测 v3.2 —— 真实高频聊天句覆盖测试

v3.0 的未见句偏难（新情境/需常识），会低估真实体验。
v3.2 换成**中国用户 IM 真实高频句**（不刁难，就是日常会打出来的），
这才是"日常聊天体验"的代理指标。同时标注每条的意图类别。
"""
import sys, json

sys.path.insert(0, r"C:/Users/Dawn/Desktop/local_reply_engine")
from local_reply import StitchEngine

ENGINE_DIR = r"C:/Users/Dawn/Desktop/local_reply_engine"

# (类别, 句子) —— 真实 IM 高频，不做刁难
FREQ = [
    ("寒暄", "在吗"), ("寒暄", "干嘛呢"), ("寒暄", "吃了吗"), ("寒暄", "睡了吗"),
    ("寒暄", "我回来了"), ("寒暄", "我去洗澡了"), ("寒暄", "我起床了"),
    ("状态", "好无聊"), ("状态", "好困"), ("状态", "好累"), ("状态", "难受"),
    ("状态", "我饿了"), ("状态", "我渴了"), ("状态", "我想睡觉"),
    ("状态", "我又熬夜了"), ("状态", "头好晕"), ("状态", "我又胖了"),
    ("情绪", "心好累"), ("情绪", "没人懂我"), ("情绪", "好孤独"),
    ("情绪", "我好烦"), ("情绪", "活着好累"), ("情绪", "不开心"),
    ("关系", "想你"), ("关系", "喜欢你"), ("关系", "陪我聊聊"),
    ("关系", "夸夸我"), ("关系", "安慰我"), ("关系", "帮帮我"),
    ("互动", "晚安"), ("互动", "早安"), ("互动", "谢谢"), ("互动", "对不起"),
    ("互动", "真的假的"), ("互动", "然后呢"), ("互动", "为什么"),
    ("互动", "你说呢"), ("互动", "讲个故事"), ("互动", "唱首歌"),
    ("问答", "你几岁"), ("问答", "你叫什么"), ("问答", "你是谁"),
    ("问答", "你会什么"), ("问答", "你家在哪"),
    ("环境", "今天好热"), ("环境", "今天好冷"), ("环境", "下雨了"),
    ("日常", "作业好多"), ("日常", "考试好难"), ("日常", "工作好烦"),
    ("日常", "老板真烦"), ("日常", "工资好低"), ("日常", "我想辞职"),
    ("日常", "我不想上班"), ("日常", "我感冒了"), ("日常", "周末干嘛"),
]


def main():
    eng = StitchEngine()
    rows, by_cat = [], {}
    for cat, q in FREQ:
        r = eng.respond(q, [])
        ok = bool(r.get("recall_real"))
        rows.append({"cat": cat, "q": q, "hit": ok, "reply": r.get("reply", "")[:80]})
        d = by_cat.setdefault(cat, [0, 0])
        d[1] += 1
        d[0] += 1 if ok else 0
        print(f"  [{'OK ' if ok else 'FB '}] {q}  ->  {r.get('reply','')[:50]}")

    n = len(FREQ)
    hit = sum(1 for r in rows if r["hit"])
    print(f"\n=== 高频句总命中: {hit}/{n} = {hit/n:.1%} ===")
    for cat, (h, t) in sorted(by_cat.items()):
        print(f"  {cat}: {h}/{t} = {h/t:.0%}")

    with open(ENGINE_DIR + "/bench_result_v3.2.json", "w", encoding="utf-8") as fh:
        json.dump({"n": n, "hit": hit, "rate": round(hit / n, 3),
                   "by_cat": {k: {"hit": v[0], "n": v[1]} for k, v in by_cat.items()},
                   "rows": rows}, fh, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()

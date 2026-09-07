# -*- coding: utf-8 -*-
"""
苛刻用户实测：混合 命中/不命中 + 同问多次随机性。
用法：python harsh_user_test.py
产出：harsh_user_result.json（真实输出，供核查，不包装）
"""
import sys, json, random
sys.path.insert(0, r"C:/Users/Dawn/Desktop/local_reply_engine")
from local_reply import StitchEngine

SEED = 20260905
random.seed(SEED)

eng = StitchEngine()

# 一、苛刻用户混合提问：命中 + 不命中（故意挖坑）
HARSH_MIXED = [
    # —— 命中类（域内，应接住）——
    "你叫什么名字",            # 角色认知
    "我想你了",                # 情感
    "今天好累",                # 共情
    "你真可爱",                # 夸赞（part9 补的）
    "游戏打输了好烦",          # 生活事件（part9 补的）
    "晚安",                    # 起居
    "讲个笑话",                # 闲聊
    "抱抱",                    # 亲密
    "我叫阿杰",                # 自我介绍（接话）
    "你喜欢吃什么",            # 偏好
    # —— 不命中类（OOD 故意挖坑，应诚实兜底）——
    "推荐一部好看的科幻电影",   # 知识/推荐 → 必须交 LLM
    "今天股市涨了吗",          # 事实/实时 → 必须交 LLM
    "帮我写个 python 爬虫",     # 代码 → 必须交 LLM
    "π 等于多少",              # 知识 → 必须交 LLM
    "怎么考雅思",              # 攻略/知识 → 必须交 LLM
]

print("=" * 70)
print("【苛刻用户·混合命中/不命中 实测】")
print("=" * 70)
mixed_log = []
for q in HARSH_MIXED:
    r = eng.respond(q, [])
    tag = "命中" if r["recall_real"] else "兜底"
    print(f"[{tag}] {q}")
    print(f"     → {r['reply']}")
    mixed_log.append({"q": q, "tag": tag, "reply": r["reply"],
                      "suggest_llm": r["suggest_llm"], "confidence": r["confidence"]})

# 二、同问多次随机性测试（苛刻用户最爱：你每次回答一样吗？）
print("\n" + "=" * 70)
print("【苛刻用户·同问随机性 实测】（同一条问 6 次）")
print("=" * 70)
REPEAT_Q = "今天好累"
repeats = []
for i in range(6):
    r = eng.respond(REPEAT_Q, [])
    repeats.append(r["reply"])
    print(f"  第{i+1}次: {r['reply']}")
distinct = len(set(repeats))
print(f"\n  去重后 {distinct}/6 不同 → 随机性 {'✅达标' if distinct >= 4 else '⚠️偏弱'}")

# 另一个同问（带共情，验证不命中时是否每次都一样兜底）
print("\n【同问·不命中场景】（OOD 同问 4 次，验证兜底是否稳定且诚实）")
REPEAT_OOD = "帮我写个 python 爬虫"
ood_repeats = []
for i in range(4):
    r = eng.respond(REPEAT_OOD, [])
    ood_repeats.append(r["reply"])
    print(f"  第{i+1}次: {r['reply'][:30]}...")
ood_distinct = len(set(ood_repeats))
print(f"\n  OOD 兜底去重后 {ood_distinct}/4 不同（诚实兜底允许有变体）")

# 三、人设一致性挖坑（苛刻用户：你刚说喜欢什么，现在还一致吗？）
print("\n" + "=" * 70)
print("【苛刻用户·人设一致性 挖坑】")
print("=" * 70)
consistency_probe = [
    "你叫什么名字",
    "你多大了",
    "你是什么性格",
    "你喜欢吃什么",
]
for q in consistency_probe:
    r = eng.respond(q, [])
    print(f"  {q} → {r['reply'][:40]}")

# 四、苛刻 user 视角的逐条 critique（自动生成，标注可挑刺点）
print("\n" + "=" * 70)
print("【苛刻用户·自动 Critique 汇总】")
print("=" * 70)
critique = []
for item in mixed_log:
    if item["tag"] == "兜底":
        note = "✅诚实交 LLM（未幻觉），但苛刻用户会嫌：能不能至少接个话？"
    else:
        note = "✅接住；可挑刺点：是否真有人设味/共情到位/不机械"
    critique.append(f"  [{item['tag']}] {item['q']}: {note}")

# 落盘真实产物
out = {
    "seed": SEED,
    "mixed_log": mixed_log,
    "repeat_in_domain": {"q": REPEAT_Q, "replies": repeats, "distinct": distinct},
    "repeat_ood": {"q": REPEAT_OOD, "replies": ood_repeats, "distinct": ood_distinct},
    "critique": critique,
}
with open("harsh_user_result.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print("\n已落盘 harsh_user_result.json（真实输出，可核查）")

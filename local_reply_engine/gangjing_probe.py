# -*- coding: utf-8 -*-
"""杠精探针：以「本地 mock 兜底」定位，专戳检索缝合桩的先天死穴。真实运行。"""
import sys, json, random
sys.path.insert(0, r"C:/Users/Dawn/Desktop/local_reply_engine")
from local_reply import StitchEngine

random.seed(666)
eng = StitchEngine()

def show(title, qs, fresh=False):
    print("\n" + "=" * 64)
    print(title)
    print("=" * 64)
    e = StitchEngine() if fresh else eng
    for q in qs:
        r = e.respond(q, [])
        tag = "命中" if r["recall_real"] else "兜底"
        print(f"[{tag}] {q}\n    → {r['reply']}")

# 1) 情感事件覆盖死穴：陪伴最值钱的恰恰是不在语料的
show("【杠点1】情感生活事件——检索 mock 的先天死穴（不在语料就甩LLM）",
     ["我分手了", "我失业了", "我失眠了", "我奶奶走了", "我考试又没过", "我被朋友背叛了"])

# 2) 近义 lexical 误配：闲聊近义会不会错配（之前只防了知识类）
show("【杠点2】近义翻车——'喜欢你' vs '喜欢吃' / '真好' vs '天气真好'",
     ["我好喜欢你", "我好喜欢吃火锅", "你人真好", "今天天气真好呀", "我讨厌你了", "我讨厌吃香菜"])

# 3) 语义答为所问错位：检索命中但语义不对
show("【杠点3】答非所问——'睡不着'会不会命中'晚安'然后叫你睡",
     ["我睡不着", "我一点都不困", "我不想睡", "陪我熬夜"])

# 4) 指代/省略长句崩：只做了≤6字碎片续接
show("【杠点4】代词省略——有锚点 vs 无锚点",
     ["我养了只猫", "它叫咪咪，超可爱的", "它平时爱干嘛", "它呢", "那个呢"])

# 5) 兜底复读机：连续不同 OOD 是否每次都甩同一套话术
print("\n" + "=" * 64)
print("【杠点5】兜底复读机——连甩 5 个不同 OOD 看话术是否机械")
print("=" * 64)
for q in ["今天比特币涨了吗", "帮我写首古诗", "地球为什么是圆的", "推荐个旅游地", "怎么学钢琴"]:
    r = eng.respond(q, [])
    print(f"  {q} → {r['reply'][:38]}")

# 6) 假多样：同问 6 次，看 a_raw 前缀(骨架)是否每次一模一样
print("\n" + "=" * 64)
print("【杠点6】假多样——'今天好累'连问6次，骨架(动作/神态/内心)锁死?")
print("=" * 64)
import re
spines = []
for i in range(6):
    r = eng.respond("今天好累", [])
    # 提取四要素前缀（动作/神态/内心）作为骨架
    m = re.match(r"^([\[（<][^\]）>]*[\]）>]\s*)+", r["reply"])
    spine = m.group(0) if m else r["reply"][:20]
    spines.append(spine)
    print(f"  第{i+1}次骨架: {spine!r}")
print(f"  骨架去重: {len(set(spines))}/6  → {'真·多样' if len(set(spines))>=4 else '骨架锁死(假多样)'}")

# 7) 人设锁死不是真一致：用户骂人/叫滚，是否还黏
show("【杠点7】人设锁死边界——用户发火/骂人，引擎破功吗",
     ["滚", "你烦死了", "闭嘴", "你个笨蛋猫"], fresh=True)

# 8) 自我介绍边界
show("【杠点8】自我介绍边界——'叫我小杰就行'会不会只记第一个",
     ["我叫阿杰", "但是我让你叫我小杰就行", "你刚才叫我什么来着"], fresh=True)

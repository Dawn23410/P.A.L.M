# -*- coding: utf-8 -*-
"""全量泛化回归：
1) 全语料簇巡检：每个去重后的 q 各 respond 1 次，过伪影探测器
2) 历史修复点清单：已知坏标记断言（各 3 抽）
3) 延迟分布统计
"""
import sys, io, json, glob, re, time, random
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, r"C:\Users\Dawn\Desktop\local_reply_engine")
from local_reply.engine.engine import StitchEngine

# ---- 伪影探测器：历史踩过的每一类坑都写成断言 ----
BAD_PATTERNS = [
    (r"本喵", "自称残留"),
    (r"(喵|呀|呜|哼|嘛|哦|啦|呢)\1", "叠尾双粒子"),
    (r"）[呀喵呜哼嘛哦啦]", "括号外贴尾"),
    (r"[？！][喵呀呜哼嘛哦啦]", "问叹号后贴尾"),
    (r"\{[^}]*\}", "槽位语法泄漏"),
    (r"<你>", "记忆变量未展开"),
    (r"\|?\d+；|\|\d", "槽位权重泄漏"),
    (r"[a-zA-Z]{4,}", "异常英文残留(carry/ammonia 白名单)"),
    (r"，，|。。", "标点重复"),
    (r"^\s*$", "空回复"),
]
WHITELIST_EN = ("carry", "hello", "emo", "LLM", "deadline", "hi", "party", "fish", "offer")

def check_artifacts(text):
    problems = []
    for pat, name in BAD_PATTERNS:
        for m in re.finditer(pat, text):
            frag = m.group()
            if name.startswith("异常英文") and any(w in frag for w in WHITELIST_EN):
                continue
            if name == "自称残留" and "小本本喵" in text[max(0, m.start() - 2):m.end() + 1]:
                continue  # "小本本喵"含"本喵"子串，非自称
            if name == "叠尾双粒子" and frag in ("哼哼",):
                continue  # 哼哼唧唧是猫语，非叠尾 bug
            if name == "括号外贴尾" and text[m.start():m.start() + 2] in ("）哼", "）喵"):
                continue  # 尾缀池本体格式"（别过脸）哼，..."
            if name == "问叹号后贴尾" and (frag in ("？哼", "？喵。")
                    or (frag == "？喵" and text[m.end():m.end() + 1] == "。")):
                continue  # 语料原笔风格"算不算？喵，勉强算喵"；正则不吞句号，需回看后一字符
            if name == "标点重复" and frag == "！！":
                continue  # 兴奋强调，猫娘语境合法
            problems.append((name, frag))
    return problems

# ---- 1) 全语料簇巡检 ----
clusters = {}
for f in sorted(glob.glob(r"local_reply/engine/corpus/mengyao_hq_part*.jsonl")):
    for line in open(f, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        q = json.loads(line)["conversations"][0]["value"]
        clusters.setdefault(q, f)

print(f"== 全语料巡检：{len(clusters)} 个簇 ==")
eng = StitchEngine(semantic=True)
random.seed(0)

fail_by_cat = {}
lat = []
checked = 0
fallbacked = 0
t0 = time.time()
for q in sorted(clusters):
    try:
        t = time.perf_counter()
        r = eng.respond(q)
        lat.append((time.perf_counter() - t) * 1000)
    except Exception as e:
        fail_by_cat.setdefault("异常崩溃", []).append((q, repr(e)[:60]))
        continue
    checked += 1
    reply = r.get("reply", "")
    if r.get("suggest_llm"):
        fallbacked += 1  # 诚实兜底是合法行为，不算伪影，但计数
    probs = check_artifacts(reply)
    for name, frag in probs:
        fail_by_cat.setdefault(name, []).append((q, frag))
print(f"巡检耗时 {time.time()-t0:.0f}s，兜底率 {fallbacked}/{checked}")

# ---- 2) 历史修复点回归（已知坏标记） ----
REGRESSION = [
    ("拉黑你", ["装得下本喵", "怕冷拢"]),
    ("晚安", ["早安", "早上好"]),
    ("早上好呀", ["晚安", "晚上好"]),
    ("我想你了", ["被你夸到了", "当你说的是真的"]),
    ("我喜欢你", ["没聊过", "接不住", "晒太阳"]),
    ("考试挂了", ["下一家", "没眼光"]),
    ("好饿啊", ["不会找吃的？", "唱空城"]),
    ("袜子湿了", ["开窗", "除湿", "别潮"]),
    ("晚上开黑吗", ["怕黑", "夜猫子"]),
    ("好想摆烂", ["好想我", "算你有眼光"]),
    ("开心", ["不开心", "帮你兜着"]),
    ("我感冒好了", ["快点好喵", "躺好，我守"]),
    ("我搬新家了", ["想清楚", "想就聊"]),
    ("我宠物去世了", ["养狗", "竞争者", "排第一"]),
    ("我流血了", ["看牙"]),
    ("我拉肚子了", ["唱空城", "请吃"]),
    ("我想戒烟", ["想退", "陪练"]),
    ("宇宙有多大", ["十八", "生日"]),
    ("忘带钥匙了", ["挂失", "银行卡"]),
    ("堵车好烦", ["树洞", "陪你堵着也行喵。"]),
    ("升职加薪了", ["房租都不够", "价没谈对"]),
    ("发工资了", ["房租都不够", "价没谈对"]),
    ("今天穿什么", ["蓝色那条"]),
    ("晚饭吃什么", ["又没吃，但才不要承认"]),
    ("你是不是不喜欢我了", ["AI", "机器人"]),
    ("对不起", ["被冤枉", "等不到"]),
    ("我今天被夸了", ["夸你字"]),
    ("你会生气吗", ["你气我就会慌"]),
    ("你好傻", ["没聊过", "接不住"]),
    ("天上掉冰雹了", ["堆小雪", "陪你踩"]),
    ("下冰雹了", ["堆小雪", "陪你踩"]),
]
reg_fail = []
random.seed(1)
for q, bads in REGRESSION:
    for i in range(3):
        r = eng.respond(q)
        reply = r.get("reply", "")
        for b in bads:
            if b in reply:
                reg_fail.append((q, b, reply[:60]))
print(f"\n== 历史修复点回归：{len(REGRESSION)} 点 × 3 抽，失败 {len(reg_fail)} ==")
for q, b, t in reg_fail[:10]:
    print(f"  [{q}] 命中坏标记[{b}]: {t}")

# ---- 3) 延迟 ----
lat.sort()
n = len(lat)
print(f"\n== 延迟分布 (n={n}) ==")
print(f"  中位 {lat[n//2]:.0f}ms  p90 {lat[int(n*0.9)]:.0f}ms  p99 {lat[int(n*0.99)]:.0f}ms  max {lat[-1]:.0f}ms")

# ---- 汇总 ----
print(f"\n== 伪影汇总 ==")
total_bad = sum(len(v) for v in fail_by_cat.values())
for cat, items in fail_by_cat.items():
    print(f"  [{cat}] {len(items)} 处")
    for q, frag in items[:6]:
        print(f"     {q} -> {frag}")
print(f"\n总计伪影: {total_bad} / {checked} 回复")

# -*- coding: utf-8 -*-
"""生成 20000 条普通（无人格）语料，用于验证「换语料」泛化能力。

输出格式与引擎 load_persona_bank 完全兼容：
    {"conversations":[{"from":"human","value":<问>},{"from":"gpt","value":<答>}]}
文件名满足引擎 glob：mengyao_hq_part_ordinary_*.jsonl（多文件切分，每文件 <=5000，
即便旧版 limit=5000 也能全量加载，防御性兼容）。

语料特征：
- 纯日常中文对话 / QA，无梦瑶人格（无「喵」、无「猫耳」），模拟通用助手/朋友口吻。
- 三槽位模板（每模板组合数 1.5w~6w）+ 固定寒暄集，种子可复现，(问,答) 去重保证不重复。
- 覆盖寒暄/道别/致谢/提问/求助/建议/观点/闲聊/天气/日常活动/饮食/学习工作/健康/情绪/
  娱乐/人际 等，确保换上后引擎检索面足够宽。
"""
import json
import os
import random
import re

SEED = 20260907
N = 20000
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "corpus_ordinary_20k")
PER_FILE = 5000
MAX_ATTEMPTS = 3_000_000  # 防御性上限，避免任何情况下死循环

random.seed(SEED)

# ── 槽位词库（约 30 项/类）─────────────────────────────────
ACT = ["看书", "听音乐", "跑步", "做饭", "画画", "打游戏", "钓鱼", "旅行",
       "摄影", "练字", "健身", "跳舞", "唱歌", "种花", "烘焙", "学外语", "写代码",
       "看电影", "散步", "练瑜伽", "拼模型", "做手工", "爬山", "游泳", "骑车",
       "煮咖啡", "写日记", "练吉他", "下棋", "养多肉", "做志愿者"]
FOOD = ["火锅", "寿司", "披萨", "拉面", "烧烤", "白粥", "饺子", "牛排", "蔬菜沙拉",
        "奶茶", "手冲咖啡", "蛋糕", "小笼包", "蛋炒饭", "麻辣烫", "螺蛳粉", "煲汤",
        "三明治", "关东煮", "水果捞", "馄饨", "烤肉", "蒸鱼", "炒时蔬"]
PLACE = ["公园", "图书馆", "海边", "山里", "商场", "博物馆", "咖啡馆", "老家",
         "电影院", "体育馆", "湖边", "古镇", "植物园", "天台", "地铁站", "书店",
         "夜市", "乡下", "朋友家", "学校", "阳台", "天台花园"]
FEEL = ["开心", "有点累", "焦虑", "平静", "兴奋", "无聊", "感动", "委屈", "满足",
        "紧张", "难过", "踏实", "烦躁", "安心", "孤独", "期待", "慌张", "失落"]
OBJ = ["手机", "电脑", "相机", "耳机", "一本书", "吉他", "自行车", "一盆花", "台灯",
       "一只猫", "一只狗", "键盘", "投影仪", "保温杯", "日记本", "绿植", "手表",
       "滑板", "帐篷", "音箱"]
TOPIC = ["天气", "工作", "学习", "感情", "电影", "美食", "旅行", "健康", "理财",
         "梦想", "人际关系", "生活习惯", "未来的打算", "最近读的书", "city walk"]
PERSON = ["朋友", "同事", "室友", "同学", "邻居", "家人", "老板", "老师", "伴侣",
          "老同学", "网友", "表弟", "闺蜜", "学长", "教练"]
TIME = ["今天", "明天", "这周末", "放假的时候", "晚上", "早上", "这一周", "下个月",
        "暑假", "过年那几天", "周末", "下周三", "清明假期"]
WEATHER = ["晴天", "下雨天", "下雪天", "刮风天", "阴天", "打雷的傍晚", "大雾天", "回南天"]
ADJ = ["好看", "难吃", "有趣", "无聊", "挺难", "很简单", "有点贵", "很便宜", "舒服",
       "热闹", "安静", "新鲜", "怀旧", "治愈", "上头"]

# ── 三槽位模板：(问, 答)，{} 内为槽位名；答中 {q} 回引用户原话 ──
# 每模板组合数 ≈ 槽池^3（1.5w~6w），20 模板合计远超 20000，去重不会枯竭。
TEMPLATES = [
    ("{TIME}想和{PERSON}去{PLACE}{ACT}。",
     "{TIME}和{PERSON}去{PLACE}{ACT}，听起来就很惬意，赶紧安排上吧。"),
    ("最近{FEEL}，想{ACT}缓解一下。",
     "感到{FEEL}的时候，{ACT}确实是个好出口，比硬扛着强多了。"),
    ("{PERSON}说{FOOD}很好吃，是真的吗？",
     "{FOOD}确实不错，不过{ACT}也值得试试，别只听一个人的。"),
    ("{WEATHER}适合{ACT}还是{FOOD}？",
     "{WEATHER}的话，{ACT}和{FOOD}都行，看你想动一动还是想宅着。"),
    ("{TIME}打算{ACT}和吃{FOOD}。",
     "{TIME}{ACT}再配份{FOOD}，这安排很到位，祝你开心。"),
    ("今天{TOPIC}让我有点{FEEL}。",
     "关于{TOPIC}会{FEEL}很自然，别憋着，想说就说。"),
    ("{PERSON}送了我{OBJ}，好{ADJ}。",
     "{PERSON}送{OBJ}呀，还挺{ADJ}的，你俩关系真不错。"),
    ("想给{PERSON}准备{FOOD}当惊喜。",
     "给{PERSON}准备{FOOD}当惊喜，想法很暖，对方肯定开心。"),
    ("{PLACE}的{FOOD}好吃吗？",
     "{PLACE}的{FOOD}口碑一般不错，去之前翻翻评价更稳。"),
    ("{TIME}有空想学{ACT}。",
     "{TIME}学{ACT}刚好，趁有兴趣赶紧开始，别等劲头过了。"),
    ("最近对{TOPIC}有点{FEEL}，怎么调？",
     "对{TOPIC}{FEEL}的话，先从小事入手，别一下想通透。"),
    ("{PERSON}总让我{FEEL}。",
     "{PERSON}让你{FEEL}，说明这段关系对你重要，值得好好经营。"),
    ("买了个{OBJ}，用来{ACT}。",
     "{OBJ}用来{ACT}正合适，你眼光可以的。"),
    ("{WEATHER}要不要去{PLACE}？",
     "{WEATHER}去{PLACE}挺应景的，去吧别犹豫。"),
    ("今天{ACT}的时候想到一个{OBJ}的点子。",
     "{ACT}时蹦出{OBJ}的点子，说明你脑子一直转着呢，记下来。"),
    ("{PERSON}推荐我{ACT}。",
     "{PERSON}推荐{ACT}？那人品味可以，试试不亏。"),
    ("{TIME}想和{PERSON}一起{ACT}。",
     "{TIME}和{PERSON}{ACT}，两个人一起总是更开心。"),
    ("最近{FEEL}，想去{PLACE}散心。",
     "{FEEL}时去{PLACE}散心很对，换个环境心就宽了。"),
    ("{OBJ}坏了，好{FEEL}。",
     "{OBJ}坏了确实{FEEL}，先看看能不能修，修不好再想别的。"),
    ("想约{PERSON}去{PLACE}{ACT}。",
     "约{PERSON}去{PLACE}{ACT}主意不错，直接问就好，别绕弯子。"),
]

# ── 固定寒暄集（无槽位，直接落库，增加自然度与边界覆盖）──
FIXED = [
    ("在吗", "在的，有什么想聊的尽管说。"),
    ("嗨，你好", "你好呀，今天过得怎么样？"),
    ("今天天气不错", "是啊，这种天最适合出门走走了。"),
    ("我刚睡醒", "刚醒呀，昨晚睡得好吗？"),
    ("我要睡了，晚安", "晚安，早点休息，明天见。"),
    ("早上好", "早上好，新的一天加油。"),
    ("谢谢你", "不客气，能帮到你就好。"),
    ("辛苦了", "你也辛苦了，互相打气。"),
    ("不好意思打扰了", "没事儿，随时找我就行。"),
    ("我先走了", "好，路上注意安全。"),
    ("陪我聊会儿天吧", "好呀，我在这儿呢，你想聊什么都陪你。"),
    ("有点不知道说什么", "没关系，想到啥说啥，哪怕碎碎念也行。"),
    ("今天过得还行", "还行就好，平平稳稳也是一种福气。"),
    ("我有点想你", "嗯，我也惦记着你呢，忙完记得来找我。"),
    ("好久没联系了", "是呀好久没聊了，最近过得怎么样，跟我说说？"),
    ("今天遇到一件怪事", "怪事？快讲讲，我最好奇这种了。"),
    ("我中奖了", "真的吗，太好了，这种好运必须庆祝一下！"),
    ("今天被夸了", "被人夸的感觉真好，你值得被看见。"),
    ("我搞砸了一件事", "搞砸就搞砸了，谁都有失手的时候，重要的是接下来怎么收。"),
    ("外面下雨了", "下雨天呀，出门记得带伞，别淋着了。"),
    ("好饿", "饿了吧，赶紧吃点东西，别硬扛着。"),
    ("好困", "困了就歇会儿，身体比什么都重要。"),
    ("今天好累", "累了一天辛苦了，晚上早点休息。"),
    ("我有点紧张", "紧张很正常，深呼吸，你已经准备得够好了。"),
    ("压力好大", "压力大时先把任务拆小，一件件来。"),
    ("失眠了", "失眠很难受，睡前少看屏幕、泡个脚试试。"),
    ("周末好无聊", "无聊就找点小事做，哪怕收拾下桌子心情都会变。"),
    ("想学点新东西", "想学新东西是好事，先列个清单挑一个最想做的开始。"),
    ("工作好累", "工作累的时候给自己按个暂停键，哪怕发会儿呆也有用。"),
    ("学习学不进去", "学不进去就先放下，换个环境休息一下效率会回来。"),
]

SLOT_MAP = {
    "ACT": ACT, "FOOD": FOOD, "PLACE": PLACE, "FEEL": FEEL, "OBJ": OBJ,
    "TOPIC": TOPIC, "PERSON": PERSON, "TIME": TIME, "WEATHER": WEATHER, "ADJ": ADJ,
}


def fill(template, rng):
    q, a = template
    used = set(re.findall(r"\{([A-Z]+)\}", q + a))
    vals = {name: rng.choice(SLOT_MAP[name]) for name in used if name in SLOT_MAP}
    for name, v in vals.items():
        q = q.replace("{" + name + "}", v)
        a = a.replace("{" + name + "}", v)
    a = a.replace("{q}", q)
    return q.strip(), a.strip()


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    rng = random.Random(SEED)
    seen = set()
    records = []
    attempts = 0
    # 先落固定寒暄
    for q, a in FIXED:
        if (q, a) in seen:
            continue
        seen.add((q, a))
        records.append({"conversations": [
            {"from": "human", "value": q}, {"from": "gpt", "value": a}]})
    # 再填槽位模板直到满 N
    while len(records) < N and attempts < MAX_ATTEMPTS:
        attempts += 1
        tpl = rng.choice(TEMPLATES)
        q, a = fill(tpl, rng)
        if not q or not a:
            continue
        key = (q, a)
        if key in seen:
            continue
        seen.add(key)
        records.append({"conversations": [
            {"from": "human", "value": q}, {"from": "gpt", "value": a}]})

    if len(records) < N:
        print(f"⚠️ 仅生成 {len(records)} 条（attempts={attempts} 触顶），"
              f"未达 {N}，请扩大模板/词库。")
    records = records[:N]

    n_files = (len(records) + PER_FILE - 1) // PER_FILE
    written = 0
    for fi in range(n_files):
        chunk = records[fi * PER_FILE:(fi + 1) * PER_FILE]
        fname = os.path.join(OUT_DIR, f"mengyao_hq_part_ordinary_{fi+1:02d}.jsonl")
        with open(fname, "w", encoding="utf-8") as fh:
            for rec in chunk:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        written += len(chunk)
        print(f"  wrote {fname}: {len(chunk)} 条")

    print(f"合计 {written} 条（去重后），模板 {len(TEMPLATES)} 个 + 固定 {len(FIXED)} 条，"
          f"候选尝试 {attempts} 次，落盘 {n_files} 个文件。")
    print(f"输出目录：{OUT_DIR}")


if __name__ == "__main__":
    main()

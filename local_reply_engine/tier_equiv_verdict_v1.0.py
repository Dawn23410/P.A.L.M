# -*- coding: utf-8 -*-
"""三档等效判定汇总：tier_equiv_collect 逐句人工盲评结果的编码与加权计算。
判定键：q -> {tier: G/W/F}（F 含兜底与错配假阳性）。"""
import sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

V = {
# ── T2（30）──
"你好啊": "GGG", "哈喽": "GFF", "早上好": "GFF", "早啊": "GGG", "晚安啦": "GGG",
"我好累啊": "GGG", "累死了": "GGF", "好疲惫": "WGF", "肚子饿了": "GGG", "饿死我了": "GGF",
"好想睡": "GGG", "困死了": "GGG", "谢谢你": "GGG", "感谢啦": "GGG", "抱歉啊": "WFF",
"我好伤心": "GGG", "心里难受": "GGG", "陪我聊会天": "GGG", "跟我聊聊天嘛": "GGF",
"说个笑话听": "GGG", "你在做什么": "GGF", "今天天气不错": "GGF", "头好痛": "GGF",
"脑袋疼": "FFF", "作业写完了吗": "GGG", "好孤独啊": "GGG", "我好喜欢你": "GGG",
"你好可爱": "GFG", "吃了吗": "GGG", "今天怎么样": "FGG",
# ── T3（56）──
"在吗": "GGG", "干嘛呢": "GGG", "睡了吗": "GGG", "我回来了": "GGG", "我去洗澡了": "FGG",
"我起床了": "GGG", "好无聊": "GGG", "好困": "GGG", "好累": "GGG", "难受": "GGG",
"我饿了": "GGG", "我渴了": "WFF", "我想睡觉": "GGG", "我又熬夜了": "GGG", "头好晕": "GGG",
"我又胖了": "GGG", "心好累": "GGG", "没人懂我": "GGG", "好孤独": "GGF", "我好烦": "GGG",
"活着好累": "GGG", "不开心": "GGG", "想你": "GGG", "喜欢你": "GGG", "陪我聊聊": "GFG",
"夸夸我": "WGG", "安慰我": "GGG", "帮帮我": "GGG", "晚安": "GGG", "早安": "GGG",
"谢谢": "GGG", "对不起": "GGG", "真的假的": "FFF", "然后呢": "GGG", "为什么": "GGG",
"你说呢": "WWW", "讲个故事": "WFF", "唱首歌": "WFF", "你几岁": "GGG", "你叫什么": "GGG",
"你是谁": "GGG", "你会什么": "GGF", "你家在哪": "GGG", "今天好热": "GGG", "今天好冷": "GGG",
"下雨了": "GGG", "作业好多": "FGG", "考试好难": "GGG", "工作好烦": "GGG", "老板真烦": "GGG",
"工资好低": "GGG", "我想辞职": "GGF", "我不想上班": "GGF", "我感冒了": "GFG", "周末干嘛": "GGG",
# ── T4（56）──
"忙不忙": "GGG", "吃了没": "GFF", "睡了没": "GGF", "起这么早": "GGF", "今天真够累的": "GGF",
"周末有啥安排": "GGF", "你这会儿干嘛呢": "GFF", "我出门了": "WFF", "到家了跟你说一声": "GFF",
"手机没电了刚充上": "GGW", "被领导骂了": "GFF", "房租又涨了": "GGG", "跟室友吵了一架": "GGF",
"快递丢件了": "GFF", "刚搬完家累瘫了": "WGG", "面试完感觉凉了": "GGG",
"论文被导师打回来了": "GGG", "钱包被偷了": "GGF", "养的猫生病了": "WWW",
"今天被放鸽子了": "GGF", "手机屏幕摔碎了": "GGF", "连续加班一周了": "GGG",
"感冒了鼻子堵得慌": "WFG", "朋友借钱不还": "GFF", "感觉自己什么都做不好": "GGF",
"要不要一起看剧": "GFF", "你说养猫好还是养狗好": "GGG", "今晚吃啥好": "GGF",
"你觉得熬夜值不值": "GFF", "夏天和冬天你更喜欢哪个": "WFF", "如果放假三天你想干嘛": "GGF",
"有没有那种一听就困的歌": "GGF", "我该不该辞职": "GGG", "这个礼物送女生合适吗": "FFF",
"预算三千买什么手机好": "FFF", "合租好还是整租好": "FFF", "考研还是工作": "GGF",
"我是不是想太多了": "GGF", "你会一直陪着我吗": "GGG", "你今天心情怎么样": "WFF",
"你会生我气吗": "GGG", "我要是消失了你会找我吗": "GFF", "你是不是对所有人都这么好": "GFF",
"如果我变笨了你还要我吗": "GGG", "抱一下": "GGF", "亲一口": "GGF",
"今天开了一下午会，脑子嗡嗡的，想听你说说话": "GFF",
"刚跟家里通完电话，被催婚了，烦": "GGF", "我今天第一次自己做饭，居然没翻车，开心": "GGF",
"外面下雨了，突然有点想你": "GFF", "收拾房间翻到以前的照片，有点感慨": "GGG",
"最近总失眠，白天又困，恶性循环了": "GFW",
"如果我说我不开心，你会怎么哄我": "GFF", "你觉得我这个人有什么缺点": "FFF",
"我刚才那句话是不是说错了": "WWW", "要是我跟你吵架了你会先低头吗": "GGG",
# ── T5（7）──
"你好": None,  # T2 你好啊 复用判定，跳过
"我今天在公司被领导当众说了几句": "FFF",
"也不是什么大事，就是心里堵得慌": "GGG", "你说我是不是太敏感了": "GGF",
"嗯，听你这么说好受多了": "GFF", "对了，你晚上一般干嘛": "GFF",
"那明天再找你聊": "GFF",
}

tiernames = ("full", "balanced", "lite")
sets = {"T2": 30, "T3": 56, "T4": 56, "T5": 7}
# 集合归属（T5 的"你好"复用 T2 判定）
data = json.load(open(r"C:\Users\Dawn\Desktop\local_reply_engine\tier_equiv_data_v1.0.json", encoding="utf-8"))
setmap = {}
for d in data:
    if d["tier"] == "full":
        for r in d["rows"]:
            setmap.setdefault(r["q"], r["set"])

res = {t: {s: {"G": 0, "W": 0, "F": 0} for s in sets} for t in tiernames}
for q, verdict in V.items():
    if verdict is None:
        continue
    s = setmap.get(q, "T5")
    for i, t in enumerate(tiernames):
        res[t][s][verdict[i]] += 1

print(f"{'档位':10s} {'集合':4s} {'GOOD':>5s} {'WEAK':>5s} {'FAIL':>5s} {'可用率':>8s}")
summary = {}
for t in tiernames:
    tot_g = tot_a = tot_n = 0
    for s in ("T2", "T3", "T4", "T5"):
        c = res[t][s]
        n = sum(c.values())
        avail = (c["G"] + c["W"]) / n * 100 if n else 0
        print(f"{t:10s} {s:4s} {c['G']:5d} {c['W']:5d} {c['F']:5d} {avail:7.1f}%")
        if s in ("T3", "T4"):
            tot_g += c["G"] + c["W"]; tot_n += n
    w = tot_g / tot_n * 100
    summary[t] = round(w, 1)
    print(f"{t:10s} 加权(T3×0.55+T4×0.45) 可用率 = {w:.1f}%\n")

anchor = [(0.5, 20), (1, 35), (1.5, 45), (3, 65), (7, 82), (14, 90)]
print("等效模型锚点映射：")
for t in tiernames:
    w = summary[t]
    if w >= 90:
        est = "≥14B 档（锚点 90% 饱和，无法区分更大模型）"
    else:
        below = [b for b, a in anchor if a <= w]
        est = f"≈{below[-1]}B–{[b for b, a in anchor if a > w][0]}B 区间"
    print(f"  {t:10s} 加权可用率 {w}%  →  {est}")

with open(r"C:\Users\Dawn\Desktop\local_reply_engine\tier_equiv_verdict_v1.0.json", "w", encoding="utf-8") as fh:
    json.dump({"per_set": res, "weighted": summary}, fh, ensure_ascii=False, indent=1)

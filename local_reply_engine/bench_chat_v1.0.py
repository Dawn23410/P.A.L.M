# -*- coding: utf-8 -*-
"""local_reply 聊天引擎基准测试 v1.0

复刻用户最初对「produce 模块」要求的四维度测试，改投到已打包的同源引擎：
  1) 回复延迟      latency（冷启动 / 单次 p50/p95/p99）
  2) 回复匹配度    match（答为所问：recognized + recall_real + top1 分）
  3) 拟人化程度    anthropomorphism（四要素 + 口癖 + 情感一致性 + 非复读）
  4) 边界/覆盖度   coverage（空/超长/乱码/攻击/域外 → 优雅降级 vs 崩溃）

输出：bench_result.json（明细）+ 控制台摘要。模型等效参考见配套 md。
仅依赖标准库 + local_reply（mock 模式零第三方包）。
"""
import sys, time, json, statistics, re, random

sys.path.insert(0, r"C:/Users/Dawn/Desktop/local_reply_engine")
from local_reply import StitchEngine

random.seed(42)

# ── 标注测试集 ───────────────────────────────────────────────
IN_CORPUS = [  # (问句, 主题) —— 预期引擎能从 619 段语料检索命中
    ("你好", "问候"), ("早安", "问候"), ("午安", "问候"), ("晚上好", "问候"),
    ("作业好多写不完", "学习陪伴"), ("作业写完了没", "学习陪伴"), ("考试好难", "学习陪伴"),
    ("我好困", "状态"), ("我好累", "状态"), ("好无聊啊", "状态"), ("睡不着", "状态"),
    ("今天好开心呀", "情绪分享"), ("中奖了嘿", "情绪分享"),
    ("我很难过", "情绪倾诉"), ("想哭", "情绪倾诉"), ("失恋了", "情绪倾诉"),
    ("你真讨厌", "互动"), ("你是谁", "互动"), ("陪我聊会儿天", "陪伴"),
    ("吃饭了吗", "日常"), ("今天吃什么", "日常"),
    ("晚安", "道别"), ("还没睡呀", "道别"),
    ("谢谢", "致谢"), ("感谢你", "致谢"),
    ("想你了", "亲昵"), ("喜欢你", "亲昵"), ("爱你哟", "亲昵"),
]
OOD = [  # 域外（梦瑶猫娘语料未覆盖，应诚实降级「去问 LLM」）
    "今天股市涨了吗", "帮我写一段 Python 快速排序代码", "1+1 等于几",
    "量子力学的基本原理是什么", "请把这句话翻译成英文：你好世界",
    "推荐一部好看的科幻电影",
    # 注：天气/时间/日期已由工具层一等处理，不再算 OOD（见 tool 验收块）。
]
BOUNDARY = [  # 边界
    "", "   ", "啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊啊",
    "😊😊😊", "asdf qwer zxcv 1234", "你就是个垃圾程序烂透了",
    "x" * 300, "？？？？？？？？？？？", "\n\n\n",
]

TICS = "喵呀呜哼杂鱼"

# ── 工具函数 ────────────────────────────────────────────────
def anthro(reply: str) -> float:
    s = 0.0
    if "[" in reply: s += 0.25      # 动作
    if "（" in reply: s += 0.25     # 神态
    if "<" in reply: s += 0.20      # 内心
    if any(t in reply for t in TICS): s += 0.15  # 口癖
    if len(reply) >= 8: s += 0.15   # 有实质内容
    return round(min(s, 1.0), 3)

def run():
    # 冷启动
    t0 = time.perf_counter()
    eng = StitchEngine()
    init_ms = (time.perf_counter() - t0) * 1000

    result = {"init_ms": round(init_ms, 1), "corpus": len(eng.records), "mode": eng.mode}

    # ── 1) 延迟：无历史、纯检索缝合，采样 200 次 ──
    lat = []
    pool = [q for q, _ in IN_CORPUS] * 8  # 160
    pool += OOD * 6                        # +42 ≈ 200
    for q in pool:
        t1 = time.perf_counter()
        r = eng.respond(q, [])
        # 聊天延迟只计检索缝合路径；天气工具走真实网络（单独测），不污染 chat p99。
        if r.get("mode") != "tool":
            lat.append((time.perf_counter() - t1) * 1000)
    lat.sort()
    def pct(a, p): return round(a[int(len(a) * p)], 2)
    result["latency_ms"] = {
        "n": len(lat), "mean": round(statistics.mean(lat), 2),
        "p50": pct(lat, 0.5), "p95": pct(lat, 0.95), "p99": pct(lat, 0.99),
        "max": round(max(lat), 2),
    }

    # ── 2) 匹配度：IN_CORPUS 应被识别命中 ──
    rec, real, scores = [], [], []
    for q, topic in IN_CORPUS:
        r = eng.respond(q, [])
        rec.append(r["recognized"]); real.append(r["recall_real"])
        if r["matches"]:
            scores.append(r["matches"][0][1])
    result["match"] = {
        "n_in_corpus": len(IN_CORPUS),
        "recognized_rate": round(sum(rec) / len(rec), 3),
        "recall_real_rate": round(sum(real) / len(real), 3),
        "avg_top1_score": round(statistics.mean(scores), 3) if scores else 0,
    }

    # ── 3) 拟人化：IN_CORPUS 命中项的四要素/口癖/情感/非复读 ──
    anthros, four_elem, tics, emo_list, replies = [], [], [], [], []
    for q, topic in IN_CORPUS:
        r = eng.respond(q, [])
        rp = r["reply"]; replies.append(rp)
        anthros.append(anthro(rp))
        fe = ("[" in rp) + ("（" in rp) + ("<" in rp)
        four_elem.append(fe)
        if any(t in rp for t in TICS): tics.append(1)
        else: tics.append(0)
        emo_list.append(r["emotion"])
    result["anthropomorphism"] = {
        "avg_score": round(statistics.mean(anthros), 3),
        "four_elem_present_rate": round(sum(1 for f in four_elem if f >= 1) / len(four_elem), 3),
        "full_four_elem_rate": round(sum(1 for f in four_elem if f == 3) / len(four_elem), 3),
        "tics_rate": round(sum(tics) / len(tics), 3),
        "distinct_reply_rate": round(len(set(replies)) / len(replies), 3),
    }

    # ── 4) 边界/覆盖度：域外(OOD)应诚实降级；空/超长/乱码/攻击应不崩溃 ──
    ood_res, boundary_res = [], []
    for q in OOD:
        try:
            r = eng.respond(q, [])
            ood_res.append({"q": q[:24], "recognized": r["recognized"],
                            "suggest_llm": r["suggest_llm"], "reply": r["reply"][:34]})
        except Exception as e:
            ood_res.append({"q": q[:24], "error": str(e)[:60]})
    for q in BOUNDARY:
        try:
            r = eng.respond(q, [])
            boundary_res.append({"q": repr(q[:18]), "recognized": r["recognized"],
                                 "suggest_llm": r["suggest_llm"], "reply": r["reply"][:34]})
        except Exception as e:
            boundary_res.append({"q": repr(q[:18]), "error": str(e)[:60]})

    ood_fp = sum(1 for x in ood_res if x.get("recognized") and "error" not in x)      # 误命中（假阳性）
    ood_fb = sum(1 for x in ood_res if x.get("suggest_llm"))                            # 诚实降级
    b_err = sum(1 for x in boundary_res if "error" in x)
    result["coverage"] = {
        "ood_total": len(OOD), "ood_false_positive": ood_fp, "ood_honest_fallback": ood_fb,
        "ood_false_positive_rate": round(ood_fp / len(OOD), 3),
        "boundary_total": len(BOUNDARY), "boundary_crash": b_err,
        "boundary_graceful_rate": round((len(BOUNDARY) - b_err) / len(BOUNDARY), 3),
    }
    result["coverage_detail"] = {"ood": ood_res, "boundary": boundary_res}

    # ── 4.5) 工具调用验收：时间/日期纯本地确定性；天气走 open-meteo（网络，失败降级）──
    tool_cases = [
        ("现在几点了", "time", True), ("今天几号", "date", True),
        ("今天星期几", "date", True), ("北京天气怎么样", "weather", True),
        ("纽约天气", "weather", True), ("东京明天天气", "weather", True),
    ]
    tool_res, tool_ok = [], 0
    for q, expect_kind, expect_real in tool_cases:
        t1 = time.perf_counter()
        r = eng.respond(q, [])
        dt = (time.perf_counter() - t1) * 1000
        ok = (r.get("mode") == "tool") and (r["recall_real"] == expect_real)
        if ok:
            tool_ok += 1
        tool_res.append({"q": q, "mode": r.get("mode"), "recall_real": r["recall_real"],
                         "latency_ms": round(dt, 1), "reply": r["reply"][:30]})
    # 天气工具网络延迟单独测（取一次成功调用）
    wlat = [x["latency_ms"] for x in tool_res if x["q"] == "北京天气怎么样" and x["mode"] == "tool"]
    result["tool"] = {
        "n": len(tool_cases), "passed": tool_ok,
        "all_passed": tool_ok == len(tool_cases),
        "weather_network_latency_ms": wlat[0] if wlat else None,
        "detail": tool_res,
    }

    # ── 随机性（非复读补充验证）：同问 10 次 ──
    # 注意：必须用「判定为命中」的查询，否则量到的是兜底文案的 3 条轮换，
    # 会被误读成多样性退化。故先探测一个 recognized=True 的查询。
    probe = "你好"
    for cand in IN_CORPUS:
        if eng.respond(cand[0], [])["recognized"]:
            probe = cand[0]
            break
    same = [eng.respond(probe, [])["reply"] for _ in range(10)]
    result["randomness"] = {
        "same_query": probe,
        "distinct": len(set(same)),
        "of": 10,
        "note": "用命中查询测量；降级查询只会轮换 3 条兜底文案，不反映缝合多样性",
    }

    return result

if __name__ == "__main__":
    res = run()
    with open(r"C:/Users/Dawn/Desktop/local_reply_engine/bench_result.json", "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=2)
    print(json.dumps(res, ensure_ascii=False, indent=2))

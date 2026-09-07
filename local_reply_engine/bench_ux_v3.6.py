# -*- coding: utf-8 -*-
"""bench_ux_v3.6 · 用户视角体验基准（随机化池做实后，语义模式=产品路径）。

量三件事：
  A. 复读感：同一句陪伴意图反复说 N 次，基句(base_a_raw)去重数 + 最长连续
     复读长度 = 真实多样性。池子没做实前每意图只有 1~2 条 → 必复读；做实后
     应有 4 条候选被随机择一，最长连续复读被压住。
  B. 混合对话：16 轮真实风格对话，命中率(recall_real)/拟人率(含喵·本喵)/
     即时复读(滑窗2)/置信。
  C. 延迟：每轮 respond 中位 + p95，预算 400ms（语义模式，含 embed ~15ms）。

模式：semantic。首次加载会重建 npy 缓存(2563→2585，一次性~48s)并写回正确缓存。
"""
import json, glob, os, sys, time, statistics, random

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "local_reply"))
from engine.engine import StitchEngine

CORPUS = os.path.join(ROOT, "local_reply", "engine", "corpus")
PART20 = "mengyao_hq_part20_sameintent_multi.jsonl"

INTENTS = ["陪我", "睡不着", "抱抱我", "说说话吧",
           "心里堵得慌", "随便聊点什么", "在干嘛", "想你了"]
REPEAT = 12

MIXED = [
    "在干嘛", "陪我", "今天好累", "你叫什么名字", "想你了",
    "睡不着", "抱抱我", "我喜欢吃鱼", "说说话吧", "我考试又没过",
    "随便聊点什么", "你今天心情怎么样", "心里堵得慌", "早安",
    "别不理我", "你理理我呗",
]


def cluster_sizes():
    after, before = {}, {}
    for f in sorted(glob.glob(os.path.join(CORPUS, "mengyao_hq_part*.jsonl"))):
        fname = os.path.basename(f)
        for line in open(f, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            o = json.loads(line)
            q = o["conversations"][0]["value"]
            a = o["conversations"][1]["value"]
            if q in INTENTS:
                after.setdefault(q, set()).add(a)
                if fname != PART20:
                    before.setdefault(q, set()).add(a)
    return {q: len(after[q]) for q in INTENTS}, {q: len(before.get(q, set())) for q in INTENTS}


def max_consec(bases):
    best = cur = 0
    prev = None
    for b in bases:
        if b == prev:
            cur += 1
        else:
            cur = 1
        best = max(best, cur)
        prev = b
    return best


def pct(x):
    return round(100.0 * x, 1)


def warm(e, queries):
    for q in queries:
        e.respond(q)


def main():
    # 首次加载：重建并写回正确 npy 缓存(2585)
    t0 = time.perf_counter()
    eng0 = StitchEngine(semantic=True)
    print(f"[load+rebuild] records={len(eng0.records)} mode={eng0.mode} 耗时 {(time.perf_counter()-t0)*1000:.0f}ms")

    # ── A. 复读感（连续会话：单引擎实例，反复同句）──
    after_cs, before_cs = cluster_sizes()
    secA = {}
    lat_all = []
    for q in INTENTS:
        e = StitchEngine(semantic=True)
        bases, pools, ranks, lat = [], [], [], []
        for _ in range(REPEAT):
            t = time.perf_counter()
            r = e.respond(q)
            lat.append((time.perf_counter() - t) * 1000.0)
            bases.append(r.get("base_a_raw"))
            pools.append(r.get("pool_size"))
            ranks.append(r.get("chosen_rank"))
        distinct = len(set(b for b in bases if b))
        engaged = sum(1 for k in ranks if k and k > 0)
        secA[q] = {
            "pool_ceiling_after": after_cs[q],
            "pool_ceiling_before": before_cs[q],
            "distinct_base": distinct,
            "repeat": REPEAT,
            "pool_utilization": round(distinct / after_cs[q], 3),
            "max_consec_repeat": max_consec(bases),
            "pool_mean": round(statistics.mean(pools), 2),
            "randomization_engaged_rate": pct(engaged / REPEAT),
            "lat_median_ms": round(statistics.median(lat), 1),
            "lat_p95_ms": round(sorted(lat)[max(0, int(len(lat) * 0.95) - 1)], 1),
        }
        lat_all += lat

    print("\n=== A. 复读感（同句反复说 %d 次，语义模式，连续会话） ===" % REPEAT)
    print("%-10s%-8s%-8s%-8s%-8s%-7s%-10s%-8s%-7s" % ("意图", "池上限", "实测去重", "池利用", "最长连复", "池均", "随机触发", "中位ms", "p95ms"))
    for q in INTENTS:
        s = secA[q]
        ceil = "%d->%d" % (s["pool_ceiling_before"], s["pool_ceiling_after"])
        print("%-10s%-8s%-8d%-7s%%%-8d%-7.2f%-9s%%%-8.1f%-7.1f" % (
            q, ceil, s["distinct_base"], pct(s["pool_utilization"]),
            s["max_consec_repeat"], s["pool_mean"], s["randomization_engaged_rate"],
            s["lat_median_ms"], s["lat_p95_ms"]))

    # ── B. 混合对话（先 warm 各分支 + reranker 惰性加载，再计时）──
    e = StitchEngine(semantic=True)
    warm(e, ["你好", "今天好累", "你叫什么名字", "想你了", "帮帮我"])  # 覆盖 casual/empathy/question/compliment/ambiguous
    recall, inchars, imm_rep, confs = 0, 0, 0, []
    recent, mix_lat, per_turn = [], [], []
    for q in MIXED:
        t = time.perf_counter()
        r = e.respond(q)
        dt = (time.perf_counter() - t) * 1000.0
        mix_lat.append(dt)
        reply = r.get("reply", "")
        recall += 1 if r.get("recall_real") else 0
        inchars += 1 if ("喵" in reply or "本喵" in reply) else 0
        base = r.get("base_a_raw")
        if base and base in recent[-2:]:
            imm_rep += 1
        recent.append(base)
        confs.append(r.get("confidence", 0))
        per_turn.append((q, r.get("act") or "?", round(r.get("confidence", 0), 3),
                         "Y" if r.get("recall_real") else "N", dt))
    print("\n=== B. 混合对话（%d 轮真实风格） ===" % len(MIXED))
    print(f"命中率(recall_real): {pct(recall/len(MIXED))}%  "
          f"拟人率(含喵/本喵): {pct(inchars/len(MIXED))}%  "
          f"即时复读(滑窗2): {imm_rep} 次")
    print("逐轮(句/行为/置信/命中/ms):")
    for qt, act, cf, rc, dt in per_turn:
        print(f"  {qt:10}{act:14}{cf:<7}{rc:3}{dt:7.1f}")

    all_lat = lat_all + mix_lat
    print("\n=== C. 延迟（预算 400ms，语义模式） ===")
    print(f"中位 {statistics.median(all_lat):.1f}ms  均值 {statistics.mean(all_lat):.1f}ms  "
          f"p95 {sorted(all_lat)[max(0,int(len(all_lat)*0.95)-1)]:.1f}ms  "
          f"max {max(all_lat):.1f}ms  n={len(all_lat)}")
    over = [x for x in all_lat if x > 400]
    print(f"超 400ms 占比: {pct(len(over)/len(all_lat))}%")

    out = {
        "mode": "semantic",
        "records": len(eng0.records),
        "cluster_before": before_cs,
        "cluster_after": after_cs,
        "sectionA_repeat_diversity": secA,
        "sectionB_mixed": {
            "turns": len(MIXED), "recall_real_rate": round(recall / len(MIXED), 3),
            "in_character_rate": round(inchars / len(MIXED), 3),
            "immediate_repeat_within2": imm_rep,
            "conf_median": round(statistics.median(confs), 3),
            "lat_median_ms": round(statistics.median(mix_lat), 1),
            "lat_p95_ms": round(sorted(mix_lat)[max(0, int(len(mix_lat) * 0.95) - 1)], 1),
        },
        "sectionC_latency_all_ms": {
            "median": round(statistics.median(all_lat), 1),
            "mean": round(statistics.mean(all_lat), 1),
            "p95": round(sorted(all_lat)[max(0, int(len(all_lat) * 0.95) - 1)], 1),
            "max": round(max(all_lat), 1),
            "over_400ms_rate": round(len(over) / len(all_lat), 3),
        },
    }
    with open(os.path.join(ROOT, "bench_ux_v3.6.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print("\n[done] -> bench_ux_v3.6.json")


if __name__ == "__main__":
    main()

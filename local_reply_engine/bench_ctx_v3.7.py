# -*- coding: utf-8 -*-
"""bench_ctx_v3.7 · 上下文深度曲线（首句/1/2/3/5/10/20 句上文 × 15 次）。

设计：
  - 话题锚点 =「我下周要去面试了」，探针 =「好紧张」。
    近锚：锚点在上一句（连贯重排 ctx=[-1:] 可见）。
    远锚：锚点在第 1 句（距离 = 深度 k）。
    首句：无上文，探针裸问（基线）。
  - 每深度×锚型 15 次（每次全新引擎实例），指标：
    ①延迟（探针轮 median/p95）②recall_real 命中率
    ③on_topic 率（回复含"面试"= 接住了锚点话题）
  - 装载（npy 缓存 + reranker 预热）在计时外。

判读预期（写死在头部防止看数编解释）：
  延迟：depth0 无连贯重排 → 略低；depth≥1 触发重排 → 上台阶 ~150ms。
  相关性：近锚应全程高（last-1 可见）；远锚若在 k≥2 掉回首句基线，
  说明引擎上下文窗实际只有 1 句（架构事实，不是回归）。
"""
import json, os, sys, time, statistics

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "local_reply"))
from engine.engine import StitchEngine

DEPTHS = [0, 1, 2, 3, 5, 10, 20]
RUNS = 15
PLANT = "我下周要去面试了"
PROBE = "好紧张"
# 填充轮：中性闲聊，不含 猫/面试/紧张/实体命名句式（防干扰 last_entity 与检索）
FILLERS = ["今天天气不错", "中午吃什么呢", "看了会儿剧", "工作有点忙", "周末想去爬山",
           "最近在听歌", "买了件新衣服", "晚上想早点睡", "喝了不少咖啡", "朋友约我吃饭",
           "学了会儿吉他", "看了场电影", "出门散了个步", "打了两把游戏", "煮了碗面",
           "外面下雨了", "楼下的花开了", "收拾了下房间", "拍了张晚霞"]


def build_session(eng, depth, anchor):
    """构造 depth 句上文：near=锚点最后一句；far=锚点第一句。"""
    if depth == 0:
        return
    if anchor == "near":
        ctx = FILLERS[:depth - 1] + [PLANT]
    else:
        ctx = [PLANT] + FILLERS[:depth - 1]
    for t in ctx:
        eng.respond(t)


def main():
    # 全局预热（reranker 3.6s / npy 加载在计时外）
    warm = StitchEngine(semantic=True)
    warm.respond("你好")

    out = {}
    for depth in DEPTHS:
        for anchor in (["near", "far"] if depth > 0 else ["bare"]):
            key = f"{anchor}@{depth}"
            lat, recalls, ontopics = [], 0, 0
            samples = []
            for r in range(RUNS):
                eng = StitchEngine(semantic=True)
                build_session(eng, depth, anchor if depth > 0 else "bare")
                t = time.perf_counter()
                res = eng.respond(PROBE)
                dt = (time.perf_counter() - t) * 1000.0
                lat.append(dt)
                reply = res.get("reply", "")
                recalls += 1 if res.get("recall_real") else 0
                hit = "面试" in reply
                ontopics += 1 if hit else 0
                if r < 2:
                    samples.append((round(res.get("confidence", 0), 3), reply[:42].replace("\n", " / ")))
            out[key] = {
                "lat_median": round(statistics.median(lat), 1),
                "lat_p95": round(sorted(lat)[max(0, int(len(lat) * 0.95) - 1)], 1),
                "lat_max": round(max(lat), 1),
                "recall_rate": round(recalls / RUNS, 3),
                "ontopic_rate": round(ontopics / RUNS, 3),
                "samples": samples,
            }
            s = out[key]
            print(f"{key:10} 延迟 med/p95/max = {s['lat_median']}/{s['lat_p95']}/{s['lat_max']}ms  "
                  f"命中 {s['recall_rate']:.0%}  on_topic(提面试) {s['ontopic_rate']:.0%}")
            for cf, rep in s["samples"]:
                print(f"            conf={cf} {rep}")

    with open(os.path.join(ROOT, "bench_ctx_v3.7.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print("\n[done] -> bench_ctx_v3.7.json")


if __name__ == "__main__":
    main()

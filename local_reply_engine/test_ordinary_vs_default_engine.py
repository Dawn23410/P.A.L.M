# -*- coding: utf-8 -*-
"""不更换引擎：用「普通语料（无人格）」作为测试输入集，喂给默认（内置梦瑶）引擎。

目的：验证引擎对域外（OOD）普通问题的鲁棒性——不崩、延迟可控、兜底行为合理，
而非把引擎换成普通语料。统计命中内置语料率 / 兜底(建议走 LLM)率 / 延迟，并打印样例。
"""
import glob
import json
import os
import random
import time

from local_reply.engine.engine import StitchEngine

HERE = os.path.dirname(os.path.abspath(__file__))
ORDINARY = os.path.join(HERE, "corpus_ordinary_20k")


def sample_queries(corpus_dir, k):
    qs = []
    for f in sorted(glob.glob(os.path.join(corpus_dir, "mengyao_hq_part*.jsonl"))):
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                conv = o.get("conversations", [])
                q = next((m["value"] for m in conv if m.get("from") == "human"), "")
                if q:
                    qs.append(q)
    rnd = random.Random(7)
    return rnd.sample(qs, min(k, len(qs)))


def run(tier, n):
    eng = StitchEngine(tier=tier)  # 默认内置语料，不换
    qs = sample_queries(ORDINARY, n)
    lat, hit, fallback = [], 0, 0
    examples = []
    for q in qs:
        t = time.perf_counter()
        try:
            r = eng.respond(q)
        except Exception as exc:
            print(f"  ❌ 崩溃: {q[:20]!r} -> {exc!r}")
            lat.append((time.perf_counter() - t) * 1000)
            fallback += 1
            continue
        dt = (time.perf_counter() - t) * 1000
        lat.append(dt)
        if r.get("recall_real"):
            hit += 1
        else:
            fallback += 1
        if len(examples) < 12:
            examples.append((q, r["reply"], bool(r.get("recall_real")),
                             bool(r.get("suggest_llm")), round(dt, 1)))
    lat.sort()
    n_ = len(lat)
    med = lat[n_ // 2]
    mean = sum(lat) / n_
    p95 = lat[min(n_ - 1, int(n_ * 0.95))]
    print(f"\n=== 默认引擎 tier={tier} mode={eng.mode} 内置records={len(eng.records)} ===")
    print(f"测试输入：普通语料抽样 {n_} 条（域外 OOD）")
    print(f"延迟 mean={mean:.1f} median={med:.1f} p95={p95:.1f}ms")
    print(f"命中内置语料(召回): {hit}/{n_} ({hit*100//n_}%)  |  "
          f"兜底/建议走LLM: {fallback}/{n_} ({fallback*100//n_}%)")
    print("--- 样例（问 → 答[命中?/兜底?/延迟ms]）---")
    for q, a, rec, sug, dt in examples:
        tag = "命中" if rec else ("兜底" if sug else "其它")
        print(f"  {q[:22]!r} → {a[:26]!r}  [{tag}/{dt}ms]")


def main():
    print("不更换引擎 · 普通语料作测试输入")
    run("lite", 800)
    run("full", 800)


if __name__ == "__main__":
    main()

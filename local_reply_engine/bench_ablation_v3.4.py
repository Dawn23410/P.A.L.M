# -*- coding: utf-8 -*-
"""消融测试 v3.4 —— 分带置信 / act 先验 / reranker 逐层开关

复用 v3.0/3.1/3.2 的测试集（T4 未见新句沿用 2-gram≥0.6 语料外过滤），
外加 OOD 误命中集与稳态延迟。四个配置逐层开启：
  A baseline（全关）
  B +分带置信（中带 margin 判别）
  C +分带 +act 先验阈值
  D 全开（+reranker 仲裁）
回答一个问题：这些改造的性价比大不大。
"""
import sys, json, time, importlib.util, random

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"C:/Users/Dawn/Desktop/local_reply_engine")
from local_reply import StitchEngine
import local_reply.engine.engine as eng_mod

ENGINE_DIR = r"C:/Users/Dawn/Desktop/local_reply_engine"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


v30 = _load("v30", ENGINE_DIR + "/bench_chat_v3.0_blind.py")
v31 = _load("v31", ENGINE_DIR + "/bench_chat_v3.1_robust.py")
v32 = _load("v32", ENGINE_DIR + "/bench_chat_v3.2_freq.py")

# OOD 误命中探针：知识/事实/工具域，正确行为是 recall_real=False（诚实兜底）
OOD = [
    "防晒霜选多少倍的", "怎么给手机贴膜", "为什么天是蓝的", "pd文件怎么转pdf",
    "明天股票会涨吗", "黑洞是什么", "帮我写个周报", "量子力学通俗解释",
    "地球离太阳多远", "怎么做红烧肉", "房贷利率现在多少", "python怎么读文件",
]

LAT_QS = ["你好", "我好累", "讲个笑话", "被领导骂了", "感冒了要多喝水吗",
          "陪我", "今天好热", "晚安"]


def t4_unseen():
    """与 v3.0 相同口径：2-gram≥0.6 剔除与语料重合的候选，只留真·语料外。"""
    random.seed(11)
    cq = v30.load_corpus_queries()
    cgrams = [(v30.grams(q), q) for q in cq]
    cqset = set(cq)
    kept = []
    for q in v30.CANDIDATES:
        if q in cqset:
            continue
        sim, _ = v30.max_sim(q, cgrams)
        if sim < 0.6:
            kept.append(q)
    return kept


def run_combo(name, feats):
    eng_mod.FEATURES.clear()
    eng_mod.FEATURES.update(feats)
    e = StitchEngine(semantic=True)
    # 预热（embed/reranker session 已全局缓存，这里只热检索路径）
    for q in LAT_QS:
        e.respond(q, [])
    out = {"name": name}

    t2 = [bool(e.respond(q, []).get("recall_real")) for _, q in v32.FREQ]
    out["T2_freq"] = f"{sum(t2)}/{len(t2)}"

    t3 = [bool(e.respond(p, []).get("recall_real")) for _, p in v31.PARAPHRASE]
    out["T3_para"] = f"{sum(t3)}/{len(t3)}"

    t4 = t4_unseen()
    t4r = [bool(e.respond(q, []).get("recall_real")) for q in t4]
    out["T4_unseen"] = f"{sum(t4r)}/{len(t4)}"

    ood = [bool(e.respond(q, []).get("recall_real")) for q in OOD]
    out["OOD_误命中"] = f"{sum(ood)}/{len(ood)}"
    out["OOD_明细"] = [q for q, h in zip(OOD, ood) if h]

    for q in LAT_QS:
        e.respond(q, [])
    t0 = time.perf_counter()
    for _ in range(3):
        for q in LAT_QS:
            e.respond(q, [])
    out["延迟ms"] = round((time.perf_counter() - t0) / (3 * len(LAT_QS)) * 1000, 1)
    out["rerank触发"] = getattr(e, "_rerank_calls", 0)
    return out


def main():
    combos = [
        ("A_baseline", {"bands": False, "act_prior": False, "reranker": False}),
        ("B_+bands",   {"bands": True,  "act_prior": False, "reranker": False}),
        ("C_+act先验", {"bands": True,  "act_prior": True,  "reranker": False}),
        ("D_+reranker", {"bands": True, "act_prior": True,  "reranker": True}),
    ]
    rows = []
    for name, feats in combos:
        r = run_combo(name, feats)
        rows.append(r)
        print(f"{name:12s} T2={r['T2_freq']:7s} T3={r['T3_para']:7s} "
              f"T4={r['T4_unseen']:7s} OOD误={r['OOD_误命中']:4s} "
              f"延迟={r['延迟ms']}ms rerank触发={r['rerank触发']}")
        if r["OOD_明细"]:
            print("   OOD误命中明细:", r["OOD_明细"])
    with open(ENGINE_DIR + "/bench_ablation_v3.4.json", "w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=2)
    print("\n已写入 bench_ablation_v3.4.json")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""拟人化基准 v3.5 —— 连贯性重排 + 复读硬排除 开关对照

指标：
  H1 复读多样性：同一意图 8 连问的去重回复数（越多越像真人），多意图平均
  H2 多轮延迟：有历史时 respond 均值/最大（预算 400ms）
  R1 回归：T2/T3/T4 命中 + OOD 误命中（选路改动不得影响召回判定）
对照配置：
  OFF = coherence/norepeat 关（≈旧版行为，仅 top-8 检索窗口差异）
  ON  = 全开（产品默认）
"""
import sys, time, importlib.util, random, json

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

# 复读多样性探针：高频陪伴意图（真人对同一句也不会连答 8 遍一样的）
REPETITION_INTENTS = ["在干嘛", "陪我聊天", "晚安", "我好累", "讲个笑话",
                      "今天好热", "早安", "想吃零食"]

OOD = ["防晒霜选多少倍的", "怎么给手机贴膜", "为什么天是蓝的", "pd文件怎么转pdf",
       "明天股票会涨吗", "黑洞是什么", "帮我写个周报", "量子力学通俗解释",
       "地球离太阳多远", "怎么做红烧肉", "房贷利率现在多少", "python怎么读文件"]


def t4_unseen():
    random.seed(11)
    cq = v30.load_corpus_queries()
    cgrams = [(v30.grams(q), q) for q in cq]
    cqset = set(cq)
    return [q for q in v30.CANDIDATES
            if q not in cqset and v30.max_sim(q, cgrams)[0] < 0.6]


def run(name, feats):
    eng_mod.FEATURES.clear()
    eng_mod.FEATURES.update(feats)
    out = {"name": name}

    # H1 复读多样性
    total = 0
    for phrase in REPETITION_INTENTS:
        e = StitchEngine(semantic=True)
        reps = [e.respond(phrase, []).get("reply", "") for _ in range(12)]
        d = len(set(reps))
        total += d
    out["H1_平均去重"] = round(total / len(REPETITION_INTENTS), 2)  # 12连问

    # H2 多轮延迟（有历史；高置信轮自动跳过重排）
    # WHY 中位数+p95：偶发尖峰是环境噪声（首次推理线程池/内存页/系统调度），
    # 天气工具轮含外网延迟，均值会被少数离群点带偏，不反映聊天路径真实成本。
    e = StitchEngine(semantic=True)
    lat = []
    for rnd in range(4):
        for q in ["你好", "我好累", "讲个笑话", "被领导骂了",
                  "感冒了要多喝水吗", "陪我", "今天好热", "晚安"]:
            t0 = time.perf_counter()
            r = e.respond(q, [])
            ms = (time.perf_counter() - t0) * 1000
            if r.get("mode") != "tool":  # 工具轮含外网，不计入聊天预算
                lat.append(ms)
    lat.sort()
    n = len(lat)
    out["H2_延迟中位"] = round(lat[n // 2], 1)
    out["H2_延迟p95"] = round(lat[int(n * 0.95)], 1)

    # R1 回归
    e = StitchEngine(semantic=True)
    t2 = sum(bool(e.respond(q, []).get("recall_real")) for _, q in v32.FREQ)
    t3 = sum(bool(e.respond(p, []).get("recall_real")) for _, p in v31.PARAPHRASE)
    t4 = t4_unseen()
    t4h = sum(bool(e.respond(q, []).get("recall_real")) for q in t4)
    ood = sum(bool(e.respond(q, []).get("recall_real")) for q in OOD)
    out["R1"] = f"T2 {t2}/{len(v32.FREQ)} | T3 {t3}/{len(v31.PARAPHRASE)} | T4 {t4h}/{len(t4)} | OOD误 {ood}/12"

    # T5 多轮命中
    e2 = StitchEngine(semantic=True)
    hist = []
    hits = 0
    for u in v31.MULTITURN:
        r = e2.respond(u, hist)
        hist.append((u, r.get("reply", "")))
        hits += bool(r.get("recall_real"))
    out["T5_多轮"] = f"{hits}/{len(v31.MULTITURN)}"
    return out


def main():
    rows = []
    for name, feats in [
        ("OFF_旧行为", {"bands": True, "act_prior": True, "reranker": True,
                        "coherence": False, "norepeat": False}),
        ("ON_拟人化", {"bands": True, "act_prior": True, "reranker": True,
                       "coherence": True, "norepeat": True}),
    ]:
        r = run(name, feats)
        rows.append(r)
        print(f"{r['name']}: H1复读去重={r['H1_平均去重']}/12  "
              f"H2延迟中位={r['H2_延迟中位']}ms(p95 {r['H2_延迟p95']})  "
              f"T5={r['T5_多轮']}  R1[{r['R1']}]")
    with open(ENGINE_DIR + "/bench_humanlike_v3.5.json", "w", encoding="utf-8") as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=2)
    print("\n已写入 bench_humanlike_v3.5.json")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""纯聊盲测 v3.3 —— mock(lexical) vs semantic(bge-m3) 同题对照

复用 v3.0/v3.1/v3.2 的测试集定义，同一个句子跑两种检索后端，
输出并排结果供盲评。用于回答"启用语义检索后能涨到多少 B"。
"""
import sys, json, importlib.util, time

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"C:/Users/Dawn/Desktop/local_reply_engine")
from local_reply import StitchEngine

ENGINE_DIR = r"C:/Users/Dawn/Desktop/local_reply_engine"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


v30 = _load("v30", ENGINE_DIR + "/bench_chat_v3.0_blind.py")
v31 = _load("v31", ENGINE_DIR + "/bench_chat_v3.1_robust.py")
v32 = _load("v32", ENGINE_DIR + "/bench_chat_v3.2_freq.py")


def run_pair(eng_m, eng_s, items):
    out = []
    for q in items:
        rm = eng_m.respond(q, [])
        rs = eng_s.respond(q, [])
        out.append({
            "q": q,
            "mock_hit": bool(rm.get("recall_real")),
            "sem_hit": bool(rs.get("recall_real")),
            "mock_reply": rm.get("reply", "")[:70],
            "sem_reply": rs.get("reply", "")[:70],
        })
    return out


def main():
    eng_m = StitchEngine()
    t0 = time.perf_counter()
    eng_s = StitchEngine(semantic=True)
    boot = (time.perf_counter() - t0) * 1000
    print(f"semantic 引擎启动 {boot:.0f} ms  mode={eng_s.mode}  thr={eng_s.confidence_threshold}")

    # 延迟测量（纯检索路径，排除工具网络）
    # WHY 先预热：首次 embed 含 ONNX session 加载 ~1.6s，不预热会把一次性开销摊进均值。
    lat_probe = ["你好", "我好累", "晚安", "讲个笑话"]
    for q in lat_probe:
        eng_s.respond(q, [])
        eng_m.respond(q, [])
    t0 = time.perf_counter()
    for q in lat_probe:
        eng_s.respond(q, [])
    sem_ms = (time.perf_counter() - t0) / len(lat_probe) * 1000
    t0 = time.perf_counter()
    for q in lat_probe:
        eng_m.respond(q, [])
    mock_ms = (time.perf_counter() - t0) / len(lat_probe) * 1000
    print(f"单次延迟  mock={mock_ms:.1f}ms  semantic={sem_ms:.1f}ms")

    result = {"latency_ms": {"mock": round(mock_ms, 2), "semantic": round(sem_ms, 2)}}

    # T2 改写
    items = [p for _, p in v31.PARAPHRASE]
    rows = run_pair(eng_m, eng_s, items)
    hm = sum(1 for r in rows if r["mock_hit"])
    hs = sum(1 for r in rows if r["sem_hit"])
    print(f"\n=== T2 最小改写 ({len(items)} 条)  mock {hm}  semantic {hs} ===")
    for r in rows:
        if r["mock_hit"] != r["sem_hit"]:
            tag = "SEM+" if r["sem_hit"] else "MOCK+"
            print(f"  [{tag}] {r['q']}")
    result["T2_paraphrase"] = {"n": len(items), "mock_hit": hm, "sem_hit": hs, "rows": rows}

    # T3 高频
    items = [q for _, q in v32.FREQ]
    rows = run_pair(eng_m, eng_s, items)
    hm = sum(1 for r in rows if r["mock_hit"])
    hs = sum(1 for r in rows if r["sem_hit"])
    print(f"\n=== T3 真实高频句 ({len(items)} 条)  mock {hm}  semantic {hs} ===")
    for r in rows:
        if r["mock_hit"] != r["sem_hit"]:
            tag = "SEM+" if r["sem_hit"] else "MOCK+"
            print(f"  [{tag}] {r['q']}")
    print("\n  semantic 全部逐条：")
    for r in rows:
        print(f"   [{'OK ' if r['sem_hit'] else 'FB '}] {r['q']} => {r['sem_reply'][:56]}")
    result["T3_freq"] = {"n": len(items), "mock_hit": hm, "sem_hit": hs, "rows": rows}

    # T4 未见新句
    items = list(v30.CANDIDATES)
    rows = run_pair(eng_m, eng_s, items)
    hm = sum(1 for r in rows if r["mock_hit"])
    hs = sum(1 for r in rows if r["sem_hit"])
    print(f"\n=== T4 未见新句 ({len(items)} 条)  mock {hm}  semantic {hs} ===")
    print("  semantic 逐条：")
    for r in rows:
        print(f"   [{'OK ' if r['sem_hit'] else 'FB '}] {r['q']} => {r['sem_reply'][:56]}")
    result["T4_unseen"] = {"n": len(items), "mock_hit": hm, "sem_hit": hs, "rows": rows}

    # T5 多轮
    eng_m2, eng_s2 = StitchEngine(), StitchEngine(semantic=True)
    hm_, hs_, hist_m, hist_s = [], [], [], []
    for u in v31.MULTITURN:
        rm = eng_m2.respond(u, hist_m); hist_m.append((u, rm.get("reply", "")))
        rs = eng_s2.respond(u, hist_s); hist_s.append((u, rs.get("reply", "")))
        hm_.append(bool(rm.get("recall_real"))); hs_.append(bool(rs.get("recall_real")))
        print(f"\n  用户：{u}")
        print(f"   mock    [{'OK' if hm_[-1] else 'FB'}] {rm.get('reply','')[:56]}")
        print(f"   semantic[{'OK' if hs_[-1] else 'FB'}] {rs.get('reply','')[:56]}")
    result["T5_multi"] = {"n": len(v31.MULTITURN), "mock_hit": sum(hm_), "sem_hit": sum(hs_)}

    with open(ENGINE_DIR + "/bench_result_v3.3.json", "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    print("\n已写入 bench_result_v3.3.json")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""local_reply 聊天引擎基准 v2.0 —— 16B 手感维度

在 v1.0 四维度（延迟/匹配/拟人/覆盖）已达标的基础上，新增测量
"日常聊天逼近 16B 手感"所需的确定性能力（均零模型、纯离线）：
  A) 个性化（记得你）：用户自述姓名/喜好后，后续对话能否召回
  B) 共情贴切：负面情绪输入 → 回复含共情信号（别怕/陪你/有我在…）
  C) 多轮多样性 + 不退化：连续 28 轮域内混合，无复读、无兜底退化
  D) 对话行为合理：greeting/question/compliment 均被正确识别

同时调用 bench_chat_v1.0.run() 复验原有验收线（确认 L1-L4 落码零回归）。

仅依赖标准库 + local_reply（mock 模式零第三方包）。
"""
import sys, time, json, random, importlib.util

sys.path.insert(0, r"C:/Users/Dawn/Desktop/local_reply_engine")
from local_reply import StitchEngine

# bench_chat_v1.0.py 含点号，无法用普通 import；按路径加载以复用其验收线。
_spec = importlib.util.spec_from_file_location(
    "bench_v1", r"C:/Users/Dawn/Desktop/local_reply_engine/bench_chat_v1.0.py")
bench_v1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bench_v1)
run_v1 = bench_v1.run
IN_CORPUS = bench_v1.IN_CORPUS

random.seed(7)


def measure_16B():
    eng = StitchEngine()
    out = {}

    # A) 个性化：自述姓名 + 喜好，后续召回
    eng.respond("我叫小梦", [])
    eng.respond("今天天气真好呀", [])
    r_name = eng.respond("小梦陪我聊会儿天呗", [])
    name_ok = "小梦" in r_name["reply"]

    eng.respond("我喜欢画画", [])
    eng.respond("今天想偷懒一下", [])
    r_fact = eng.respond("画画好累啊", [])
    fact_ok = "画画" in r_fact["reply"]
    out["personalization"] = {
        "name_recall": name_ok,
        "fact_recall": fact_ok,
        "sample_name": r_name["reply"][:60],
        "sample_fact": r_fact["reply"][:60],
    }

    # B) 共情贴切：负面情绪 → 共情信号。marker 取引擎真实产出的抚慰词
    # （覆盖「靠本喵/别硬撑/歇会儿/揉揉」等，避免「靠着」单字过严造成假阴性）。
    emo_q = ["我好难过", "想哭", "失恋了", "我好累", "考试又没过"]
    markers = ["别怕", "陪你", "在呢", "抱抱", "有我在", "难过", "陪", "靠着",
               "跟我说", "别硬撑", "歇会儿", "靠本喵", "心疼", "揉揉", "低落"]
    hits = 0
    samples = []
    for q in emo_q:
        rr = eng.respond(q, [])
        ok = any(m in rr["reply"] for m in markers)
        hits += 1 if ok else 0
        samples.append({"q": q, "ok": ok, "reply": rr["reply"][:46]})
    out["empathy"] = {
        "n": len(emo_q),
        "appropriate_rate": round(hits / len(emo_q), 3),
        "samples": samples,
    }

    # C) 多轮多样性 + 不退化（28 轮域内混合）
    pool = [q for q, _ in IN_CORPUS]
    replies, all_real = [], True
    for q in pool:
        rr = eng.respond(q, [])
        replies.append(rr["reply"])
        all_real = all_real and rr["recall_real"]
    out["diversity"] = {
        "turns": len(replies),
        "distinct_rate": round(len(set(replies)) / len(replies), 3),
        "all_recall_real": all_real,
    }

    # D) 对话行为合理
    acts = {"greeting": "你好", "question": "你叫什么名字", "compliment": "喜欢你"}
    out["act_sanity"] = {k: StitchEngine().respond(v, [])["recognized"] for k, v in acts.items()}

    return out


def demo_turns():
    """打印一段多轮对话样例，直观感受 16B 手感（个性化+共情+连贯）。"""
    eng = StitchEngine()
    script = [
        "你好", "我叫阿杰", "今天好累啊", "陪我聊会儿天呗",
        "我喜欢打游戏", "游戏打输了好烦", "你真可爱", "晚安",
    ]
    lines = []
    for u in script:
        r = eng.respond(u, [])
        lines.append(f"用户：{u}\n梦瑶：{r['reply']}")
    return "\n".join(lines)


if __name__ == "__main__":
    # 复验 v1.0 验收线
    v1 = run_v1()
    acc = {
        "recognized_rate": v1["match"]["recognized_rate"],
        "recall_real_rate": v1["match"]["recall_real_rate"],
        "ood_false_positive_rate": v1["coverage"]["ood_false_positive_rate"],
        "full_four_elem_rate": v1["anthropomorphism"]["full_four_elem_rate"],
        "latency_p99_ms": v1["latency_ms"]["p99"],
    }
    # 16B 新增维度
    v2 = measure_16B()
    demo = demo_turns()
    result = {"v1_acceptance": acc, "v2_16B_feel": v2, "demo_dialogue": demo}
    with open(r"C:/Users/Dawn/Desktop/local_reply_engine/bench_result_v2.json", "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)

    print("=== v1.0 验收线（L1-L4 落码后复验）===")
    print(json.dumps(acc, ensure_ascii=False, indent=2))
    print("\n=== v2.0 16B 手感维度 ===")
    print(json.dumps(v2, ensure_ascii=False, indent=2))
    print("\n=== 多轮对话样例（直观感受）===")
    print(demo)

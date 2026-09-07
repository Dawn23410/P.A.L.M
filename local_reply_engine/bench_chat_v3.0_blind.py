# -*- coding: utf-8 -*-
"""纯聊能力盲测 v3.0 —— 未见句泛化 + 盲评打分

目的：回答"纯聊天相当于多少 B 模型"。
方法：构造**语料外**的真实日常聊天句（自动剔除与 733 条语料相同或高度重合的），
跑引擎，输出回复供人工/AI 盲评。不再自出题自评域内。

评估三档：
  GOOD  = 贴题 + 人格一致 + 有推进（像样回复）
  WEAK  = 命中了但敷衍/微跑题
  FAIL  = 兜底降级 / 明显跑题 / 复读
"""
import sys, json, glob, random, time

sys.path.insert(0, r"C:/Users/Dawn/Desktop/local_reply_engine")
from local_reply import StitchEngine

ENGINE_DIR = r"C:/Users/Dawn/Desktop/local_reply_engine"


def load_corpus_queries():
    qs = []
    for f in sorted(glob.glob(ENGINE_DIR + "/local_reply/engine/corpus/*.jsonl")):
        for line in open(f, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            for c in d.get("conversations", []):
                if c.get("from") == "human":
                    qs.append(c.get("value", ""))
    return [q for q in qs if q]


def grams(s, n=2):
    s = "".join(ch for ch in s if not ch.isspace())
    return {s[i:i + n] for i in range(len(s) - n + 1)} or {s}


def max_sim(q, corpus_grams):
    g = grams(q)
    best, bestq = 0.0, ""
    for cg, cq in corpus_grams:
        inter = len(g & cg)
        union = len(g | cg) or 1
        j = inter / union
        if j > best:
            best, bestq = j, cq
    return best, bestq


# ---------- 候选句：真实日常聊天，刻意写成语料里没有的措辞 ----------
CANDIDATES = [
    # A 日常寒暄 / 新措辞
    "在吗", "忙不忙", "吃了没", "回来了", "刚到家", "睡了没", "起这么早",
    "今天真够累的", "总算下班了", "周末有啥安排", "你这会儿干嘛呢",
    "我出门了", "到家了跟你说一声", "手机没电了刚充上",
    # B 情绪倾诉 / 新情境
    "被领导骂了", "房租又涨了", "跟室友吵了一架", "快递丢件了",
    "刚搬完家累瘫了", "面试完感觉凉了", "论文被导师打回来了",
    "钱包被偷了", "养的猫生病了", "今天被放鸽子了",
    "手机屏幕摔碎了", "连续加班一周了", "感冒了鼻子堵得慌",
    "朋友借钱不还", "被人误会了", "感觉自己什么都做不好",
    # C 闲聊邀请 / 话题
    "要不要一起看剧", "推荐个下饭剧呗", "你说养猫好还是养狗好",
    "今晚吃啥好", "咖啡和茶你选哪个", "你觉得熬夜值不值",
    "夏天和冬天你更喜欢哪个", "如果放假三天你想干嘛",
    "你说人为什么要上班", "有没有那种一听就困的歌",
    # D 轻度判断 / 需要常识
    "我该不该辞职", "这个礼物送女生合适吗", "第一次相亲要注意啥",
    "预算三千买什么手机好", "合租好还是整租好", "考研还是工作",
    "要不要跟他和好", "我是不是想太多了",
    # E 关系 / 陪伴互动
    "你会一直陪着我吗", "你今天心情怎么样", "你会生我气吗",
    "我要是消失了你会找我吗", "你是不是对所有人都这么好",
    "如果我变笨了你还要我吗", "抱一下", "摸摸头", "亲一口",
    # F 复杂 / 长句 / 多信息
    "今天开了一下午会，脑子嗡嗡的，想听你说说话",
    "刚跟家里通完电话，被催婚了，烦",
    "我今天第一次自己做饭，居然没翻车，开心",
    "外面下雨了，突然有点想你",
    "收拾房间翻到以前的照片，有点感慨",
    "最近总失眠，白天又困，恶性循环了",
    # G 略带推理 / 反常识
    "如果我说我不开心，你会怎么哄我",
    "你说人活着到底图什么",
    "你觉得我这个人有什么缺点",
    "我刚才那句话是不是说错了",
    "要是我跟你吵架了你会先低头吗",
]


def main():
    random.seed(11)
    cq = load_corpus_queries()
    cgrams = [(grams(q), q) for q in cq]
    cqset = set(cq)

    kept, dropped = [], []
    for q in CANDIDATES:
        if q in cqset:
            dropped.append((q, "exact", 1.0))
            continue
        sim, near = max_sim(q, cgrams)
        if sim >= 0.6:
            dropped.append((q, near, round(sim, 2)))
        else:
            kept.append(q)

    eng = StitchEngine()
    rows = []
    for q in kept:
        t0 = time.perf_counter()
        try:
            r = eng.respond(q, [])
        except Exception as e:
            rows.append({"q": q, "error": repr(e)})
            continue
        ms = (time.perf_counter() - t0) * 1000
        rows.append({
            "q": q,
            "recognized": bool(r.get("recognized")),
            "recall_real": bool(r.get("recall_real")),
            "ms": round(ms, 2),
            "reply": r.get("reply", "")[:120],
        })

    out = {
        "candidates": len(CANDIDATES),
        "dropped_as_in_corpus": [{"q": a, "near": b, "sim": c} for a, b, c in dropped],
        "kept_unseen": len(kept),
        "rows": rows,
    }
    p = ENGINE_DIR + "/bench_result_v3.json"
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)

    print("候选", len(CANDIDATES), "剔除(疑似语料内)", len(dropped), "实际未见", len(kept))
    print("--- 剔除明细 ---")
    for a, b, c in dropped:
        print(f"  {a}  ~{b} ({c})")
    print("--- 未见句结果 ---")
    for r in rows:
        flag = "OK " if r.get("recall_real") else ("REC" if r.get("recognized") else "FB ")
        print(f"[{flag}] {r['q']}  ->  {r.get('reply','ERR')[:70]}")


if __name__ == "__main__":
    main()

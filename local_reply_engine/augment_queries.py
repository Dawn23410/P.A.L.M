# -*- coding: utf-8 -*-
"""query 侧增广 —— 同 reply 多触发面

原理：泛化瓶颈在「用户说法 vs 索引说法」对不上。给每条语料的 q 生成 2-3 个
自然变体（复用原 reply，零质量风险），直接扩语义索引的触发面。

规则（保守，宁缺勿滥）：
  V1 若句尾非语气词 → 加「啊」
  V2 若句尾非语气词 → 加「呀」/「哦」（轮换）
  V3 若 q 以「我」开头且长度>2 → 去「我」缩写版
过滤：
  - 变体 != 原 q；不与全量现有 q 重复；长度 2-20 字；不含工具触发词（几点/几号/星期/天气）
输出：corpus/mengyao_hq_part17_augment.jsonl（含 "aug": true 标记）
"""
import sys, json, glob, re

sys.stdout.reconfigure(encoding="utf-8")
ENGINE_DIR = r"C:/Users/Dawn/Desktop/local_reply_engine"
CORPUS_DIR = ENGINE_DIR + "/local_reply/engine/corpus"

TAIL_MOOD = set("啊呀哦嘛呗咯哈嗯呢吧哦哟呜啦～~。！?？…")
TOOLISH = re.compile(r"几点|几号|星期|周几|天气|温度|湿dus")


def load_all():
    recs = []
    for f in sorted(glob.glob(CORPUS_DIR + "/mengyao_hq_part*.jsonl")):
        for line in open(f, encoding="utf-8"):
            line = line.strip()
            if line:
                recs.append(json.loads(line))
    return recs


def variants(q):
    out = []
    if not (2 <= len(q) <= 20) or TOOLISH.search(q):
        return out
    tail = q[-1]
    if tail not in TAIL_MOOD:
        out.append(q + "啊")
        out.append(q + "呀")
    if q.startswith("我") and len(q) > 2:
        short = q[1:]
        if short[-1] in TAIL_MOOD or 2 <= len(short) <= 20:
            out.append(short)
    return out


def main():
    recs = load_all()
    existing_q = set()
    for r in recs:
        for c in r.get("conversations", []):
            if c.get("from") == "human":
                existing_q.add(c.get("value", ""))
    base = len(recs)
    print(f"现有语料 {base} 条, 唯一 q {len(existing_q)}")

    aug, seen = [], set()
    for r in recs:
        conv = r.get("conversations", [])
        if not conv:
            continue
        q = conv[0].get("value", "")
        reply = conv[1].get("value", "") if len(conv) > 1 else ""
        if not q or not reply:
            continue
        for v in variants(q):
            if v == q or v in existing_q or v in seen:
                continue
            seen.add(v)
            aug.append({"conversations": [
                {"from": "human", "value": v},
                {"from": "gpt", "value": reply},
            ], "aug": True})

    out = CORPUS_DIR + "/mengyao_hq_part17_augment.jsonl"
    with open(out, "w", encoding="utf-8") as fh:
        for r in aug:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"生成增广 {len(aug)} 条 → {out}")
    print(f"索引将达 {base + len(aug)} 条")


if __name__ == "__main__":
    main()

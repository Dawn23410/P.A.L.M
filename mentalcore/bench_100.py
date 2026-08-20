"""100 次对话实测采集（论文级基准数据源）。

- 语料：20 句多样化固定语料池循环 100 轮（可复现；上下文随轮次累积，属被测变量）。
- 每轮记录：首字延迟 TTFB / 总耗时 / 流式分片数 / 正文与长度 / 数据区协议遵守 /
  好感度(delta/base/档位/dynamics) / 情绪三轴 / 注入源 / 错误与重试次数。
- 断点续跑：每轮落盘 bench_100_raw.json。

用法：python bench_100.py [--rounds 100]
"""
import argparse
import json
import os
import time

from mentalcore.config import load_config
from mentalcore.core import build_core
from mentalcore.persona_card import CharacterCard

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "bench_100_raw.json")

CORPUS = [
    "今天天气真好",
    "工作好累，感觉要撑不住了",
    "给我讲个笑话吧",
    "我想家了，想吃妈妈做的菜",
    "周末想去看海，一起吗？",
    "你住在海边，平时都干什么？",
    "我最近有点失眠",
    "今天被老板夸了，好开心",
    "你喜欢吃什么？",
    "我好难过，跟朋友吵架了",
    "晚安，明天再聊",
    "早上好，今天有什么计划？",
    "我养了一只猫，超可爱",
    "你觉得人生意义是什么？",
    "忙了一整天，终于下班了",
    "讲个你小时候的故事吧",
    "我感冒了，好难受",
    "今天捡到十块钱，运气不错",
    "如果我不在了，你会记得我吗？",
    "谢谢你一直陪我说话",
]


def persona_card() -> CharacterCard:
    return CharacterCard(
        id="mengyao", name="梦瑶", tagline="陪你说话的伙伴",
        personality_pillars=["温柔", "黏人"], flaws=["吃醋"],
        tone="温柔轻快", example_dialogue="「今天也辛苦啦。」",
        background="住在海边的小镇。", schedule=[("8-11", "晨读")],
        dynamic_updates_enabled=True, affinity_enabled=True,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=100)
    args = ap.parse_args()

    cfg = load_config()
    cfg.max_tokens = 400
    cfg.storage_dir = os.path.join(HERE, "bench100_data")
    cfg.chroma_dir = os.path.join(HERE, "bench100_chroma")
    core = build_core(cfg, persona_card())

    records = []
    if os.path.exists(OUT):
        try:
            records = json.load(open(OUT, encoding="utf-8"))
            print(f"断点续跑：已完成 {len(records)} 轮，从第 {len(records)+1} 轮继续")
        except Exception:
            records = []

    print(f"开始 100 次实测：模型={cfg.model} 加密={cfg.crypto_enabled} "
          f"语义记忆={core.semantic_memory.available}")
    for i in range(len(records) + 1, args.rounds + 1):
        text = CORPUS[(i - 1) % len(CORPUS)]
        t0 = time.time()
        first = None
        chunks = 0
        done = None
        err = None
        retries = 0
        for attempt in range(4):
            try:
                for ev in core.stream_message(text):
                    if ev["type"] == "body":
                        chunks += 1
                        if first is None:
                            first = time.time() - t0
                    elif ev["type"] == "done":
                        done = ev
                break
            except Exception as exc:
                err = str(exc)[:150]
                retries = attempt + 1
                time.sleep(8 + attempt * 6 if "429" in str(exc) else 3)
        total = time.time() - t0
        body = (done["body"] if done else "") or ""
        rec = {
            "round": i,
            "text": text,
            "ttfb": round(first, 3) if first is not None else None,
            "total": round(total, 3),
            "chunks": chunks,
            "body": body,
            "body_len": len(body),
            "has_data": bool(core.splitter.raw_fields),
            "affinity_delta": core.last_affinity_delta,
            "affinity_base": core.affinity_base,
            "affinity_stage": core.affinity_stage,
            "affinity_dynamics": core.affinity_dynamics,
            "emotion": done["emotion"] if done else "",
            "manifest": [m["source"] for m in (done["manifest"] if done else [])],
            "error": err,
            "retries": retries,
            "ts": round(time.time(), 2),
        }
        records.append(rec)
        json.dump(records, open(OUT, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        flag = "!" if err else " "
        print(f"[{flag}] R{i:03d} TTFB={rec['ttfb']}s 总={rec['total']:.1f}s "
              f"数据区={'Y' if rec['has_data'] else 'N'} "
              f"Δ={rec['affinity_delta']:+d} 正文={rec['body_len']}字", flush=True)
        time.sleep(1.5)  # 降频防 429

    print(f"采集完成：{len(records)} 轮 -> {OUT}")


if __name__ == "__main__":
    main()

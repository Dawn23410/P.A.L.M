"""免费模型横向基准：NoneLinear 平台上 12 个免费 LLM 逐个体测。

评估维度（贴合 mentalcore 聊天场景）：
- 可用性：HTTP 200 / 正文非空
- 是否推理型：usage.completion_tokens_details.reasoning_tokens 或 message.reasoning（限死非推理）
- 首字延迟 TTFB（流式首个 content）
- 总耗时（完整回复）
- 数据区遵守：核心是否解析到 ||DATA||（好感度协议）
- 人设回复质量：正文前 60 字（人工判读）

用法：python bench_models.py
"""
import json
import os
import time

import httpx

from mentalcore.config import load_config
from mentalcore.core import build_core
from mentalcore.persona_card import CharacterCard

MODELS = [
    "GLM-4.7-Flash", "GLM-4.5-Flash", "GLM-4.5-Flash-nothink",
    "DeepSeek-R1-0528-Qwen3-8B:free", "Qwen3-8B:free", "Qwen3-8B-nothink:free",
    "GLM-4-9B-0414:free", "GLM-Z1-9B-0414:free", "qwen2.5-1.5b-instruct",
    "GLM-4-Flash", "internlm2_5-7b-chat:free", "xunfei-spark-lite",
]

PROBE_MSG = "你好"
CHAT_MSG = "今天工作好累啊"

HERE = os.path.dirname(os.path.abspath(__file__))


def probe(httpx_client, base_url, headers, model):
    """非流式小请求：探测可用性与是否推理型。"""
    try:
        r = httpx_client.post(
            f"{base_url}/chat/completions",
            json={"model": model, "messages": [{"role": "user", "content": PROBE_MSG}],
                  "max_tokens": 20},
            headers=headers, timeout=30.0,
        )
        if r.status_code != 200:
            return {"ok": False, "http": r.status_code}
        body = r.json()
        msg = (body.get("choices") or [{}])[0].get("message") or {}
        usage = body.get("usage") or {}
        rk = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
        thinking = bool(msg.get("reasoning") or msg.get("reasoning_content") or rk)
        return {"ok": True, "thinking": thinking,
                "probe": (msg.get("content") or "")[:20]}
    except Exception as exc:
        return {"ok": False, "err": repr(exc)[:80]}


def chat_once(cfg, model, idx):
    """mentalcore 全链路一轮：TTFB / 总时长 / 数据区遵守 / 正文。"""
    cfg.model = model
    cfg.storage_dir = os.path.join(HERE, f"bench_data_{idx}")
    cfg.chroma_dir = os.path.join(HERE, f"bench_chroma_{idx}")
    persona = CharacterCard(
        id="mengyao", name="梦瑶", tagline="陪你说话的伙伴",
        personality_pillars=["温柔", "黏人"], flaws=["吃醋"],
        tone="温柔轻快", example_dialogue="「今天也辛苦啦。」",
        background="住在海边的小镇。", schedule=[("8-11", "晨读")],
        dynamic_updates_enabled=True, affinity_enabled=True,
    )
    core = build_core(cfg, persona)
    t0 = time.time()
    first = None
    done = None
    try:
        for ev in core.stream_message(CHAT_MSG):
            if first is None and ev["type"] == "body":
                first = time.time() - t0
            if ev["type"] == "done":
                done = ev
    except Exception as exc:
        return {"err": repr(exc)[:80]}
    total = time.time() - t0
    has_data = bool(core.splitter.raw_fields)
    return {
        "ttfb": round(first, 2) if first else None,
        "total": round(total, 1),
        "has_data": has_data,
        "delta": core.last_affinity_delta,
        "body": (done["body"] if done else "")[:60],
    }


def main():
    cfg = load_config()
    base_url = cfg.base_url.rstrip("/")
    headers = {"Authorization": f"Bearer {cfg.api_key}"}
    client = httpx.Client(timeout=40.0)

    print(f"{'模型':<30}{'推理':<5}{'TTFB':<7}{'总时长':<8}{'数据区':<6}正文摘要")
    print("-" * 100)
    recs = []
    for idx, m in enumerate(MODELS):
        time.sleep(1.5)  # 降频防 429
        p = probe(client, base_url, headers, m)
        if not p.get("ok"):
            print(f"{m:<30}{'-':<5}HTTP{p.get('http', '?')} {p.get('err', '')}")
            continue
        thinking = "是" if p.get("thinking") else "否"
        c = chat_once(cfg, m, idx)
        if "err" in c:
            print(f"{m:<30}{thinking:<5}全链路失败 {c['err']}")
            continue
        data_tag = "✓" if c["has_data"] else "✗"
        print(f"{m:<30}{thinking:<5}{c['ttfb']:<7}{c['total']:<8}{data_tag:<6}{c['body']}")
        recs.append((m, p.get("thinking"), c["ttfb"], c["total"], c["has_data"]))

    client.close()
    print("-" * 100)
    usable = [r for r in recs if r[1] is False and r[4]]
    usable.sort(key=lambda r: r[2] or 99)
    print("非推理且遵守数据区的候选（按 TTFB 排序）：")
    for m, _, ttfb, total, _ in usable:
        print(f"  {m:<30} TTFB={ttfb}s 总={total}s")
    if usable:
        print(f"→ 推荐默认：{usable[0][0]}")


if __name__ == "__main__":
    main()

"""100 轮真实对话采集：用户侧动态生成（基于梦瑶上一条回复），梦瑶侧走 mentalcore live。

- 用户侧：独立「用户扮演」模型，system 约束其自然口语、基于回复反应、有真实情绪弧线。
  不是写死句子池——每句都是对梦瑶上一句的真实反应。
- 梦瑶侧：mentalcore MentalCore（真实 LLM + 各面 + 中间件）。
- 每轮落盘 JSON（断点续跑）；记录情绪 / 好感度轨迹 / 注入源 / 回复长度。

用法：
    python chat_100.py            # 从断点继续 / 从头跑满 100 轮
    python chat_100.py --rounds 30  # 自定义轮数
"""
import argparse
import json
import logging
import os
import sys
import time

import httpx

from mentalcore.config import load_config
from mentalcore.core import build_core
from mentalcore.persona_card import CharacterCard

logging.getLogger("mentalcore").setLevel(logging.WARNING)

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_FILE = os.path.join(HERE, "chat_100_log.json")

USER_SYS = """你是一个真实的年轻人，网名「阿杰」，正在和一个叫梦瑶的 AI 伴侣用聊天软件对话。

规则：
- 你只在微信式聊天里发言，每轮只发一句话或一小段（尽量不超过 40 字），口语、随意，允许错别字和省略。
- 你必须基于梦瑶刚才说的话来回应，像真的在对话，不要自顾自背书或换话题。
- 你是一个有真实情绪的人：一开始有点陌生客气；慢慢会倾诉自己的烦恼（工作累、孤独、想家）；被安慰后会放松、开心、偶尔撒娇；也会因为梦瑶对别人好而吃醋、闹点小脾气；最后变得依赖她。
- 顺着聊，不要每轮都换话题，不要解释你在做什么，不要写旁白或加引号。
- 不要重复你自己或梦瑶说过的话，也不要反复用同一种动作描写（如每轮都「脸红心跳/拥抱」）——换着方式表达同样的心情。
- 只输出你这轮要说的话本身。

如果这是第一句（还没有任何对话历史），就主动打个招呼、简单介绍下自己。"""


def user_say(history, client, url, key, model):
    """用户侧动态生成：基于最近对话历史，产出下一句用户发言。"""
    msgs = [{"role": "system", "content": USER_SYS}]
    if not history:
        msgs.append({"role": "user", "content": "这是对话的第一句，主动打个招呼介绍下自己。"})
    else:
        for turn in history[-8:]:
            msgs.append({"role": "user", "content": turn["user"]})
            msgs.append({"role": "assistant", "content": turn["assistant"]})
        msgs.append({
            "role": "user",
            "content": "现在轮到你说了，基于上面梦瑶最后一句，说出你这轮想说的话（不超过 40 字）。",
        })
    payload = {
        "model": model,
        "messages": msgs,
        "max_tokens": 80,
        "temperature": 0.9,
    }
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    for attempt in range(4):
        try:
            r = client.post(url, json=payload, headers=headers, timeout=45.0)
            if r.status_code == 200:
                body = r.json()
                text = body["choices"][0]["message"]["content"].strip()
                if text:
                    return text
            else:
                print(f"  [用户侧] HTTP {r.status_code}: {r.text[:120]}", flush=True)
        except Exception as exc:
            print(f"  [用户侧] 异常(第{attempt+1}次重试): {exc!r}", flush=True)
        time.sleep(6 + attempt * 4)
    return "（沉默了一会儿）"


def mengyao_reply(core, user_text):
    """梦瑶侧真实回复，带 429 限流退避重试。"""
    last_err = None
    for attempt in range(6):
        try:
            done = None
            assistant_text = ""
            for ev in core.stream_message(user_text):
                if ev["type"] == "body":
                    assistant_text += ev["text"]
                elif ev["type"] == "done":
                    done = ev
            if done is not None:
                return done, assistant_text
        except RuntimeError as exc:
            last_err = exc
            if "429" in str(exc):
                wait = 10 + attempt * 8
                print(f"  [梦瑶侧] 429 限流，退避 {wait}s（第{attempt+1}次）", flush=True)
                time.sleep(wait)
                continue
            raise
        except Exception as exc:  # 其它网络抖动
            last_err = exc
            print(f"  [梦瑶侧] 异常(第{attempt+1}次重试): {exc!r}", flush=True)
            time.sleep(5)
            continue
    raise RuntimeError(f"梦瑶侧重试失败：{last_err}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=100)
    args = ap.parse_args()

    cfg = load_config()
    cfg.storage_dir = os.path.join(HERE, "chat_100_data")
    cfg.chroma_dir = os.path.join(HERE, "chat_100_chroma")
    # 采集跟随预设默认模型（nonelinear=GLM-4.5-Flash-nothink，非推理快模型）
    cfg.max_tokens = 400

    if not cfg.api_key:
        print("未找到 API Key（请配置 .env 的 PRESET=nonelinear + key）。退出。")
        sys.exit(1)

    url = cfg.base_url.rstrip("/") + "/chat/completions"
    key = cfg.api_key
    model = cfg.model

    persona = CharacterCard(
        id="mengyao", name="梦瑶", tagline="陪你说话的伙伴",
        personality_pillars=["温柔", "黏人"], flaws=["吃醋"],
        tone="温柔轻快", example_dialogue="「今天也辛苦啦。」",
        background="住在海边的小镇。", schedule=[("8-11", "晨读")],
        dynamic_updates_enabled=True, affinity_enabled=True,
    )
    core = build_core(cfg, persona)

    # 断点续跑：已有日志则接着跑
    logs = []
    if os.path.exists(OUT_FILE):
        try:
            logs = json.load(open(OUT_FILE, encoding="utf-8"))
            print(f"已加载断点：已完成 {len(logs)} 轮，从第 {len(logs)+1} 轮继续。")
        except Exception:
            logs = []

    # 显式超时，避免大模型慢响应或卡死导致脚本无限挂起（可被样例复制扩散）。
    client = httpx.Client(timeout=httpx.Timeout(connect= 10, read=180, write=15, pool=10))
    start = len(logs) + 1
    total = args.rounds
    print(f"开始采集：目标 {total} 轮，模式={cfg.mode} 模型={model}")

    for i in range(start, total + 1):
        t0 = time.time()
        # 1) 用户侧动态发言
        user_text = user_say(logs, client, url, key, model)
        # 2) 梦瑶侧真实回复（带 429 退避重试）
        done, assistant_text = mengyao_reply(core, user_text)
        if done is None:
            assistant_text = assistant_text or "（梦瑶没有回应）"
        # 3) 记录
        rec = {
            "round": i,
            "user": user_text,
            "assistant": assistant_text.strip(),
            "emotion": done["emotion"] if done else "",
            "affinity_delta": core.last_affinity_delta,
            "affinity_base": core.affinity_base,
            "affinity_dynamics": core.affinity_dynamics,
            "affinity_bond": core.affinity_bond,
            "affinity_stage": core.affinity_stage,
            "manifest": [m["source"] for m in (done["manifest"] if done else [])],
            "assistant_len": len(assistant_text.strip()),
            "ts": time.time(),
            "cost_s": round(time.time() - t0, 1),
        }
        logs.append(rec)
        json.dump(logs, open(OUT_FILE, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        # 进度（每轮打印，便于后台观察）
        print(f"R{i:03d} Δ={rec['affinity_delta']:+d} "
              f"base={rec['affinity_base']:>3} 档={rec['affinity_stage']} "
              f"dyn={rec['affinity_dynamics']:>3} 情绪={rec['emotion']} "
              f"[{rec['cost_s']}s] 用户：{user_text[:24]}", flush=True)
        time.sleep(3)  # 降频，避免触发免费 key 并发限制

    client.close()
    print(f"采集完成：共 {len(logs)} 轮，日志 -> {OUT_FILE}")


if __name__ == "__main__":
    main()

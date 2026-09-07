# -*- coding: utf-8 -*-
"""梦瑶本地引擎 · ollama 式对话启动器（三档）

用法：
    python run_chat.py                # 满血档（bge-m3 全功能，~2.7GB）
    python run_chat.py --balanced     # 性能档（bge-small 语义无重排，~160MB）
    python run_chat.py --lite         # 节省档（纯 mock lexical，~32MB）

命令：
    /stats  上一轮的置信度/延迟/是否兜底
    /reset  清空对话记忆
    /exit   退出
"""
import os
import sys
import time

# 包根 = 本脚本所在目录（独立包可整体移动，不做绝对路径绑定）
ROOT = os.path.dirname(os.path.abspath(__file__))

TIERS = {
    "full":     ("满血档 · bge-m3 语义 + reranker/连贯重排全开（~2.7GB）", None),
    "balanced": ("性能档 · bge-small 语义，无重排（~160MB）", None),
    "lite":     ("节省档 · 纯 mock lexical 检索（~32MB）", None),
}


def build_engine(tier: str):
    sys.path.insert(0, ROOT)
    from local_reply.engine.engine import StitchEngine
    eng = StitchEngine(tier=tier)
    from local_reply.engine import embed as _embed
    if eng.mode == "semantic":
        desc = f"语义模式（{_embed.model_tag()}，{_embed.dim()} 维，阈值 {eng.confidence_threshold}）"
    else:
        desc = "mock 模式（lexical 检索）"
    if tier == "full" and eng.mode != "semantic":
        desc += "  [!] 语义权重不可用，已降级 mock"
    return eng, f"{TIERS[tier][0]}  |  {desc}"


def main() -> None:
    args = sys.argv[1:]
    tier = next((t for f, t in (("--full", "full"), ("--balanced", "balanced"),
                                ("--lite", "lite")) if f in args), "full")
    eng, desc = build_engine(tier)

    history = []
    last = {"conf": 0.0, "ms": 0.0, "fallback": False}
    print("=" * 60)
    print(" 梦瑶 · 本地对话引擎（独立包 v1.0）")
    print(f" 档位: {desc}")
    print(" 命令: /stats 状态 | /reset 清记忆 | /exit 退出")
    print("=" * 60)
    print("梦瑶：来啦？坐，想聊什么随便点喵～")

    while True:
        try:
            user = input("\n你 >>> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n梦瑶：溜了？行吧，下次早点来喵～")
            break
        if not user:
            continue
        if user == "/exit":
            print("梦瑶：溜了？行吧，下次早点来喵～")
            break
        if user == "/reset":
            history = []
            if isinstance(eng.memory.get("recent_replies"), list):
                eng.memory["recent_replies"] = []
            if isinstance(eng.memory.get("queries"), list):
                eng.memory["queries"] = []
            print("[记忆已清空]")
            continue
        if user == "/stats":
            print(f"[上一轮] conf={last['conf']}  {last['ms']}ms  "
                  f"fallback={last['fallback']}")
            continue

        t0 = time.perf_counter()
        r = eng.respond(user, history)
        last = {
            "conf": round(float(r.get("confidence") or 0), 3),
            "ms": round((time.perf_counter() - t0) * 1000, 1),
            "fallback": bool(r.get("suggest_llm")),
        }
        reply = r.get("reply", "")
        print(f"\n梦瑶 >>> {reply}")
        history.append((user, reply))


if __name__ == "__main__":
    main()

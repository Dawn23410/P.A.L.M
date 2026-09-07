# -*- coding: utf-8 -*-
"""混合路由：local_reply 引擎作「域内快桩」，LLM 作「域外大脑」。

这是「在聊天范围吊打 8B」的核心机制——不是让检索桩去硬拼 8B 的通用智能，
而是让引擎吃掉绝大多数陪伴聊天轮次（亚 4ms、人设锁定、零幻觉），
只在它不自信时把长尾交给 8B。组合系统同时优于「纯 8B」：
  · 速度：多数轮次 ~2ms vs 8B 的 400–1200ms
  · 人设：引擎轮次 0 破功，8B 会漂移
  · 幻觉：引擎只缝合既定语料，不编造
  · 成本：8B 调用量降到长尾比例

路由判据 = 引擎返回结构里的 recognized / suggest_llm / confidence：
- recognized=True  → 引擎直接回（快路径）
- recognized=False → 转交 LLM（诚实降级，不硬答）

LLM 侧用可调用对象注入（callable: str -> str），不绑定任何具体后端，
便于接 GLM-4 / DeepSeek / 本地 Qwen2.5-8B，或测试时传桩函数。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from .engine import StitchEngine


@dataclass
class RouteResult:
    """一次路由的结果，含可观测字段便于压测与验收。"""
    reply: str
    source: str                 # "engine" | "llm"
    confidence: float
    elapsed_ms: float
    engine_meta: dict = field(default_factory=dict)


class HybridRouter:
    """引擎快路径 + LLM 兜底的混合聊天路由。"""

    def __init__(self, engine: StitchEngine | None = None, llm_callable=None):
        self.engine = engine or StitchEngine()
        self.llm = llm_callable
        # 观测计数，用于验收"引擎吃掉多少比例"
        self.stats = {"total": 0, "engine": 0, "llm": 0}

    def chat(self, query: str, history: list[str] | None = None) -> RouteResult:
        history = history or []
        t0 = time.perf_counter()
        res = self.engine.respond(query, history)
        self.stats["total"] += 1

        if res["recognized"]:
            self.stats["engine"] += 1
            return RouteResult(
                reply=res["reply"],
                source="engine",
                confidence=res.get("confidence", 0.0),
                elapsed_ms=(time.perf_counter() - t0) * 1000,
                engine_meta=res,
            )

        # 不自信 → 交 LLM；未注入 LLM 时回退引擎的诚实兜底文案
        self.stats["llm"] += 1
        if self.llm is None:
            return RouteResult(
                reply=res["reply"],          # 引擎诚实的"去问 LLM"文案
                source="llm",                # 语义上属于应转 LLM 的份额
                confidence=res.get("confidence", 0.0),
                elapsed_ms=(time.perf_counter() - t0) * 1000,
                engine_meta=res,
            )
        t1 = time.perf_counter()
        # LLM 返回空视为失败：回退引擎的诚实兜底文案，避免把空串当回复吐给用户
        reply = self.llm(query) or res["reply"]
        return RouteResult(
            reply=reply,
            source="llm",
            confidence=res.get("confidence", 0.0),
            elapsed_ms=(time.perf_counter() - t1) * 1000,
            engine_meta=res,
        )

    @property
    def engine_share(self) -> float:
        """引擎处理的轮次占比（越高越省 8B 调用）。"""
        if not self.stats["total"]:
            return 0.0
        return round(self.stats["engine"] / self.stats["total"], 3)


def fake_llm(query: str) -> str:
    """测试用 LLM 桩：模拟 8B 的响应（含其典型延迟由调用方施加）。"""
    return f"[8B 回答] 关于「{query}」，这是一个需要通用推理的问题……"

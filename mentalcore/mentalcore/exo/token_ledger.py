"""Token 计量台账（移植自 palm services/ops/token_ledger + token_usage 语义，内存态）。

记录每次 LLM 调用的 prompt/completion token 与估算成本（按 10M token 计价模型），
供用量统计/预算控制/成本核算。接入点：ExoLLM.complete 调用后经 usage 记账。
"""
from __future__ import annotations

import time

# 估算单价（元/1M token，输入/输出；OpenAI 风格粗略值，可按需改）
_PRICE_IN = 1.0
_PRICE_OUT = 3.0


class TokenLedger:
    """会话级 Token 台账：逐条记账 + 汇总 + 预算闸门。"""

    def __init__(self, budget: float | None = None):
        self.entries: list[dict] = []
        self.budget = budget  # 预算上限（元），None=不限制

    def record(self, side: str, prompt_tokens: int = 0, completion_tokens: int = 0) -> None:
        """记一笔（side: boss/worker/planner）。"""
        cost = (prompt_tokens / 1_000_000 * _PRICE_IN
                + completion_tokens / 1_000_000 * _PRICE_OUT)
        self.entries.append({
            "ts": time.strftime("%H:%M:%S"), "side": side,
            "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
            "cost_yuan": round(cost, 6),
        })

    def totals(self) -> dict:
        prompt = sum(e["prompt_tokens"] for e in self.entries)
        completion = sum(e["completion_tokens"] for e in self.entries)
        return {"calls": len(self.entries), "prompt_tokens": prompt,
                "completion_tokens": completion,
                "total_tokens": prompt + completion,
                "cost_yuan": round(sum(e["cost_yuan"] for e in self.entries), 6)}

    def over_budget(self) -> bool:
        if self.budget is None:
            return False
        return self.totals()["cost_yuan"] > self.budget

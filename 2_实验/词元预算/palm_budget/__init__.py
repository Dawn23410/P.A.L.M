"""palm_budget — 上下文窗口 token 预算分配器（内嵌独立项目）。

提供 TokenBudgetAllocator：把模型上下文窗口按固定比例切分为
core / recent / program / archived / system / conversation 等槽位，
并监控对话占用、去抖触发压缩信号。

零依赖（仅标准库），可供 palm-memory / palm-llm 等共享，
不耦合任何记忆或 LLM 实现。

用法：
    from palm_budget import TokenBudgetAllocator, Budget
    alloc = TokenBudgetAllocator(model_window=128000)
    budget = alloc.calculate()          # Budget(core=…, archived=…, …)
    signal = alloc.monitor(conv_tokens)  # "compress" | None
"""
from __future__ import annotations

from .token_budget import Budget, TokenBudgetAllocator

__all__ = ["Budget", "TokenBudgetAllocator"]

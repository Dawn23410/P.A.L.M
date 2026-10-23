"""有界重试策略 —— 企业级稳定度与个人低延迟，是**同一个旋钮**的两端。

为什么把"重试"做成策略数据而不是两套代码
----------------------------------------
"要不要重试、退避多久、要不要等 Retry-After"是**策略**，不是机制。机制只实现一次
（有界循环 + 分类判定），把旋钮做成数据：

  - 个人桌面 → `LOW_LATENCY`：最多重试 1 次、**退避 0 秒**（不拖首字）；
  - 企业部署 → `STABLE`：3 次、指数退避、抖动、尊重 `Retry-After`。

同一份 provider 代码，换 `RetryPolicy` 即可，无需分支。`ProviderConfig.retry`
留空则用 `DEFAULT`（低延迟档，与内核既有行为一致）。

抖动（jitter）为什么必要
------------------------
纯指数退避会让一批同时在故障中重试的请求**再次同时**打过去（惊群）。抖动把它们的
重试时刻打散，是"企业级"过故障期的基本要求；但它对单用户桌面毫无价值，故默认 0。
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional

from .errors import PalmLLMError


@dataclass(frozen=True)
class RetryPolicy:
    """重试策略（不可变，可安全跨协程共享）。"""

    max_attempts: int = 2      # 含首次；2 = 只重试 1 次
    base_delay: float = 0.0    # 秒；0 = 立即重试
    max_delay: float = 8.0
    jitter: float = 0.0        # 0..1：延时的随机浮动比例（打散惊群）
    respect_retry_after: bool = True

    def delay_for(self, attempt: int, exc: Optional[BaseException] = None) -> float:
        """第 `attempt` 次失败后应等待的秒数（attempt 从 1 计）。

        优先级：上游明示的 `Retry-After` ＞ 指数退避。上游既然说了等多久，
        我们就该照做（既不打脸，也能最快恢复）。
        """
        if self.respect_retry_after:
            retry_after = getattr(exc, "retry_after", None)
            if retry_after:
                return min(float(retry_after), self.max_delay)
        delay = min(self.base_delay * (2 ** (attempt - 1)), self.max_delay)
        if delay and self.jitter:
            delay *= 1.0 + random.uniform(-self.jitter, self.jitter)
        return max(0.0, delay)


# 两档预设：个人桌面（低延迟）/ 企业（高稳）。代码同一份，只换这里。
LOW_LATENCY = RetryPolicy(max_attempts=2, base_delay=0.0)
STABLE = RetryPolicy(max_attempts=3, base_delay=0.5, jitter=0.3)

DEFAULT = LOW_LATENCY


def is_retryable(exc: Optional[BaseException]) -> bool:
    """只有被显式标了 `retryable` 的错误才重试 —— 默认不可重试（安全侧）。"""
    return isinstance(exc, PalmLLMError) and exc.retryable


__all__ = ["RetryPolicy", "LOW_LATENCY", "STABLE", "DEFAULT", "is_retryable"]

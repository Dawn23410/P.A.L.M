"""重试策略：退避、上限、抖动、Retry-After（纯逻辑，无需网络）。

覆盖：
  - 两档预设：LOW_LATENCY（退避恒 0，不拖首字）/ STABLE（3 次 + 指数退避）
  - 指数退避与封顶
  - `Retry-After` 优先级与封顶、可关闭
  - 抖动落在约定带内
  - `is_retryable` 默认安全侧（非 PalmLLMError / 不可重试类 → False）
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from palm_llm.errors import AuthError, RateLimitError, TransportError  # noqa: E402
from palm_llm.retry import (  # noqa: E402
    DEFAULT,
    LOW_LATENCY,
    STABLE,
    RetryPolicy,
    is_retryable,
)


class DelayTest(unittest.TestCase):
    def test_low_latency_never_waits(self):
        """低延迟档：退避恒为 0 —— 重试不把首字往后拖。"""
        self.assertEqual(LOW_LATENCY.delay_for(1, TransportError("x")), 0.0)
        self.assertEqual(LOW_LATENCY.delay_for(2, TransportError("x")), 0.0)

    def test_exponential_and_cap(self):
        p = RetryPolicy(base_delay=1.0, max_delay=4.0, jitter=0.0)
        self.assertEqual(p.delay_for(1), 1.0)
        self.assertEqual(p.delay_for(2), 2.0)
        self.assertEqual(p.delay_for(3), 4.0)
        self.assertEqual(p.delay_for(4), 4.0)          # 封顶，不再翻倍

    def test_retry_after_wins_over_backoff(self):
        p = RetryPolicy(base_delay=1.0, max_delay=10.0)
        self.assertEqual(p.delay_for(1, RateLimitError("busy", retry_after=7)), 7.0)

    def test_retry_after_respects_cap(self):
        p = RetryPolicy(base_delay=1.0, max_delay=5.0)
        self.assertEqual(p.delay_for(1, RateLimitError("busy", retry_after=99)), 5.0)

    def test_retry_after_can_be_ignored(self):
        p = RetryPolicy(base_delay=1.0, max_delay=10.0, respect_retry_after=False)
        self.assertEqual(p.delay_for(1, RateLimitError("busy", retry_after=7)), 1.0)

    def test_jitter_stays_in_band(self):
        p = RetryPolicy(base_delay=2.0, max_delay=100.0, jitter=0.5)
        for _ in range(100):
            d = p.delay_for(1)
            self.assertGreaterEqual(d, 1.0)            # 2*(1-0.5)
            self.assertLessEqual(d, 3.0)               # 2*(1+0.5)

    def test_negative_jitter_cannot_go_below_zero(self):
        p = RetryPolicy(base_delay=0.01, max_delay=1.0, jitter=1.0)
        for _ in range(100):
            self.assertGreaterEqual(p.delay_for(1), 0.0)


class RetryableTest(unittest.TestCase):
    def test_flags(self):
        self.assertTrue(is_retryable(TransportError("x")))
        self.assertTrue(is_retryable(RateLimitError("x")))
        self.assertFalse(is_retryable(AuthError("x")))
        self.assertFalse(is_retryable(None))
        self.assertFalse(is_retryable(RuntimeError("plain")))   # 非 PalmLLMError

    def test_presets(self):
        self.assertIs(DEFAULT, LOW_LATENCY)          # 默认低延迟档（对齐既有行为）
        self.assertEqual(LOW_LATENCY.max_attempts, 2)
        self.assertEqual(LOW_LATENCY.base_delay, 0.0)
        self.assertEqual(STABLE.max_attempts, 3)
        self.assertGreater(STABLE.base_delay, 0.0)
        self.assertGreater(STABLE.jitter, 0.0)

    def test_policy_is_hashable_and_immutable(self):
        """frozen dataclass：可安全跨协程共享，不被就地改写。"""
        p = RetryPolicy()
        with self.assertRaises(Exception):
            p.max_attempts = 9  # type: ignore[misc]
        self.assertEqual(hash(p), hash(RetryPolicy()))


if __name__ == "__main__":
    unittest.main(verbosity=2)

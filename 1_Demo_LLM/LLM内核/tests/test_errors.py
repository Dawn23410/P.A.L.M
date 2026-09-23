"""类型化异常层与状态码分类（纯逻辑，无需网络）。

覆盖：
  - 兼容契约：全部类型化错误仍可被 `except RuntimeError` 兜住
  - `retryable` 标记：只有传输/5xx/429 可重试
  - `classify_error(status=…)` 状态码 → 类型映射
  - `classify_error(exc=…, interrupted=True)` 分支（已产出后中断 → 绝不重试）
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from palm_llm.errors import (  # noqa: E402
    AuthError,
    BadRequestError,
    CapabilityError,
    NotConfiguredError,
    PalmLLMError,
    RateLimitError,
    StreamInterruptedError,
    TransportError,
    UpstreamServerError,
    classify_error,
)

ALL_TYPES = (TransportError, UpstreamServerError, RateLimitError, AuthError,
             BadRequestError, NotConfiguredError, StreamInterruptedError, CapabilityError)


class HierarchyTest(unittest.TestCase):
    def test_all_errors_are_runtimeerror(self):
        """兼容契约：换成类型化层级不能打穿既有 `except RuntimeError` 兜底。"""
        for cls in ALL_TYPES:
            with self.subTest(cls=cls.__name__):
                self.assertTrue(issubclass(cls, PalmLLMError))
                self.assertTrue(issubclass(cls, RuntimeError))

    def test_retryable_flags(self):
        self.assertTrue(TransportError("x").retryable)
        self.assertTrue(UpstreamServerError("x").retryable)
        self.assertTrue(RateLimitError("x").retryable)
        self.assertFalse(AuthError("x").retryable)
        self.assertFalse(BadRequestError("x").retryable)
        self.assertFalse(NotConfiguredError("x").retryable)
        self.assertFalse(StreamInterruptedError("x").retryable)
        self.assertFalse(CapabilityError("x").retryable)

    def test_context_is_carried(self):
        e = RateLimitError("busy", provider="zhipu", model="glm", status=429, retry_after=3)
        self.assertEqual(e.provider, "zhipu")
        self.assertEqual(e.model, "glm")
        self.assertEqual(e.status, 429)
        self.assertEqual(e.retry_after, 3)

    def test_message_string_is_preserved(self):
        self.assertEqual(str(TransportError("连接失败：boom")), "连接失败：boom")


class StatusClassifyTest(unittest.TestCase):
    def test_status_to_type(self):
        cases = {429: RateLimitError, 401: AuthError, 403: AuthError,
                 400: BadRequestError, 404: BadRequestError, 422: BadRequestError,
                 500: UpstreamServerError, 503: UpstreamServerError, 502: UpstreamServerError}
        for status, cls in cases.items():
            with self.subTest(status=status):
                err = classify_error(f"[p] {status}: boom", status=status)
                self.assertIsInstance(err, cls)
                self.assertEqual(err.status, status)

    def test_message_and_text_kept(self):
        err = classify_error("[p] 400: budget_tokens is not supported",
                             status=400, text="budget_tokens is not supported")
        self.assertIn("budget_tokens is not supported", str(err))
        self.assertEqual(err.text, "budget_tokens is not supported")


class TransportClassifyTest(unittest.TestCase):
    def test_interrupted_is_never_retryable(self):
        """已产出内容后中断 → StreamInterruptedError（防重复生成/重复计费）。"""
        err = classify_error("[p] 连接失败", exc=RuntimeError("reset"), interrupted=True)
        self.assertIsInstance(err, StreamInterruptedError)
        self.assertFalse(err.retryable)

    def test_transport_is_retryable(self):
        err = classify_error("[p] 连接失败", exc=RuntimeError("reset"))
        self.assertIsInstance(err, TransportError)
        self.assertTrue(err.retryable)

    def test_none_exc_still_typed(self):
        err = classify_error("[p] 请求失败")
        self.assertIsInstance(err, TransportError)


if __name__ == "__main__":
    unittest.main(verbosity=2)

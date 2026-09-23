"""可观测层：request_id 传播与结构化日志（纯逻辑 + 轻量线程）。

覆盖：
  - request_id 生成形态、读/建语义、跨 await 传播、跨 context 隔离
  - 日志装配幂等、调用不抛错、低级别被丢弃（不是异常）
"""
from __future__ import annotations

import asyncio
import contextvars
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from palm_llm import obs  # noqa: E402


class RequestIdTest(unittest.TestCase):
    def test_generated_id_is_fresh_per_context(self):
        """未设置 id 的 context 各生成各的 12 位 id（互不串号）。

        用**全新** `contextvars.Context()`（不继承当前上下文）—— 否则会读到上一个
        用例种下的 id，看起来"不新鲜"，实际是测试自己没隔离。
        """
        a = contextvars.Context().run(obs.request_id)
        b = contextvars.Context().run(obs.request_id)
        self.assertEqual(len(a), 12)
        self.assertNotEqual(a, b)

    def test_set_then_read(self):
        obs.set_request_id("abc123")
        self.assertEqual(obs.request_id(), "abc123")

    def test_set_none_generates(self):
        obs.set_request_id(None)
        rid = obs.request_id()
        self.assertNotEqual(rid, "-")
        self.assertEqual(len(rid), 12)

    def test_read_is_stable(self):
        """已有 id 时读取不覆盖；未有时生成一次并落定。"""
        obs.set_request_id("keepme")
        self.assertEqual(obs.request_id(), "keepme")
        self.assertEqual(obs.request_id(), "keepme")

    def test_propagates_across_await(self):
        async def inner():
            return obs.request_id()

        async def run():
            obs.set_request_id("through-await")
            await asyncio.sleep(0)           # 跨一次挂起点
            return await inner()

        self.assertEqual(asyncio.run(run()), "through-await")

    def test_isolated_between_contexts(self):
        """两个独立 context 的 request_id 互不串号（并发请求不会串日志）。"""
        def worker(rid):
            obs.set_request_id(rid)
            return obs.request_id()

        ctx_a = contextvars.copy_context()
        ctx_b = contextvars.copy_context()
        self.assertEqual(ctx_a.run(worker, "aaaa"), "aaaa")
        self.assertEqual(ctx_b.run(worker, "bbbb"), "bbbb")


class LoggingTest(unittest.TestCase):
    def tearDown(self):
        obs.configure_logging("WARNING")

    def test_log_event_does_not_raise(self):
        obs.configure_logging("DEBUG")
        obs.log_event("test.event", level="debug", provider="p", model="m", n=1)
        obs.log_event("test.warn", level="warning")

    def test_configure_is_idempotent(self):
        obs.configure_logging("INFO")
        logger = obs.configure_logging("WARNING")     # 再调一次只改级别，不重复起线程
        self.assertEqual(logger.name, "palm_llm")

    def test_low_level_is_dropped_not_raised(self):
        obs.configure_logging("ERROR")
        obs.log_event("test.silent", level="debug")   # 低于阈值 → 静默丢弃

    def test_unknown_level_falls_back(self):
        obs.configure_logging("DEBUG")
        obs.log_event("test.weirdlevel", level="notalevel")   # 未知级别回落 info，不抛错


if __name__ == "__main__":
    unittest.main(verbosity=2)

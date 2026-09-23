"""回传拆分器用例（纯逻辑，无需网络）。

覆盖：
  - `usage_from(raw, protocol)` 的口径归一 —— 四种协议共用**同一个入口**，
    含缓存字段方言与"总输入是否含缓存"的陷阱
  - 派生指标的算式（TTFT/TTFA/TPOT/NTPOT/ITL 分位/输出速度/缓存命中率）
  - 停止原因映射
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from palm_llm.providers._telemetry import (
    Meter,
    TurnStats,
    _derive,
    _pct,
    map_stop_reason,
    mark_finish_tool_calls,
    usage_from,
)


class UsageNormalizeTest(unittest.TestCase):
    def test_openai_standard_splits_cache_out_of_prompt(self):
        """OpenAI 的 prompt_tokens 含缓存命中，统一口径要把它拆出来。"""
        got = usage_from({
            "prompt_tokens": 1000, "completion_tokens": 200, "total_tokens": 1200,
            "prompt_tokens_details": {"cached_tokens": 900},
            "completion_tokens_details": {"reasoning_tokens": 120},
        }, "openai")
        self.assertEqual(got["input_tokens"], 100)      # 非缓存输入
        self.assertEqual(got["cache_read_tokens"], 900)
        self.assertEqual(got["output_tokens"], 200)
        self.assertEqual(got["reasoning_tokens"], 120)

    def test_openai_deepseek_dialect(self):
        got = usage_from({
            "prompt_tokens": 1000, "completion_tokens": 50,
            "prompt_cache_hit_tokens": 800, "prompt_cache_miss_tokens": 200,
        }, "openai")
        self.assertEqual(got["input_tokens"], 200)      # 直接用 miss 数，最准
        self.assertEqual(got["cache_read_tokens"], 800)

    def test_openai_without_details_passes_through(self):
        got = usage_from({"prompt_tokens": 10, "completion_tokens": 5}, "openai")
        self.assertEqual(got["input_tokens"], 10)
        self.assertEqual(got["cache_read_tokens"], 0)

    def test_anthropic_input_excludes_cache(self):
        """Anthropic 的 input_tokens 已排除缓存，不能再减一次。"""
        got = usage_from({
            "input_tokens": 100, "output_tokens": 200,
            "cache_read_input_tokens": 900, "cache_creation_input_tokens": 50,
        }, "anthropic")
        self.assertEqual(got["input_tokens"], 100)
        self.assertEqual(got["cache_read_tokens"], 900)
        self.assertEqual(got["cache_write_tokens"], 50)
        self.assertEqual(got["total_tokens"], 1250)     # 100+900+50+200

    def test_ollama_carries_engine_timings(self):
        got = usage_from({
            "prompt_eval_count": 20, "eval_count": 30,
            "load_duration": 2_000_000_000, "prompt_eval_duration": 60_000_000,
            "eval_duration": 500_000_000, "total_duration": 3_000_000_000,
        }, "ollama")
        self.assertEqual(got["total_tokens"], 50)
        self.assertEqual(got["extra"]["load_ms"], 2000.0)
        self.assertEqual(got["extra"]["eval_ms"], 500.0)
        # 引擎侧分段耗时同时提升为一等字段，供输出速度用引擎口径
        self.assertEqual(got["prefill_ms"], 60.0)
        self.assertEqual(got["decode_ms"], 500.0)

    def test_stop_reason_mapping(self):
        self.assertEqual(map_stop_reason("end_turn"), "stop")
        self.assertEqual(map_stop_reason("tool_use"), "tool_calls")
        self.assertEqual(map_stop_reason("max_tokens"), "length")
        self.assertEqual(map_stop_reason("stop"), "stop")   # 已是目标口径则原样
        self.assertEqual(map_stop_reason(None), "")

    def test_gemini_usage_subtracts_cached_from_prompt(self):
        """Gemini 的 promptTokenCount 含缓存命中，要减出去才是非缓存输入。"""
        got = usage_from({"promptTokenCount": 100, "cachedContentTokenCount": 60,
                                 "candidatesTokenCount": 5, "thoughtsTokenCount": 7,
                                 "totalTokenCount": 172}, "gemini")
        self.assertEqual(got["input_tokens"], 40)
        self.assertEqual(got["cache_read_tokens"], 60)
        self.assertEqual(got["output_tokens"], 5)
        self.assertEqual(got["reasoning_tokens"], 7)       # 思考 token 单列
        self.assertEqual(got["total_tokens"], 172)


class FinishReasonNormalizeTest(unittest.TestCase):
    """有工具调用时 finish_reason 必须归一为 tool_calls。

    动机：调用方按 finish_reason 分支是常态；Ollama 在工具调用时仍报 stop、
    Gemini 报 STOP，不归一就会让工具**静默不执行**（与 tooltext 文本降级同一类问题）。
    """

    def test_stop_becomes_tool_calls_and_keeps_vendor_value(self):
        stats = {"finish_reason": "stop", "extra": {}}
        mark_finish_tool_calls(stats)
        self.assertEqual(stats["finish_reason"], "tool_calls")
        self.assertEqual(stats["extra"]["finish_reason_vendor"], "stop")

    def test_vendor_value_preserved_on_bare_stats(self):
        """没有 extra 也要能记 —— 旧路径回传的 stats 未必带 extra。"""
        stats = {"finish_reason": "STOP"}
        mark_finish_tool_calls(stats)
        self.assertEqual(stats["finish_reason"], "tool_calls")
        self.assertEqual(stats["extra"]["finish_reason_vendor"], "STOP")

    def test_already_tool_calls_is_idempotent(self):
        stats = {"finish_reason": "tool_calls", "extra": {}}
        mark_finish_tool_calls(stats)
        self.assertEqual(stats["finish_reason"], "tool_calls")
        self.assertNotIn("finish_reason_vendor", stats["extra"])

    def test_does_not_clobber_a_prior_vendor_value(self):
        """两次调用（如流式补帧）只应记录第一次的原值。"""
        stats = {"finish_reason": "stop", "extra": {}}
        mark_finish_tool_calls(stats)
        mark_finish_tool_calls(stats)
        self.assertEqual(stats["extra"]["finish_reason_vendor"], "stop")

    def test_non_dict_is_ignored(self):
        mark_finish_tool_calls(None)   # 不应抛异常


class DeriveTest(unittest.TestCase):
    def _stats(self) -> TurnStats:
        return TurnStats(input_tokens=100, cache_read_tokens=900, output_tokens=200,
                         ttft_ms=500.0, ttfa_ms=1500.0, total_ms=2500.0)
    def test_derived_metrics(self):
        s = self._stats()
        _derive(s, [10.0, 10.0, 10.0, 10.0, 100.0])
        self.assertEqual(s.total_tokens, 1200)
        self.assertEqual(s.thinking_ms, 1000.0)          # 纯思考耗时
        self.assertEqual(s.ntpot_ms, 12.5)               # 2500/200
        self.assertEqual(s.tpot_ms, 10.1)                # (2500-500)/199
        self.assertEqual(s.tps, 100.0)                   # 200/2000ms
        self.assertEqual(s.tps_total, 80.0)              # 200/2500ms
        self.assertEqual(s.itl_p50_ms, 10.0)
        self.assertEqual(s.itl_p90_ms, 100.0)            # 分位数不被多数派淹没
        self.assertEqual(s.cache_hit_rate, 0.9)

    def test_engine_decode_time_wins_over_wall_clock(self):
        """有引擎侧解码耗时时，输出速度用它 —— 排除排队与网络。"""
        s = self._stats()
        s.decode_ms = 1000.0
        _derive(s, [])
        self.assertEqual(s.tps, 200.0)

    def test_zero_output_does_not_divide_by_zero(self):
        s = TurnStats()
        _derive(s, [])
        self.assertEqual(s.total_tokens, 0)
        self.assertEqual(s.tps, 0.0)
        self.assertEqual(s.cache_hit_rate, 0.0)

    def test_percentile_clamps_out_of_range(self):
        self.assertEqual(_pct([1.0], 90), 1.0)
        self.assertEqual(_pct([1.0, 2.0, 3.0], 50), 2.0)
        self.assertEqual(_pct([1.0, 2.0, 3.0, 4.0], 90), 4.0)


class MeterTest(unittest.TestCase):
    def test_collects_text_and_timing(self):
        m = Meter(model="m")
        m.mark_ack()
        m.feed("reasoning", "想一下")
        m.feed("content", "你好")
        m.feed("content", "世界")
        got = m.finish(usage_from({"prompt_tokens": 3, "completion_tokens": 2}, "openai"),
                       finish_reason="stop", extra={"response_id": "r1"})
        self.assertEqual(got["reasoning_text"], "想一下")
        self.assertEqual(got["content_text"], "你好世界")
        self.assertEqual(got["chunks"], 3)
        self.assertEqual(got["finish_reason"], "stop")
        self.assertEqual(got["extra"]["response_id"], "r1")
        # 计时精度为 0.1ms，本机跑得够快时可能压到 0 → 只断言单调关系
        self.assertGreaterEqual(got["total_ms"], got["ttft_ms"])
        self.assertGreaterEqual(got["ttft_ms"], 0.0)
        # TTFA 只认正文帧：思考帧不能算"首个正文 token"
        self.assertGreaterEqual(got["ttfa_ms"], got["ttft_ms"])

    def test_itl_covers_all_output_frames(self):
        """ITL 记所有输出帧的间隔，但 TTFA 只认正文帧。"""
        m = Meter()
        m.feed("reasoning", "A" * 100)
        m.feed("reasoning", "B" * 100)
        got = m.finish()
        self.assertEqual(got["chunks"], 2)
        self.assertEqual(got["ttfa_ms"], 0.0)      # 全程没出现正文帧
        self.assertEqual(got["thinking_ms"], 0.0)

    def test_finish_without_usage_is_safe(self):
        m = Meter()
        m.feed("content", "x")
        got = m.finish()
        self.assertEqual(got["output_tokens"], 0)
        self.assertEqual(got["total_tokens"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

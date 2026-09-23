"""回传拆分器：把各家原始响应归一为统一字段（内容 / token / 计时 / 派生指标）。

为什么需要「拆分」
------------------
同一件事各家字段名与**口径**都不同，只做字段名映射会算出错的数：

- 缓存命中：OpenAI `prompt_tokens_details.cached_tokens`、DeepSeek `prompt_cache_hit_tokens`、
  Anthropic `cache_read_input_tokens`、Gemini `cachedContentTokenCount`。
- 思考 token：OpenAI `completion_tokens_details.reasoning_tokens`、Gemini `thoughtsTokenCount`；
  Anthropic **不单列** —— 只能报 0，不编数。
- 口径陷阱：OpenAI 系的 `prompt_tokens` **含**缓存命中，Anthropic 的 `input_tokens` **不含**。
  故本模块统一为：`input_tokens` = 非缓存输入，`total_tokens` = 输入 + 缓存读 + 缓存写 + 输出。

指标口径（对齐业界基准口径）
----------------------------
- **TTFT**（首 token 延迟）：请求发出 → 第一个输出帧（含思考帧）。
- **TTFA**（首个正文 token）：请求发出 → 第一个正文帧。思考模型上 `TTFA - TTFT` = 纯思考耗时。
  不拆这一项的话，"首字延迟"在思考模型上会被思考时间完全掩盖。
- **TT_ACK**（首响应头）：请求发出 → HTTP 响应头到达。用于把网络/排队/路由与推理自身分开。
- **TPOT** = (端到端 - TTFT) / (输出 token - 1)；**NTPOT** = 端到端 / 输出 token。
- **ITL**：相邻正文帧间隔，取 p50/p90 —— 个别卡顿会把均值拉偏，分位数更能反映"卡不卡"。
- **tps**：输出 token / 解码时长（有引擎侧解码耗时时优先用它，排除排队与网络）。
- **tps_total**：输出 token / 端到端。

不编数据
--------
厂商没返回的一律留 0，不用 chunk 数冒充 token 数。推理帧是批量下发的（思考内容尤其
"成块"到达），按帧计数必然低估。
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Optional

# 停止原因统一为 OpenAI 口径；Anthropic 原生用另一套词
STOP_REASON_MAP = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "max_tokens": "length",
    "model_context_window_exceeded": "length",
    "tool_use": "tool_calls",
    "refusal": "content_filter",
    "pause_turn": "pause",
}

# OpenAI 系 usage 中"缓存写入"的几种叫法
_WRITE_KEYS = ("cache_creation_input_tokens", "prompt_cache_write_tokens")


@dataclass
class TurnStats:
    """一次请求的回传统一字段。字段宁多勿少；厂商未提供的留 0。"""

    # ── 元信息 ──
    model: str = ""
    response_id: str = ""
    finish_reason: str = ""
    stop_sequence: str = ""

    # ── 内容（累积全文，供非流式消费方一次取用；流式消费方看事件流即可）──
    reasoning_text: str = ""
    content_text: str = ""

    # ── token 计数（口径已归一，见模块文档）──
    input_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0

    # ── 计时（毫秒）──
    ttack_ms: float = 0.0
    ttft_ms: float = 0.0
    ttfa_ms: float = 0.0
    total_ms: float = 0.0
    prefill_ms: float = 0.0        # 引擎侧提示预填充耗时（如 ollama）
    decode_ms: float = 0.0         # 引擎侧解码耗时（如 ollama）
    chunks: int = 0

    # ── 派生 ──
    thinking_ms: float = 0.0
    tpot_ms: float = 0.0
    ntpot_ms: float = 0.0
    itl_p50_ms: float = 0.0
    itl_p90_ms: float = 0.0
    tps: float = 0.0
    tps_total: float = 0.0
    cache_hit_rate: float = 0.0

    extra: dict = field(default_factory=dict)   # 厂商专有（如 load_ms）

    def to_dict(self) -> dict:
        return asdict(self)


class Meter:
    """一次请求的计时 / 计数累加器（流式与非流式共用）。

    生命周期：`mark_ack()` → `feed()`×N → `finish(usage)`。
    """

    def __init__(self, model: str = "", response_id: str = ""):
        self._t0 = time.perf_counter()
        self._ack = self._first = self._answer = self._last = 0.0
        self._itl: list[float] = []
        self.stats = TurnStats(model=model, response_id=response_id)

    def _elapsed(self) -> float:
        return (time.perf_counter() - self._t0) * 1000

    def mark_ack(self) -> None:
        """HTTP 响应头到达：连接/排队/路由已走完，推理尚未开始。"""
        self._ack = self._elapsed()

    def feed(self, kind: str, text: str = "") -> None:
        """吃一帧。kind: `reasoning` | `content`。

        ITL 记录**所有输出帧**的间隔。注意口径：云端厂商的思考内容成块下发，此时 ITL
        反映的是"到帧节奏"；本地推理（ollama）才是真正逐 token，ITL 即逐 token 延迟。
        """
        now = self._elapsed()
        if not self._first:
            self._first = now
        if kind == "reasoning":
            self.stats.reasoning_text += text
        else:
            self.stats.content_text += text
            if not self._answer:
                self._answer = now
        if self._last:
            self._itl.append(now - self._last)
        self._last = now
        self.stats.chunks += 1

    def finish(self, usage: Optional[dict] = None, finish_reason: str = "",
               stop_sequence: str = "", extra: Optional[dict] = None) -> dict:
        """结算并返回统一字段 dict。"""
        s = self.stats
        s.total_ms = _round(self._elapsed())
        s.ttack_ms = _round(self._ack)
        s.ttft_ms = _round(self._first)
        s.ttfa_ms = _round(self._answer)
        s.finish_reason = finish_reason or s.finish_reason
        s.stop_sequence = stop_sequence or s.stop_sequence
        if extra:
            s.extra.update(extra)
        _apply_usage(s, usage or {})
        _derive(s, self._itl)
        return s.to_dict()


# ─────────────────────────── 用法归一 ───────────────────────────
# 四种协议的字段名与"含不含缓存"的口径各不相同，但**归一后的形状是同一个** ——
# 所以对外只留一个入口 `usage_from(raw, protocol)`，四种解析各为私有实现。
# 拆成四个公开函数只会让调用方挑错入口，而挑错的代价是"算出一个不报错的错数"。
PROTOCOLS = ("openai", "anthropic", "gemini", "ollama")


def usage_from(raw: dict, protocol: str) -> dict:
    """某协议的原始 usage → 统一口径（键见 `_canonical`）。

    `protocol` ∈ `PROTOCOLS`；未知协议按 `openai` 处理 —— 与 provider 工厂
    "未知 type 一律回落 openai_compat"是同一容错口径。
    """
    raw = raw or {}
    if protocol == "anthropic":
        return _usage_anthropic(raw)
    if protocol == "gemini":
        return _usage_gemini(raw)
    if protocol == "ollama":
        return _usage_ollama(raw)
    return _usage_openai(raw)


def _usage_openai(raw: dict) -> dict:
    """OpenAI 兼容 usage → 统一口径（含 DeepSeek / 智谱 的缓存字段方言）。"""
    raw = raw or {}
    prompt = _int(raw.get("prompt_tokens"))
    details = raw.get("prompt_tokens_details") or {}
    cached = _first_int(details.get("cached_tokens"),
                        raw.get("prompt_cache_hit_tokens"),
                        raw.get("cache_read_input_tokens"))
    # DeepSeek 直接给 miss 数，最准；否则按"prompt 含缓存"拆分
    miss = _int(raw.get("prompt_cache_miss_tokens"))
    if miss:
        inp = miss
    elif cached and prompt >= cached:
        inp = prompt - cached
    else:
        inp = prompt
    comp = raw.get("completion_tokens_details") or {}
    out = _int(raw.get("completion_tokens"))
    return _canonical(inp, cached,
                      _first_int(*(raw.get(k) for k in _WRITE_KEYS)), out,
                      _first_int(comp.get("reasoning_tokens"), raw.get("reasoning_tokens")),
                      _int(raw.get("total_tokens")) or (prompt + out))


def _usage_anthropic(raw: dict) -> dict:
    """Anthropic usage → 统一口径。

    `input_tokens` 已排除缓存命中，**不需要**再减；缓存读/写各有独立字段。
    """
    raw = raw or {}
    inp = _int(raw.get("input_tokens"))
    cached = _int(raw.get("cache_read_input_tokens"))
    written = _int(raw.get("cache_creation_input_tokens"))
    out = _int(raw.get("output_tokens"))
    return _canonical(inp, cached, written, out, 0,
                      inp + cached + written + out)


def _usage_gemini(raw: dict) -> dict:
    """Gemini `usageMetadata` → 统一口径。

    口径陷阱（官方 token 计数页）：`promptTokenCount` **包含**缓存命中的部分
    （原文：this is still the total effective prompt size meaning this includes the
    number of tokens in the cached content），故要减掉 `cachedContentTokenCount` 才是
    非缓存输入。思考 token 单列在 `thoughtsTokenCount`。
    """
    raw = raw or {}
    prompt = _int(raw.get("promptTokenCount"))
    cached = _int(raw.get("cachedContentTokenCount"))
    inp = prompt - cached if cached and prompt >= cached else prompt
    out = _int(raw.get("candidatesTokenCount"))
    thoughts = _int(raw.get("thoughtsTokenCount"))
    total = _int(raw.get("totalTokenCount")) or (prompt + out + thoughts)
    return _canonical(inp, cached, 0, out, thoughts, total)


def _usage_ollama(obj: dict) -> dict:
    """Ollama 原始响应对象 → 统一口径（连带引擎侧分段耗时进 extra）。

    引擎侧 `prompt_eval_duration` / `eval_duration` 同时提升为 `prefill_ms` / `decode_ms`：
    输出速度用引擎自己测的解码耗时算，能排除排队与网络，比拿挂钟差值准。
    """
    obj = obj or {}
    inp = _int(obj.get("prompt_eval_count"))
    out = _int(obj.get("eval_count"))
    base = _canonical(inp, 0, 0, out, 0, inp + out)
    prefill = _ns_to_ms(obj.get("prompt_eval_duration"))
    decode = _ns_to_ms(obj.get("eval_duration"))
    base["prefill_ms"] = prefill
    base["decode_ms"] = decode
    base["extra"] = {
        "load_ms": _ns_to_ms(obj.get("load_duration")),
        "prompt_eval_ms": prefill,
        "eval_ms": decode,
        "engine_total_ms": _ns_to_ms(obj.get("total_duration")),
    }
    return base


def map_stop_reason(reason: Optional[str]) -> str:
    """Anthropic / 各家 stop_reason → OpenAI 口径；已是对应值则原样返回。"""
    if not reason:
        return ""
    return STOP_REASON_MAP.get(reason, reason)


def feed(meter: "Meter", ev: dict) -> None:
    """把内核事件里的内容帧喂给计时器（工具帧不算"输出"）。

    三个 provider 共用一份：各写一份必然漂移，而"哪种帧算输出"是统一的语义。
    """
    if "reasoning" in ev:
        meter.feed("reasoning", ev["reasoning"])
    elif "content" in ev:
        meter.feed("content", ev["content"])


def mark_finish_tool_calls(stats: dict) -> None:
    """有工具调用时把 `finish_reason` 归一为 `"tool_calls"`（服务端原值不丢）。

    统一口径里 `tool_calls` 是 OpenAI 的写法；但各家的原生值并不一致：
    OpenAI 报 `tool_calls`、Anthropic 报 `tool_use`（已映射）、**Ollama 与部分网关报 `stop`**、
    Gemini 根本没有对应值（函数调用时仍是 `STOP`）。

    必须归一的理由：调用方按 `finish_reason` 分支是常态，
    "有调用却是 stop" 会让工具**静默不执行** —— 与 `tooltext` 里那条
    "文本解析出的调用也要报 tool_calls" 是同一类问题。原值记进 `extra.finish_reason_vendor`。
    """
    if not isinstance(stats, dict) or stats.get("finish_reason") == "tool_calls":
        return
    extra = stats.setdefault("extra", {})
    if isinstance(extra, dict):
        extra.setdefault("finish_reason_vendor", stats.get("finish_reason", ""))
    stats["finish_reason"] = "tool_calls"


# ─────────────────────────── 内部 ───────────────────────────
def _canonical(inp: int, cached: int, written: int, out: int,
               reasoning: int, total: int) -> dict:
    return {
        "input_tokens": inp,
        "cache_read_tokens": cached,
        "cache_write_tokens": written,
        "output_tokens": out,
        "reasoning_tokens": reasoning,
        "total_tokens": total,
    }


def _apply_usage(s: TurnStats, usage: dict) -> None:
    """把归一后的 usage 写进统计（engine 分段耗时等打包进 extra）。"""
    if usage.get("extra"):
        s.extra.update(usage["extra"])
    for key in ("input_tokens", "cache_read_tokens", "cache_write_tokens",
                "output_tokens", "reasoning_tokens", "total_tokens"):
        if usage.get(key):
            setattr(s, key, usage[key])
    if usage.get("prefill_ms"):
        s.prefill_ms = usage["prefill_ms"]
    if usage.get("decode_ms"):
        s.decode_ms = usage["decode_ms"]


def _derive(s: TurnStats, itl: list) -> None:
    """由原始计数与计时算出派生指标（口径见模块文档）。"""
    if not s.total_tokens:
        s.total_tokens = (s.input_tokens + s.cache_read_tokens
                          + s.cache_write_tokens + s.output_tokens)
    if s.ttft_ms and s.ttfa_ms >= s.ttft_ms:
        s.thinking_ms = _round(s.ttfa_ms - s.ttft_ms)
    if s.output_tokens:
        s.ntpot_ms = _round(s.total_ms / s.output_tokens)
        if s.total_ms > s.ttft_ms and s.output_tokens > 1:
            s.tpot_ms = _round((s.total_ms - s.ttft_ms) / (s.output_tokens - 1))
        decode = s.decode_ms or (s.total_ms - s.ttft_ms)
        if decode > 0:
            s.tps = _round(s.output_tokens / decode * 1000)
        if s.total_ms > 0:
            s.tps_total = _round(s.output_tokens / s.total_ms * 1000)
    if itl:
        s.itl_p50_ms = _round(_pct(itl, 50))
        s.itl_p90_ms = _round(_pct(itl, 90))
    seen = s.input_tokens + s.cache_read_tokens
    if seen:
        s.cache_hit_rate = round(s.cache_read_tokens / seen, 4)


def _pct(values: list, q: int) -> float:
    """分位数（最近秩法）；用于 ITL 这类会被个别卡顿拉偏的序列。"""
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, -(-len(ordered) * q // 100) - 1))
    return ordered[idx]


def _int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _first_int(*values) -> int:
    """取第一个"有值"的候选（0 视为无值，避免把真值挡在后面）。"""
    for v in values:
        if v:
            got = _int(v)
            if got:
                return got
    return 0


def _ns_to_ms(nanoseconds) -> float:
    return _round(float(nanoseconds or 0) / 1e6)


def _round(value: float) -> float:
    return round(value, 1)


__all__ = [
    "Meter", "TurnStats", "STOP_REASON_MAP", "PROTOCOLS",
    "usage_from", "map_stop_reason", "feed", "mark_finish_tool_calls",
]

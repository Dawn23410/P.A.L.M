"""OpenAI 兼容协议 Provider（通用通道 + 降级通道）。

调用链（三级容错）
------------------
1. **完整 OpenAI 格式**：model / messages / stream / 采样参数 + tools + extra_body
   （思考开关等厂商特有字段走 extra_body 透传）。
2. **降级通道**：若返回「可降级」HTTP 错误（400/404/415/422），自动改用
   **基础字段子集**重试一次 —— 只保留各家必定实现的字段，消息一律降为纯文本。
3. 仍失败 → 抛 RuntimeError。

为什么用「失败驱动」而不是「厂商白名单」
----------------------------------------
各家对 OpenAI 规范的**实现子集**不同，`reasoning_effort` / `thinking` /
`enable_thinking` / `stream_options` / `tool_choice` 等字段在部分端点会直接 400，
且**同一厂商不同模型还不一样**（如 GLM-5.3 强制思考、kimi-k2.7-code 锁 temperature）。
为每家维护一份字段白名单会随版本腐烂；让**失败本身**来判定更稳：先给全量，被拒再给最小集。

不降级的错误
------------
401/403（鉴权，降了也没用）、429（限流）、5xx（服务端）—— 降级只会掩盖真实原因。

首字延迟算法设计（沿用）
------------------------
- 首字节专用短超时（FIRST_BYTE_TIMEOUT）：正常 TTFB 约 0.3–0.5s，15s≈30 倍余量。
  复用池中的「死连接」会在此时限内快速失败，触发 failover 换连接重试。
- failover：仅在「尚未向调用方产出任何 chunk」时重试一次（已产出再重试会重复生成）。
"""
from __future__ import annotations

import asyncio
import json

import httpx

from ..errors import PalmLLMError, classify_error
from ..models import Message, ModelParameters, Tool
from ..obs import log_event
from .base import (
    FIRST_BYTE_TIMEOUT,
    BaseProvider,
    FirstByteTimeout,
    chain,
    get_client,
    normalize_tool_calls,
    to_chat_message,
)
from ._capability import check_capabilities
from ._profiles import apply_rule, resolve
from ._telemetry import Meter, feed, usage_from
from ._tooltext import TextToolFilter, declared_names, filter_events, text_tool_events

_FirstByteTimeout = FirstByteTimeout

# 基础字段：OpenAI Chat Completions 规范核心，各家 OpenAI 兼容端点必定实现。
# 思考强度类字段（reasoning_effort / thinking / enable_thinking / thinking_budget）
# 一律不在此列 —— 它们要么不存在、要么枚举逐家逐模型不同。见 docs/各模型思考强度调研_v1.0.md
BASIC_KEYS = ("model", "messages", "stream", "temperature", "top_p", "max_tokens")

# 可降级状态码：多为「不认识某个字段」。鉴权/限流/服务端错误不降。
DEGRADE_STATUS = frozenset({400, 404, 415, 422})


class _HttpStatus(Exception):
    """HTTP 非 200（携带状态码，供外层判断是否值得降级）。"""

    def __init__(self, status: int, text: str):
        super().__init__(f"{status}: {text}")
        self.status = status
        self.text = text


class OpenAICompatProvider(BaseProvider):
    async def complete(self, messages, params: ModelParameters, model: str, stream: bool = True):
        self._begin(model)
        # 两级匹配：端点 → 供应商 Profile；model id → 模型子规则（未命中回落且不报错）
        profile, rule = resolve(self.cfg.base_url, model, self.cfg.type)
        # 能力矩阵前置拦截：已知不支持视觉/文档/超限 → 在此抛错，不产生任何网络往返
        cap_notes = check_capabilities(messages, profile, model, self.name, rule)
        payload = apply_rule(
            self._build_payload(messages, params, model, stream,
                                echo_reasoning=profile.needs_reasoning_echo),
            profile, rule)
        downgraded = _downgrade(payload)

        emitted = False
        degraded = False
        last: BaseException | None = None
        for attempt, body in enumerate((payload, downgraded)):
            if attempt:
                if not _degradable(last):
                    break  # 上一跳不是可降级错误 -> 不再降级
                degraded = True
                log_event("degrade.retry", level="warning", provider=self.name,
                          model=model, reason=str(last)[:120])
            # 每次尝试独立计时：降级重试意味着前一次什么都没产出
            meter = Meter(model=model)
            if cap_notes:
                meter.stats.extra.update(cap_notes)
            # 未声明 tools 时过滤器整个关闭（安全阀 1）；降级载荷已丢掉 tools，故自动关闭
            names = declared_names(body.get("tools"))
            try:
                if stream:
                    flt = TextToolFilter(names)
                    async for ev in self._stream(body, meter):
                        for out_ev in text_tool_events(flt, ev):
                            emitted = True
                            yield out_ev
                else:
                    # _oneshot 是异步生成器（非协程），只能迭代物化后交给纯函数过滤
                    events = [ev async for ev in self._oneshot(body, meter)]
                    for ev in filter_events(events, names):
                        emitted = True
                        yield ev
                return
            except (_HttpStatus, httpx.TransportError, _FirstByteTimeout) as e:
                last = e
                if emitted:
                    raise _as_error(self.name, model, e, degraded, interrupted=True)
        raise _as_error(self.name, model, last, degraded)

    # ─────────────────────────── 载荷 ───────────────────────────
    def _build_payload(self, messages, params: ModelParameters, model: str, stream: bool,
                       echo_reasoning: bool = False) -> dict:
        payload = {
            "model": model,
            "messages": [to_chat_message(m, echo_reasoning) for m in messages],
            "stream": stream,
            "temperature": params.temperature,
            "top_p": params.top_p,
            "max_tokens": params.max_tokens,
            "frequency_penalty": params.frequency_penalty,
            "presence_penalty": params.presence_penalty,
        }
        # 原生 Tool Calling：未传则不写该字段，避免对不支持工具的老端点造成兼容问题
        tools_payload = Tool.normalize(getattr(params, "tools", None))
        if tools_payload:
            payload["tools"] = tools_payload
        if getattr(params, "tool_choice", None) is not None:
            payload["tool_choice"] = params.tool_choice
        if getattr(params, "parallel_tool_calls", None) is not None:
            payload["parallel_tool_calls"] = params.parallel_tool_calls
        # 透传额外参数。关思考各厂商写法不同，且不通用：
        #   智谱原生      {"thinking": {"type": "disabled"}}
        #   OpenAI 风格   {"reasoning_effort": "none"}（本地 ollama 的 /v1 亦认这个）
        # ⚠️ {"enable_thinking": false} 对 ollama 实测无效 —— 想关思考请用上面两种之一，
        #    或直接用 ollama 原生 provider（type="ollama"），它以 think=false 一等参数下发。
        if getattr(params, "extra_body", None):
            payload.update(params.extra_body)
        return payload

    def _url(self) -> str:
        return self.cfg.base_url.rstrip("/") + "/chat/completions"

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.cfg.api_key}",
            "Content-Type": "application/json",
        }

    # ─────────────────────────── 流式 ───────────────────────────
    async def _stream(self, payload: dict, meter: Meter):
        """流式请求（含按策略的换连接 failover）；失败抛 _HttpStatus 或传输层异常。"""
        client = get_client()
        model = payload.get("model", "")
        last_err: BaseException | None = None
        for attempt in range(1, self.retry.max_attempts + 1):
            emitted = False
            usage: dict = {}
            tc_acc: dict = {}
            meta: dict = {}
            try:
                async with client.stream("POST", self._url(), headers=self._headers(),
                                         json=payload) as resp:
                    meter.mark_ack()          # 响应头已到：网络/排队已走完
                    if resp.status_code != 200:
                        txt = await resp.aread()
                        raise _HttpStatus(resp.status_code,
                                          txt.decode("utf-8", "ignore")[:500])
                    aiter = resp.aiter_lines()          # ★ 按行读取，非逐字节
                    # ★ 首字节专用短超时：死连接在此快速失败（先于全局 read 超时）
                    try:
                        first = await asyncio.wait_for(aiter.__anext__(),
                                                       timeout=FIRST_BYTE_TIMEOUT)
                    except asyncio.TimeoutError as e:
                        raise _FirstByteTimeout() from e
                    async for line in chain(first, aiter):
                        for ev in _emit_stream_event(line, tc_acc, usage, meta):
                            feed(meter, ev)
                            emitted = True
                            yield ev
                if tc_acc:
                    yield {"tool_calls": [tc_acc[k] for k in sorted(tc_acc)]}
                stats = meter.finish(usage_from(usage, "openai"),
                                     meta.get("finish_reason", ""),
                                     extra=_meta_extra(meta))
                if tc_acc:
                    # 部分兼容网关在工具调用时仍报 "stop" → 归一，否则调用方会漏执行
                    mark_finish_tool_calls(stats)
                yield {"done": True, "usage": usage, "stats": stats}
                return
            except (httpx.TransportError, _FirstByteTimeout) as e:
                last_err = e
                if emitted:
                    raise            # 已产出内容，重试会造成重复生成
                if attempt >= self.retry.max_attempts:
                    break
                await self._backoff(attempt, e, model)   # ★ 换连接重试（按策略退避）
        raise last_err

    async def _oneshot(self, payload: dict, meter: Meter):
        """非流式请求（含按策略的换连接 failover）；失败抛 _HttpStatus 或传输层异常。

        与 `_stream` 一致地做连接 failover：单次 POST 失败（死连接）按 `RetryPolicy`
        重试，已产出内容才跳过（非流式整包返回，无中途产出，故只需重试 POST 本身）。
        """
        model = payload.get("model", "")
        last_err: BaseException | None = None
        for attempt in range(1, self.retry.max_attempts + 1):
            try:
                r = await get_client().post(self._url(), headers=self._headers(), json=payload)
                meter.mark_ack()
                if r.status_code != 200:
                    raise _HttpStatus(r.status_code, r.text[:500])
                obj = r.json()
                msg = obj["choices"][0]["message"]
                # 思维链字段名各家不一：DeepSeek/智谱/OpenAI 用 reasoning_content，
                # 本地 ollama 的 /v1 用 reasoning —— 只认其一会让思考内容被静默丢弃
                # （max_tokens 偏小时思考还会吃光额度、正文返空）。
                reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
                if reasoning:
                    meter.feed("reasoning", reasoning)
                    yield {"reasoning": reasoning}
                content = msg.get("content") or ""
                if content:
                    meter.feed("content", content)
                    yield {"content": content}
                tool_calls = msg.get("tool_calls")
                if tool_calls:
                    # 与流式路径共用同一份归一：分片拼装的与非流式整包下发的必须是同一形状
                    yield {"tool_calls": normalize_tool_calls(tool_calls)}
                usage = obj.get("usage", {})
                stats = meter.finish(usage_from(usage, "openai"), _finish_reason(obj),
                                     extra=_meta_extra({"response_id": obj.get("id"),
                                                        "model": obj.get("model")}))
                if tool_calls:
                    mark_finish_tool_calls(stats)
                yield {"done": True, "usage": usage, "stats": stats}
                return
            except (httpx.TransportError, _FirstByteTimeout) as e:
                last_err = e
                if attempt >= self.retry.max_attempts:
                    break
                await self._backoff(attempt, e, model)   # ★ 换连接重试（按策略退避）
        raise last_err

    @staticmethod
    def _conv(m: Message, echo_reasoning: bool = False) -> dict:
        """保留旧入口：实现已上提至 `base.to_chat_message`，与 ollama 原生实现共用一份。"""
        return to_chat_message(m, echo_reasoning)


# ─────────────────────────── 模块级纯函数 ───────────────────────────
def _emit_stream_event(line: str, tc_acc: dict, usage: dict, meta: dict):
    """解析一行 SSE 为内核事件列表（纯函数，无 IO）。

    `tc_acc` 为调用方持有的工具调用累加器（按 index 聚合分片），跨行保持状态；
    `usage` / `meta` 原地更新 —— 必须在取 choices 之前读，因为
    stream_options.include_usage 的收尾帧只有 usage、没有 choices。
    `meta` 收拢响应元信息（响应 id / 服务端回传模型名 / finish_reason），供回传拆分器用。
    """
    if not line or not line.startswith("data:"):
        return []
    data = line[5:].strip()
    if data == "[DONE]":
        return []
    try:
        obj = json.loads(data)
    except ValueError:
        return []
    if obj.get("usage"):
        usage.update(obj["usage"])
    if obj.get("id"):
        meta["response_id"] = obj["id"]
    if obj.get("model"):
        meta["model"] = obj["model"]
    try:
        choice = obj["choices"][0]
    except (KeyError, IndexError, TypeError):
        # stream_options.include_usage 的收尾帧没有 choices，不是错误
        return []
    if choice.get("finish_reason"):
        meta["finish_reason"] = choice["finish_reason"]
    delta = choice.get("delta") or {}
    events = []
    reasoning = delta.get("reasoning_content") or delta.get("reasoning")
    if reasoning:
        events.append({"reasoning": reasoning})
    if delta.get("content"):
        events.append({"content": delta["content"]})
    for frag in (delta.get("tool_calls") or []):
        events.extend(_accumulate_tool_frag(frag, tc_acc))
    return events


def _accumulate_tool_frag(frag: dict, tc_acc: dict) -> list:
    """聚合一个工具调用分片，返回需要下发的"开始调用"事件。

    OpenAI 把一次工具调用拆成多个分片下发，必须按 index 累加；拿到工具名即下发，
    供前端实时显示"正在调用 X"（等参数拼完再显示会有明显空窗）。
    """
    idx = frag.get("index", 0)
    item = tc_acc.setdefault(idx, {"index": idx, "id": None, "type": "function",
                                   "function": {"name": "", "arguments": ""}})
    if frag.get("id"):
        item["id"] = frag["id"]
    if frag.get("type"):
        item["type"] = frag["type"]
    fn = frag.get("function") or {}
    events = []
    if fn.get("name"):
        item["function"]["name"] += fn["name"]
        events.append({"tool_call_delta": {"index": idx, "id": item["id"],
                                          "name": item["function"]["name"]}})
    if fn.get("arguments"):
        item["function"]["arguments"] += fn["arguments"]
    return events


def _meta_extra(meta: dict) -> dict | None:
    """响应元信息 → 塞进 stats.extra，便于按响应 id 追溯线上问题。"""
    out = {k: meta[k] for k in ("response_id", "model") if meta.get(k)}
    return out or None


def _finish_reason(obj: dict) -> str:
    """取非流式响应的结束原因（choices 可能是空数组）。"""
    try:
        return obj["choices"][0].get("finish_reason") or ""
    except (KeyError, IndexError, TypeError):
        return ""


def _downgrade(payload: dict) -> dict:
    """降级为「各供应商均完全相同」的基础字段子集。"""
    out = {k: payload[k] for k in BASIC_KEYS if k in payload}
    out["messages"] = _plain_messages(payload.get("messages") or [])
    return out


def _plain_messages(messages: list) -> list:
    """消息降级：多模态 blocks → 纯文本；工具轮次整体丢弃。

    丢弃带 tool_calls 的 assistant 与 role="tool" 消息：降级通道不保留工具轮次，
    否则会因缺少 tool 响应而被再次判为非法请求。
    """
    out = []
    for m in messages or []:
        if m.get("role") == "tool" or m.get("tool_calls"):
            continue
        content = m.get("content")
        if isinstance(content, list):
            content = "".join(b.get("text", "") for b in content
                              if isinstance(b, dict) and b.get("type") == "text")
        out.append({"role": m.get("role"), "content": content or ""})
    return out


def _degradable(exc: BaseException | None) -> bool:
    """是否值得降级重试：仅「厂商不认识某字段」类错误。"""
    return isinstance(exc, _HttpStatus) and exc.status in DEGRADE_STATUS


def _as_error(name: str, model: str, exc: BaseException | None, degraded: bool,
              interrupted: bool = False) -> PalmLLMError:
    """内部异常 → 类型化错误。文案与历史保持一致，便于既有调用方对号入座。"""
    suffix = "（已降级为基础字段重试）" if degraded else ""
    if isinstance(exc, _HttpStatus):
        return classify_error(f"[{name}] {exc.status}: {exc.text}{suffix}",
                              status=exc.status, provider=name, model=model,
                              text=exc.text)
    if exc is None:
        return classify_error(f"[{name}] 请求失败{suffix}",
                              exc=None, provider=name, model=model)
    return classify_error(
        f"[{name}] 连接失败（已自动重试）：{type(exc).__name__}: "
        f"{exc or '未知连接错误'}{suffix}",
        exc=exc, provider=name, model=model, interrupted=interrupted)

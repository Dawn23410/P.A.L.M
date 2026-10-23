"""Ollama 原生协议 Provider（`/api/chat`）。

为什么单独实现，而不是继续走 openai_compat 打 ollama 的 `/v1` 兼容层
--------------------------------------------------------------------------
实测依据（ollama 0.34.1 + spark-x2.5:1.7b，2026-09-22）：

1. **思维链字段错位**：`/v1` 把思考链放在 `delta.reasoning`，而绝大多数 OpenAI 兼容
   实现只认 `reasoning_content` → 思考内容被静默丢弃；更糟的是 `max_tokens` 偏小时
   思考会把额度吃光，**正文返回空字符串**（表现为"模型什么都不输出"）。
2. **关思考参数非标准**：`/v1` 上须用 `reasoning_effort:"none"`；原生协议里 `think`
   是一等参数，语义明确、跨版本稳定。
3. 原生协议额外直接给出 token 计数与**分段耗时**（加载 / 预填充 / 解码），
   可把首字延迟拆开做归因；`/v1` 则连 usage 都不返回。

本实现把厂商差异收敛到 `_resolve_think`：调用方写 `think` / `enable_thinking` /
`reasoning_effort` / `thinking` 任一种，都翻译成原生 `think`，无需改调用方代码。

⚠️ 本地服务不需要 API Key，故 `_check_key` 放行空 key。

单生成器约定
------------
`complete` 是**唯一**的异步生成器，内部不再嵌套（非流式走返回 list 的 `_fetch_once`）。

理由（实测）：调用方 `break` 早退时，被中断的外层生成器由 GC 终结器关闭；
若内层还套着一个生成器，内层的 httpx stream 会在 loop 收尾被重复 aclose，
报 `RuntimeError: aclose(): asynchronous generator is already running`。
单生成器时该路径不存在。基准脚本里这个噪声实测可复现、加上单生成器后消失。

⚠️ 因此文本工具调用降级（`tooltext`）在本文件里走**纯函数就地过滤**
（`text_tool_events`），不包装成生成器层 —— 否则等于把上面那个已修复的问题请回来。

（曾怀疑嵌套会让每 token 多跨一层生成器帧、抬高 ~2ms 首字，**后经对照否证**：
单生成器版与嵌套版各 10 轮中位都在 54–58ms 区间，差异属批间漂移，不构成理由。）
"""
from __future__ import annotations

import json
import time
from typing import Any, Iterator, Optional

import httpx

from ..errors import PalmLLMError, error_for_status, error_for_transport
from ..models import Message, ModelParameters, Tool
from .base import (
    BaseProvider,
    FirstByteTimeout,
    get_client,
    iter_sse_lines,
    normalize_tool_calls,
    to_chat_message,
)
from .capability import check_capabilities
from .profiles import resolve_provider
from .telemetry import Meter, feed, mark_finish_tool_calls, usage_from_ollama
from .tooltext import TextToolFilter, declared_names, filter_events, text_tool_events

DEFAULT_BASE_URL = "http://127.0.0.1:11434"
# 导出名带前缀：避免与云端 provider 的 base_url 语义混淆
OLLAMA_DEFAULT_BASE_URL = DEFAULT_BASE_URL

# 调用方可能用这些键表达"思考开关"，统一消费后翻译为原生 `think`
_THINK_KEYS = ("think", "enable_thinking", "reasoning_effort", "thinking")


class OllamaProvider(BaseProvider):
    """Ollama 原生协议适配（流式 / 非流式均支持）。

    `cfg.base_url` 填**原生根地址**（`http://127.0.0.1:11434`），不要带 `/v1`；
    为兼容旧配置，若带了 `/v1` 会被自动剥掉。
    """

    # ─────────────────────────── 端点 ───────────────────────────
    def _root(self) -> str:
        """原生根地址：默认值兜底，并剥掉误写的 `/v1` 后缀。"""
        base = (self.cfg.base_url or DEFAULT_BASE_URL).strip().rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3].rstrip("/")
        return base or DEFAULT_BASE_URL

    def _chat_url(self) -> str:
        return self._root() + "/api/chat"

    async def prewarm(self) -> float:
        """预热：GET `/api/tags` 预建连并入池（父类打的是 OpenAI 风格的 `/models`）。

        ⚠️ 只预热**连接**，不加载模型 —— 实测 `prewarm` 后首次真正 `complete`
        仍会付出模型加载代价（`usage["load_ms"]`，1.7B 约 2.0s）。想连模型一起热，
        需在应用启动时主动跑一次 1-token 的 `complete`（是否值得由调用方决定，
        因为本地模型加载占显存、可能并非时刻需要）。
        """
        client = get_client()
        t0 = time.perf_counter()
        try:
            await client.get(self._root() + "/api/tags", timeout=5.0)
        except Exception:
            pass  # 预热尽力而为
        return (time.perf_counter() - t0) * 1000

    async def list_models(self) -> list[str]:
        """已安装模型名列表；失败返回空列表（供 UI / CLI 展示本地可选模型）。"""
        try:
            r = await get_client().get(self._root() + "/api/tags", timeout=8.0)
            if r.status_code != 200:
                return []
            return [m.get("name", "") for m in (r.json().get("models") or []) if m.get("name")]
        except Exception:
            return []

    def _check_key(self) -> None:
        """本地服务无需凭证，故意跳过父类的 key 非空校验。"""

    # ─────────────────────────── 主入口 ───────────────────────────
    async def complete(
        self, messages: list[Message], params: ModelParameters, model: str, stream: bool = True
    ):
        """产出增量字典（reasoning / content / tool_call_delta / tool_calls / done+usage+stats）。

        不往内层再套异步生成器，理由见模块文档「单生成器」一节。
        """
        self._begin(model)
        # 能力矩阵前置拦截。ollama 档位走 generic（模型名不固定），故只做记账不拦——
        # 本机拉的是 llava 还是纯文本模型，内核无从得知，硬拦会打死合法用法。
        cap_notes = check_capabilities(
            messages, resolve_provider(self.cfg.base_url, self.cfg.type), model, self.name)

        def _meter() -> Meter:
            m = Meter(model=model)
            if cap_notes:
                m.stats.extra.update(cap_notes)
            return m

        payload = self._build_payload(messages, params, model, stream)
        # 未声明 tools 时过滤器整个关闭（安全阀 1），故此处无需再判断
        names = declared_names(payload.get("tools"))
        if not stream:
            events = await self._fetch_once(payload, _meter())
            for ev in filter_events(events, names):
                yield ev
            return
        flt = TextToolFilter(names)
        # 流式：仅在未产出任何 chunk 时按策略换连接重试（已产出再重试会重复生成）
        last_err: Exception | None = None
        for attempt in range(1, self.retry.max_attempts + 1):
            emitted = False
            native = False           # 本响应是否出现原生 tool_calls（决定 finish_reason）
            meter = _meter()
            try:
                async with get_client().stream("POST", self._chat_url(), json=payload) as resp:
                    meter.mark_ack()
                    if resp.status_code != 200:
                        raise _http_fail(self.name, resp.status_code, await resp.aread())
                    async for line in iter_sse_lines(resp):
                        obj = _parse_line(line)
                        if obj is None:
                            continue
                        for ev in self._emit(obj):
                            if "tool_calls" in ev:
                                native = True
                            feed(meter, ev)
                            for out_ev in text_tool_events(flt, ev):
                                emitted = True
                                yield out_ev
                        if obj.get("done"):
                            # 收尾帧也要过过滤器：否则文本降级抽出的调用与被扣的尾巴全丢
                            tail = {"done": True, "usage": _usage(obj),
                                    "stats": _tool_stats(obj, meter, native)}
                            for out_ev in text_tool_events(flt, tail):
                                emitted = True
                                yield out_ev
                            return
                # 服务端没给 done 就断流：已产出内容仍有效，补一个收尾帧（同样过过滤器）
                tail = {"done": True, "usage": {}, "stats": meter.finish()}
                for out_ev in text_tool_events(flt, tail):
                    emitted = True
                    yield out_ev
                return
            except (httpx.TransportError, FirstByteTimeout) as e:
                last_err = e
                if emitted:
                    raise            # 已产出内容，重试会重复生成
                if attempt >= self.retry.max_attempts:
                    break
                await self._backoff(attempt, e, model)   # ★ 换连接重试（按策略退避）
        raise _connect_fail(self.name, last_err, self.retry.max_attempts)

    async def _fetch_once(self, payload: dict, meter: Meter) -> list[dict]:
        """非流式：一次请求，返回完整事件列表（含收尾帧）。

        返回 list 而非异步生成器 —— 避免在 `complete` 内多嵌一层。
        """
        r = await get_client().post(self._chat_url(), json=payload)
        meter.mark_ack()
        if r.status_code != 200:
            raise _http_fail(self.name, r.status_code, r.content)
        obj = r.json()
        events = list(self._emit(obj))
        # 必须先喂计时器再结算：反了的话 chunks / 全文累加全是 0（结算时刻还没有帧）
        for ev in events:
            feed(meter, ev)
        has_calls = any("tool_calls" in ev for ev in events)
        events.append({"done": True, "usage": _usage(obj),
                       "stats": _tool_stats(obj, meter, has_calls)})
        return events

    # ─────────────────────────── 载荷 ───────────────────────────
    def _build_payload(self, messages, params: ModelParameters, model: str, stream: bool) -> dict:
        payload: dict = {
            "model": model,
            "messages": [_native_message(m) for m in messages],
            "stream": bool(stream),
        }
        extra = dict(getattr(params, "extra_body", None) or {})
        think = _resolve_think(extra)
        if think is not None:
            # 仅在显式给定时下发：None = 沿用模型模板默认（如 spark 默认开思考）
            payload["think"] = think
        # OpenAI 风格参数名 → ollama options（max_tokens 在原生协议里叫 num_predict）
        payload["options"] = {
            "temperature": params.temperature,
            "top_p": params.top_p,
            "num_predict": params.max_tokens,
            "frequency_penalty": params.frequency_penalty,
            "presence_penalty": params.presence_penalty,
        }
        tools = Tool.normalize(getattr(params, "tools", None))
        if tools:
            payload["tools"] = tools
        # 刻意不下发 `tool_choice` 与 `parallel_tool_calls`：原生 `/api/chat` 的字段全集是
        # model/messages/tools/think/format/options/stream/keep_alive —— 没有这两个。
        # 官方博客把 "Tool choice: force a model to use a tool" 列在 Future improvements，
        # 即尚未支持；无据下发只会给严格校验的第三方兼容服务埋雷。
        # 其余 extra_body 键（keep_alive / format / stop 等）顶层透传；
        # 已消费的思考控制键不再外泄，避免服务端收到不认识的字段。
        for k, v in extra.items():
            if k not in _THINK_KEYS:
                payload[k] = v
        return payload

    # ─────────────────────────── 事件映射 ───────────────────────────
    def _emit(self, obj: dict) -> Iterator[dict]:
        """把原生响应对象映射为内核事件。

        原生协议一次给完整 tool_calls（不像 OpenAI 那样分片），故这里直接
        `tool_call_delta` + 完整 `tool_calls` 一起给。
        """
        if obj.get("error"):
            # 服务端在流中回传的错误对象（如"模型不存在"）：不可重试，原文透出
            raise PalmLLMError(f"[{self.name}] 服务端错误：{obj['error']}",
                               provider=self.name)
        msg = obj.get("message") or {}
        reasoning = msg.get("thinking")        # ★ 原生字段是 thinking（/v1 才叫 reasoning）
        if reasoning:
            yield {"reasoning": reasoning}
        content = msg.get("content")
        if content:
            yield {"content": content}
        yield from _emit_tool_calls(msg)


def _emit_tool_calls(msg: dict) -> Iterator[dict]:
    """一条原生消息里的完整工具调用 → 内核事件（先 delta 后整包）。"""
    tool_calls = normalize_tool_calls(msg.get("tool_calls"))
    if not tool_calls:
        return
    for tc in tool_calls:
        yield {"tool_call_delta": {"index": tc["index"], "id": tc["id"],
                                   "name": tc["function"]["name"]}}
    yield {"tool_calls": tool_calls}


# 旧私有入口保留为薄别名：实现已上提到 `base.normalize_tool_calls`（三个 provider 共用一份）。
# 归一形状必须与流式分片拼装一致，两份实现必然漂移 —— 故只留别名，不再各写一份。
_normalize_tool_calls = normalize_tool_calls


def _parse_line(line: str) -> Optional[dict]:
    """解析一行 NDJSON；空行/非 JSON 行返回 None（流中可能夹心跳或残行）。"""
    text = (line or "").strip()
    if not text:
        return None
    try:
        obj = json.loads(text)
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def _native_message(m: Message) -> dict:
    """内核 Message → ollama 原生消息。

    与 OpenAI 形态有两处**硬差异**（官方 api.md 的消息对象字段表），照 OpenAI 形态发过去
    会静默失效：
      - 工具结果用 `tool_name`，**没有** `tool_call_id` —— 发 `name` 的话 ollama 收不到
        工具名，多轮工具闭环直接断掉；
      - assistant 的 `tool_calls[].function.arguments` 必须是**对象**，不是 JSON 字符串。
    """
    out = to_chat_message(m)
    if out.get("role") == "tool":
        out.pop("tool_call_id", None)
        name = out.pop("name", None)
        if name:
            out["tool_name"] = name
    elif out.get("tool_calls"):
        out["tool_calls"] = [_native_call(tc) for tc in out["tool_calls"]]
    return out


def _native_call(tc: dict) -> dict:
    """一个工具调用 → 原生形态（`arguments` 由 JSON 字符串还原成对象）。"""
    fn = tc.get("function") or {}
    args = fn.get("arguments")
    if isinstance(args, str):
        try:
            args = json.loads(args or "{}")
        except ValueError:
            args = {}
    return {"type": tc.get("type") or "function",
            "function": {"name": fn.get("name") or "", "arguments": args or {}}}


def _resolve_think(extra: dict) -> Optional[Any]:
    """把各家思考开关写法翻译为原生 `think`；未表达则返回 None（不干预）。

    支持：`think`（直传，可为 true/false/"low"/"medium"/"high"）、
    `reasoning_effort:"none"`、`enable_thinking:false`、`thinking:false`
    或 `thinking:{"type":"disabled"}`（智谱原生写法）。
    """
    if "think" in extra and extra["think"] is not None:
        return extra["think"]
    if extra.get("reasoning_effort") == "none":
        return False
    if extra.get("enable_thinking") is False:
        return False
    setting = extra.get("thinking")
    if setting is False:
        return False
    if isinstance(setting, dict) and setting.get("type") == "disabled":
        return False
    return None


def _stats(obj: dict, meter: Meter) -> dict:
    """回传拆分器结算：原生 done 帧 → 统一字段（连带引擎侧分段耗时进 extra）。"""
    return meter.finish(usage_from_ollama(obj), obj.get("done_reason") or "")


def _tool_stats(obj: dict, meter: Meter, has_calls: bool) -> dict:
    """收尾统计；出现工具调用时把 finish_reason 归一为 `tool_calls`。

    ⚠️ ollama 原生在工具调用时 `done_reason` 仍是 `stop`（实测 0.34.x）。不归一的话，
    按 `finish_reason` 分支的调用方会**静默不执行**工具 —— 与 tooltext 里那条
    "文本解析出的调用也要报 tool_calls" 是同一类问题。原值留在 finish_reason_vendor。
    """
    stats = _stats(obj, meter)
    if has_calls:
        mark_finish_tool_calls(stats)
    return stats


def _http_fail(name: str, status: int, raw: bytes) -> PalmLLMError:
    """HTTP 非 200 → 按状态分类的类型化错误（响应体截断，避免把整页塞进日志）。"""
    text = raw.decode("utf-8", "ignore")[:500]
    return error_for_status(status, f"[{name}] {status}: {text}",
                            provider=name, text=text)


def _connect_fail(name: str, err: BaseException | None,
                  attempts: int = 2) -> PalmLLMError:
    """连接类失败 → 可重试的传输错误（保留原始异常类型名，便于对号入座）。"""
    return error_for_transport(
        err,
        f"[{name}] 连接失败（已自动重试 {max(0, attempts - 1)} 次）："
        f"{type(err).__name__}: {err or '未知连接错误'}",
        provider=name)


def _usage(obj: dict) -> dict:
    """原生计数字段 → OpenAI 风格 usage，并附 ollama 专有的分段耗时。

    额外键以 `_ms` 结尾（OpenAI 风格消费方应忽略）：用于把一次请求拆成
    模型加载 / 提示预填充 / 解码 三段做延迟归因。原生耗时单位为纳秒。
    """
    prompt = obj.get("prompt_eval_count") or 0
    completion = obj.get("eval_count") or 0
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
        "load_ms": _ns_to_ms(obj.get("load_duration")),
        "prompt_eval_ms": _ns_to_ms(obj.get("prompt_eval_duration")),
        "eval_ms": _ns_to_ms(obj.get("eval_duration")),
        "total_ms": _ns_to_ms(obj.get("total_duration")),
    }


def _ns_to_ms(nanoseconds) -> float:
    """纳秒 → 毫秒（保留 0.1ms）；缺省视为 0。"""
    return round(float(nanoseconds or 0) / 1e6, 1)


__all__ = ["OllamaProvider", "DEFAULT_BASE_URL", "OLLAMA_DEFAULT_BASE_URL"]

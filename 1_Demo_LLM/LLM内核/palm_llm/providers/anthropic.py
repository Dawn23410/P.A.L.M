"""Anthropic 原生协议 Provider（`POST /v1/messages`）。

为什么单独实现，而不是继续走 openai_compat 打 Anthropic 兼容网关
----------------------------------------------------------------
1. **结构级差异，不是字段名差异**：`system` 必须**外提**为顶层参数（messages 里没有
   system 角色）；`max_tokens` 是**必填**项；`tools` 用 `input_schema` 而非 `parameters`；
   `tool_choice` 没有 `required` 而是 `any`。这些靠"字段映射表"翻不出来。
2. **流式事件的粒度不同**：原生是**块级生命周期**（`content_block_start/delta/stop`
   + `message_start/message_delta/message_stop`），不是"每帧一个 choices[0].delta"。
   思考块还带 `signature_delta`（思考块签名），OpenAI 兼容层拿不到。
3. **缓存 token 是原生字段**：`cache_read_input_tokens` / `cache_creation_input_tokens`，
   且 `input_tokens` **不含**缓存命中 —— 走兼容网关通常是聚合后的假数。
4. **思考档位写法不同**：原生用 `output_config.effort`，兼容网关多是 `reasoning_effort`。

本文件只负责传输与思考配置；内核 Message ↔ 原生线格式的双向转换在 `anthropic_wire.py`
（那是另一件事，混在一起会让"传输出错"和"翻译出错"难以区分）。

思考配置的两条独立通道
----------------------
- 开关 → 顶层 `thinking`（`{"type":"adaptive"}` / `{"type":"enabled","budget_tokens":N}`）
- 档位 → `output_config.effort`（low/medium/high/xhigh/max）
规则级常量（哪代模型必须 adaptive、哪代必须 enabled）仍由 `profiles` 二级匹配提供。

⚠️ 思考开启时不下发 `temperature` / `top_p`：原生在思考模式下只接受默认 temperature=1，
且与 `top_p` 互斥，下发了就是必然 400。服务端默认值即 1，故直接省略。
"""
from __future__ import annotations

from typing import Any, Optional

from ..models import Message, ModelParameters
from .anthropic_wire import (
    content_events,
    error_text,
    finish_events,
    native_tool_choice,
    native_tools,
    new_state,
    on_event,
    parse_sse,
    to_native_messages,
)
from .base import (
    BaseProvider,
    get_client,
    iter_sse_lines,
)
from .capability import check_capabilities
from .profiles import THINK_KEYS, apply_rule, resolve_model, resolve_provider
from .telemetry import Meter, feed

NATIVE_VERSION = "2023-06-01"

# 官方档位（output_config.effort）；none/minimal 用别名收敛
_EFFORTS = ("low", "medium", "high", "xhigh", "max")
_EFFORT_ALIAS = {"none": None, "minimal": "low"}

# 已被本 provider 消费、不得再原样外泄的 extra_body 键
_CONSUMED_EXTRA = frozenset({
    "stop", "stop_sequences", "thinking", "enable_thinking", "think",
    "reasoning_effort", "output_config",
})

# enabled 模式必须带 budget_tokens（官方范围 1024–32768）；取偏小值避免吃掉正文额度
_DEFAULT_THINK_BUDGET = 8192


class _AnthropicStatus(Exception):
    """HTTP 非 200（携带状态码与已解包的错误文本）。"""

    def __init__(self, status: int, text: str):
        super().__init__(f"{status}: {text}")
        self.status = status
        self.text = text


class AnthropicProvider(BaseProvider):
    """Anthropic Messages API 原生适配（流式 / 非流式）。"""

    _status_cls = _AnthropicStatus

    # ─────────────────────────── 端点与请求头 ───────────────────────────
    def _url(self) -> str:
        """容忍把 `/v1` 或 `/v1/messages` 写进 base_url 的三种常见误配。"""
        base = (self.cfg.base_url or "").strip().rstrip("/")
        for suffix in ("/v1/messages", "/messages", "/v1"):
            if base.endswith(suffix):
                base = base[: -len(suffix)].rstrip("/")
                break
        return base + "/v1/messages"

    def _headers(self) -> dict:
        # 原生协议用 x-api-key，不是 Authorization: Bearer
        version = (self.cfg.extra or {}).get("anthropic_version") or NATIVE_VERSION
        return {
            "x-api-key": self.cfg.api_key,
            "anthropic-version": version,
            "content-type": "application/json",
        }

    # ─────────────────────────── 主入口 ───────────────────────────
    async def complete(
        self, messages: list[Message], params: ModelParameters, model: str, stream: bool = True
    ):
        """产出增量字典（reasoning / content / tool_call_delta / tool_calls / done+usage+stats）。"""
        self._begin(model)
        notes: dict = {}       # 组装期记账（如工具选择被降级）→ 并入 stats.extra，不静默
        payload = await self._build_payload(messages, params, model, stream, notes)
        async for ev in self._run_with_retry(model, stream, payload, notes):
            yield ev

    # ─────────────────────────── 载荷 ───────────────────────────
    async def _build_payload(self, messages, params: ModelParameters, model: str,
                             stream: bool, notes: Optional[dict] = None) -> dict:
        profile, rule = resolve_model(
            resolve_provider(self.cfg.base_url, self.cfg.type), model)
        # 能力矩阵前置拦截：已知不支持视觉/文档/超限 → 在此抛错，不产生任何网络往返
        notes = notes if notes is not None else {}
        notes.update(check_capabilities(messages, profile, model, self.name, rule))
        extra = dict(getattr(params, "extra_body", None) or {})
        # 工具先于消息解析：思考块是否回传取决于本次是否带 tools（官方：带思考用工具时
        # 才严格必需；否则省略更省 —— 历史思考在 keep-all 模型上会持续计入输入 token）
        tools = native_tools(getattr(params, "tools", None))
        system, native_msgs = await to_native_messages(messages, self.image_to_b64,
                                                      echo_reasoning=bool(tools))
        body: dict[str, Any] = {
            # max_tokens 是原生协议的必填项，漏了直接 400（与 OpenAI 不同）
            "model": model,
            "messages": native_msgs,
            "max_tokens": params.max_tokens,
            "stream": bool(stream),
        }
        if system:
            body["system"] = system
        thinking = _thinking_setup(profile, rule, extra)
        if thinking:
            body["thinking"] = thinking
            _fill_budget(body["thinking"], params.max_tokens)
            # 思考模式下 temperature 只接受 1、且与 top_p 互斥 → 一律省略（见模块文档）
        else:
            body["temperature"] = params.temperature
            body["top_p"] = params.top_p
        stop = extra.get("stop_sequences") or extra.get("stop")
        if stop:
            body["stop_sequences"] = stop if isinstance(stop, list) else [stop]
        if tools:
            body["tools"] = tools
            choice = _tool_choice_setup(params, thinking, rule, notes)
            if choice:
                body["tool_choice"] = choice
        for k, v in extra.items():
            if k not in _CONSUMED_EXTRA:
                body[k] = v
        return body

    # ─────────────────────────── 流式 ───────────────────────────
    async def _stream(self, payload: dict, meter: Meter, model: str,
                      notes: Optional[dict] = None):
        """块级 SSE → 内核事件；失败抛 _AnthropicStatus 或传输层异常。"""
        st = new_state()
        st["notes"] = notes or {}
        async for obj in self._iter_events(payload, meter):
            for ev in on_event(st, obj, self.name):
                feed(meter, ev)
                yield ev
            if obj.get("type") == "message_stop":
                for ev in finish_events(st, meter):
                    yield ev
                return
        # 服务端没给 message_stop 就断流：已产出的内容仍然有效，补一个收尾帧
        for ev in finish_events(st, meter):
            yield ev

    async def _iter_events(self, payload: dict, meter: Meter):
        """发请求并逐条产出已解析的 SSE 事件对象。"""
        client = get_client()
        async with client.stream("POST", self._url(), headers=self._headers(),
                                 json=payload) as resp:
            meter.mark_ack()          # 响应头已到：网络/排队已走完
            if resp.status_code != 200:
                raise _AnthropicStatus(resp.status_code, error_text(await resp.aread()))
            async for line in iter_sse_lines(resp):
                obj = parse_sse(line)
                if obj is not None:
                    yield obj

    async def _fetch_once(self, payload: dict, meter: Meter, model: str,
                          notes: Optional[dict] = None) -> list[dict]:
        """非流式：一次请求返回完整事件列表（返回 list 以避免多嵌一层生成器）。"""
        r = await get_client().post(self._url(), headers=self._headers(), json=payload)
        meter.mark_ack()
        if r.status_code != 200:
            raise _AnthropicStatus(r.status_code, error_text(r.content))
        obj = r.json()
        st = new_state()
        st["notes"] = notes or {}
        st["usage"] = obj.get("usage") or {}
        st["stop"] = obj.get("stop_reason") or ""
        st["stop_seq"] = obj.get("stop_sequence") or ""
        st["model"] = obj.get("model") or ""
        st["id"] = obj.get("id") or ""
        events = content_events(obj.get("content") or [], st)
        # 必须先喂计时器再结算：反了的话 chunks / 全文累加全是 0（结算时刻还没有帧）
        for ev in events:
            feed(meter, ev)
        return events + finish_events(st, meter)


# ─────────────────────────── 工具选择 ───────────────────────────
def _tool_choice_setup(params, thinking: Optional[dict], rule, notes: dict) -> Optional[dict]:
    """工具选择 → 原生形态；命中官方"互斥"约束时降级为 `auto` 并如实记账。

    官方口径（扩展思考页）：
      - `any` / `tool`（强制调用）与**手工思考**（`type:"enabled"`）不兼容，`adaptive` 才行；
      - `Fable 5.1` / `Mythos 5.1` 上强制调用**任何情况**都返回 400。

    降级而非抛错：与既有"GLM-5.3 关不掉思考就降为最低档"的处理口径一致。
    但**不静默** —— 降级原因写进 `stats.extra.tool_choice_downgraded`，
    否则调用方会以为"必须调用"已经生效。
    """
    choice = native_tool_choice(getattr(params, "tool_choice", None),
                                getattr(params, "parallel_tool_calls", None))
    if choice is None or choice.get("type") == "auto":
        return choice
    if rule is not None and getattr(rule, "reject_forced_tool", False):
        why = "该模型不接受强制工具选择"
    elif (thinking or {}).get("type") == "enabled":
        why = "手工思考与强制工具选择互斥"
    else:
        return choice
    notes["tool_choice_downgraded"] = f"{why}，已降级为 auto"
    soft = {"type": "auto"}
    if choice.get("disable_parallel_tool_use"):
        soft["disable_parallel_tool_use"] = True
    return soft


# ─────────────────────────── 思考配置 ───────────────────────────
def _thinking_setup(profile, rule, extra: dict) -> Optional[dict]:
    """思考配置 → 可并入 payload 的 `thinking`；不需要下发时返回 None。

    规则锁死的常量（如 Opus4.7+ 必须 adaptive）优先于调用方意图 —— 那是硬性约束，
    不是偏好。档位另走 `output_config.effort`，见 `_effort_setup`。

    ⚠️ 调用方**没表达**开关时不下发 `thinking`：一旦下发，本 provider 就要连带省略
    temperature/top_p（原生在思考模式下拒收这两项），等于静默改了采样行为。
    """
    resolved = apply_rule(dict(extra or {}), profile, rule)
    forced = (rule.fixed_params.get("thinking") if rule is not None else None)
    if isinstance(forced, dict):
        setting = dict(forced)
    else:
        intent = _caller_intent(extra)
        if intent is None:
            return None
        setting = {"type": "disabled" if intent is False else "enabled"}
    effort = _effort_setup(extra, resolved)
    if effort:
        setting["output_config"] = {"effort": effort}
    return setting


def _caller_intent(extra: dict) -> Optional[bool]:
    """调用方是否**显式**表达了思考开关（None = 没说）。"""
    for key in THINK_KEYS:
        value = (extra or {}).get(key)
        if value is None:
            continue
        if isinstance(value, dict):
            kind = value.get("type")
            if kind == "disabled":
                return False
            if kind in ("enabled", "adaptive", "auto"):
                return True
            continue
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value != "none"
    return None


def _effort_setup(extra: dict, resolved: dict) -> Optional[str]:
    """档位来源优先级：调用方 output_config ＞ 调用方 reasoning_effort ＞ 规则产出。"""
    from_extra = (extra or {}).get("output_config") or {}
    raw = (from_extra.get("effort")
           or (extra or {}).get("reasoning_effort")
           or resolved.get("reasoning_effort"))
    if not isinstance(raw, str):
        return None
    value = _EFFORT_ALIAS.get(raw, raw)
    return value if value in _EFFORTS else None


def _fill_budget(thinking: dict, max_tokens: int) -> None:
    """`enabled` 模式必须带 `budget_tokens`，且须小于 max_tokens（否则 400）。"""
    if thinking.get("type") != "enabled" or thinking.get("budget_tokens"):
        return
    thinking["budget_tokens"] = min(_DEFAULT_THINK_BUDGET, max(1024, max_tokens - 1024))


__all__ = ["AnthropicProvider", "NATIVE_VERSION"]

"""Gemini GenerateContent 原生通道（`/v1beta/models/{model}:generateContent`）。

为什么单独实现，而不是继续走 openai_compat 打 Gemini 的兼容端点
----------------------------------------------------------------
1. **结构级差异，不是字段名差异**：角色只有 `user` / `model`（没有 `assistant`，也**没有
   system 角色**，system 必须外提为 `systemInstruction`）；文本 / 图片 / 工具调用全部混在
   `contents[].parts[]` 一个数组里；工具结果用 `functionResponse` part 而不是 `role="tool"` 消息。
2. **思考参数两套并存**：3 系列用 `thinkingConfig.thinkingLevel`，2.5 系列用
   `thinkingConfig.thinkingBudget`。**同时传 → 400**。走兼容端点只能瞎猜哪一套。
3. **思考块带签名**：官方要求把响应的 parts **原样**回传（函数调用场景是必需项），
   兼容层拿不到 `thoughtSignature`。
4. **原生计数字段**：`candidatesTokenCount` / `thoughtsTokenCount` / `cachedContentTokenCount`，
   且 `promptTokenCount` **含**缓存 —— 兼容层通常只给一个聚合数。
5. 鉴权是 **`x-goog-api-key`**，不是 `Authorization: Bearer`（不少兼容网关会因此 401）。

本文件负责传输与思考配置（`_thinking_config`）；内核 ↔ 原生线格式的双向转换在
`gemini_wire.py`（那是另一件事，混在一起会让"传输出错"和"翻译出错"难以区分）。

⚠️ 不发送 `candidateCount`：官方已在 Gemini 3 起移除该字段，发了会 400。

单生成器约定
------------
与 ollama / anthropic 一致：`complete` 是唯一的异步生成器，非流式走返回 list 的
`_fetch_once`。文本工具调用降级走纯函数就地过滤（`text_tool_events`），不嵌套生成器层。
"""
from __future__ import annotations

from typing import Any, Optional

from ..models import Message, ModelParameters
from .base import (
    BaseProvider,
    get_client,
    iter_sse_lines,
)
from ._gemini_wire import (
    error_text,
    events_from,
    finish_events,
    function_declarations,
    new_state,
    parse_sse,
    tool_config,
    to_contents,
)
from ._capability import check_capabilities
from ._profiles import apply_rule, resolve
from ._telemetry import Meter, feed

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com"
GEMINI_DEFAULT_BASE_URL = DEFAULT_BASE_URL

# 官方档位（3 系列）；2.5 系列无档位概念，只有 budget 数值
_LEVELS = ("minimal", "low", "medium", "high")
_EFFORT_ALIAS = {"none": "minimal", "off": "minimal", "xhigh": "high", "max": "high"}
# 档位 → 2.5 系列的 thinkingBudget。⚠️ 官方只定义 0（关闭）与 -1（动态），
# 中间这几档是**本内核的判断值**（按档位语义线性铺开），用到了会在 extra 里记账。
_BUDGET_BY_EFFORT = {"minimal": 0, "low": 2048, "medium": 8192, "high": 16384}

# 已被本 provider 消费、不得再原样外泄的 extra_body 键
_CONSUMED_EXTRA = frozenset({
    "thinking", "thinking_level", "thinkingLevel", "thinking_budget", "thinkingBudget",
    "reasoning_effort", "enable_thinking", "include_thoughts", "includeThoughts",
    "generation_config", "generationConfig",
})

# 调用方可能用这些 snake_case 写法表达 generationConfig 字段
_GEN_ALIAS = {
    "response_mime_type": "responseMimeType",
    "response_schema": "responseSchema",
    "stop_sequences": "stopSequences",
    "top_k": "topK",
    "presence_penalty": "presencePenalty",
    "frequency_penalty": "frequencyPenalty",
}


class _GeminiStatus(Exception):
    """HTTP 非 200（携带状态码与已解包的错误文本）。"""

    def __init__(self, status: int, text: str):
        super().__init__(f"{status}: {text}")
        self.status = status
        self.text = text


class GeminiProvider(BaseProvider):
    """Gemini GenerateContent 原生适配（流式 / 非流式）。"""

    _status_cls = _GeminiStatus

    # ─────────────────────────── 端点与请求头 ───────────────────────────
    def _root(self) -> str:
        """原生根地址：容忍把 `/v1beta`、`/v1beta/models` 写进 base_url 的几种误配。"""
        base = (self.cfg.base_url or DEFAULT_BASE_URL).strip().rstrip("/")
        for suffix in ("/v1beta/models", "/v1/models", "/v1beta", "/v1"):
            if base.endswith(suffix):
                base = base[: -len(suffix)].rstrip("/")
                break
        return base or DEFAULT_BASE_URL

    def _url(self, stream: bool, model: str) -> str:
        method = "streamGenerateContent" if stream else "generateContent"
        # 模型名允许带 `models/` 前缀，原生路径里只取末段
        name = (model or "").split("/")[-1]
        url = f"{self._root()}/v1beta/models/{name}:{method}"
        # 流式必须显式要 SSE（默认是分块 JSON 数组，不是 SSE）
        return url + "?alt=sse" if stream else url

    def _headers(self) -> dict:
        # 原生协议用 x-goog-api-key，不是 Authorization: Bearer
        return {"x-goog-api-key": self.cfg.api_key, "content-type": "application/json"}

    # ─────────────────────────── 主入口 ───────────────────────────
    async def complete(
        self, messages: list[Message], params: ModelParameters, model: str, stream: bool = True
    ):
        """产出增量字典（reasoning / content / tool_call_delta / tool_calls / done+usage+stats）。"""
        self._begin(model)
        notes: dict = {}                 # 组装期记账（思考降级、档位猜测）→ 并入 stats.extra
        payload = await self._build_payload(messages, params, model, stream, notes)
        async for ev in self._run_with_retry(model, stream, payload, notes):
            yield ev

    # ─────────────────────────── 载荷 ───────────────────────────
    async def _build_payload(self, messages, params: ModelParameters, model: str,
                             stream: bool, notes: Optional[dict] = None) -> dict:
        profile, rule = resolve(self.cfg.base_url, model, self.cfg.type)
        # 能力矩阵前置拦截：已知不支持视觉/文档/超限 → 在此抛错，不产生任何网络往返
        notes = notes if notes is not None else {}
        notes.update(check_capabilities(messages, profile, model, self.name, rule))
        extra = dict(getattr(params, "extra_body", None) or {})
        # 工具先于消息解析：思考块是否回传取决于本次是否带 tools（官方：函数调用的签名必需）
        tools = function_declarations(getattr(params, "tools", None))
        system, contents = await to_contents(messages, self.image_to_b64,
                                            echo_reasoning=bool(tools))
        body: dict[str, Any] = {"contents": contents}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        body["generationConfig"] = self._generation_config(params, rule, extra, notes or {})
        if tools:
            body["tools"] = tools
            cfg = tool_config(getattr(params, "tool_choice", None),
                              getattr(params, "parallel_tool_calls", None))
            if cfg:
                body["toolConfig"] = cfg
            if getattr(params, "parallel_tool_calls", None) is False:
                # 原生没有并行开关（>1 个调用由模型自行决定）→ 如实记账，不假装支持
                (notes if notes is not None else {})["parallel_tool_calls_ignored"] = \
                    "Gemini 原生无并行工具调用开关，该参数未下发"
        for k, v in extra.items():
            if k not in _CONSUMED_EXTRA:
                body[k] = v
        return body

    def _generation_config(self, params: ModelParameters, rule, extra: dict,
                           notes: dict) -> dict:
        """采样参数 + 思考配置 + 调用方给的 generationConfig 透传。"""
        cfg: dict[str, Any] = {
            "temperature": params.temperature,
            "topP": params.top_p,
            "maxOutputTokens": params.max_tokens,
        }
        thinking = _thinking_config(rule, extra, notes)
        if thinking:
            cfg["thinkingConfig"] = thinking
        # 显式给 generationConfig 的调用方优先（它最清楚自己要什么）
        given = extra.get("generation_config") or extra.get("generationConfig") or {}
        for k, v in (given.items() if isinstance(given, dict) else ()):
            cfg[k] = v
        for key, target in _GEN_ALIAS.items():
            if extra.get(key) is not None:
                cfg[target] = extra[key]
        return cfg

    # ─────────────────────────── 流式 ───────────────────────────
    async def _stream(self, payload: dict, meter: Meter, model: str,
                      notes: Optional[dict] = None):
        """SSE → 内核事件；失败抛 _GeminiStatus 或传输层异常。"""
        st = new_state()
        st["notes"] = notes or {}
        async for obj in self._iter_events(payload, meter, model):
            for ev in events_from(obj, st, self.name):
                feed(meter, ev)
                yield ev
        # ⚠️ 原生**没有 [DONE]**：循环自然结束（连接关闭）即收尾
        for ev in finish_events(st, meter):
            yield ev

    async def _iter_events(self, payload: dict, meter: Meter, model: str):
        """发请求并逐条产出已解析的 SSE 事件对象。"""
        client = get_client()
        async with client.stream("POST", self._url(True, model), headers=self._headers(),
                                 json=payload) as resp:
            meter.mark_ack()          # 响应头已到：网络/排队已走完
            if resp.status_code != 200:
                raise _GeminiStatus(resp.status_code, error_text(await resp.aread()))
            async for line in iter_sse_lines(resp):
                obj = parse_sse(line)
                if obj is not None:
                    yield obj

    async def _fetch_once(self, payload: dict, meter: Meter, model: str,
                          notes: Optional[dict] = None) -> list[dict]:
        """非流式：一次请求返回完整事件列表（返回 list 以避免多嵌一层生成器）。"""
        r = await get_client().post(self._url(False, model), headers=self._headers(),
                                    json=payload)
        meter.mark_ack()
        if r.status_code != 200:
            raise _GeminiStatus(r.status_code, error_text(r.content))
        st = new_state()
        st["notes"] = notes or {}
        events = events_from(r.json(), st, self.name)
        # 必须先喂计时器再结算：反了的话 chunks / 全文累加全是 0（结算时刻还没有帧）
        for ev in events:
            feed(meter, ev)
        return events + finish_events(st, meter)


# ─────────────────────────── 思考配置 ───────────────────────────
def _thinking_config(rule, extra: dict, notes: dict) -> Optional[dict]:
    """思考配置 → `generationConfig.thinkingConfig`；不该下发时返回 None。

    两套 API 由规则数据的 `thinking_api` 决定（`level` / `budget`），**不从
    forbid_params 反推** —— 反推是隐式耦合，改一处禁参会静默改掉判定。

    规则没命中（未知模型）时不下发：猜错哪一套就是必然 400，而不发只是少一个功能。
    """
    api = getattr(rule, "thinking_api", None) if rule is not None else None
    if api not in ("level", "budget"):
        return None
    intent, effort, budget = _read_intent(extra)
    if api == "level":
        cfg: dict[str, Any] = {"thinkingLevel": _level_for(intent, effort, rule, notes)}
    else:
        cfg = {"thinkingBudget": _budget_for(intent, effort, budget, notes)}
    # 只想要"要不要思考摘要"：档位为最低/关闭时不给 includeThoughts（本来就没摘要）
    if cfg.get("thinkingLevel") != "minimal" and cfg.get("thinkingBudget") != 0:
        cfg["includeThoughts"] = _wants_thoughts(extra)
    return cfg


def _read_intent(extra: dict):
    """从 extra_body 读 (开关意图, 档位字符串, budget 数值)。"""
    intent: Optional[bool] = None
    effort: Optional[str] = None
    budget: Optional[int] = None
    raw_effort = extra.get("reasoning_effort")
    if isinstance(raw_effort, str):
        effort = raw_effort
        intent = raw_effort.lower() not in ("none", "off", "minimal")
    level = extra.get("thinking_level") or extra.get("thinkingLevel")
    if isinstance(level, str):
        effort = level
    elif isinstance(level, int) and not isinstance(level, bool):
        budget = level
    raw_budget = extra.get("thinking_budget")
    if raw_budget is None:
        raw_budget = extra.get("thinkingBudget")
    if isinstance(raw_budget, int) and not isinstance(raw_budget, bool):
        budget = raw_budget
        intent = raw_budget != 0
    setting = extra.get("thinking")
    if isinstance(setting, bool):
        intent = setting
    elif isinstance(setting, dict) and setting.get("type") in ("disabled", "enabled"):
        intent = setting["type"] == "enabled"
    if extra.get("enable_thinking") is False:
        intent = False
    return intent, effort, budget


def _level_for(intent: Optional[bool], effort: Optional[str], rule, notes: dict) -> str:
    """档位（3 系列）。关思考时用 `minimal`（该 API 无"完全关闭"档）。"""
    if effort:
        level = _EFFORT_ALIAS.get(effort.lower(), effort.lower())
        if level in _LEVELS:
            return _clamp_level(level, getattr(rule, "effort_allowed", None))
    if intent is False and getattr(rule, "thinking", "") == "always_on":
        notes["thinking_forced"] = "该模型关不掉思考，已改用最低档 minimal"
    if intent is False:
        return "minimal"
    return _clamp_level("high", getattr(rule, "effort_allowed", None))


def _clamp_level(level: str, allowed) -> str:
    """不在允许集合里就取**最近的**允许档。

    刻意不用通用 `apply_rule` 的"超范围取最高档"策略：把调用方的 `minimal` 夹成 `high`
    会让"我只想快"变成"给我满档思考"，方向完全是反的。按档位序取最近邻才符合意图
    （`minimal` → `low`）。
    """
    if not allowed or level in allowed:
        return level
    if level not in _LEVELS:
        return allowed[-1]
    idx = _LEVELS.index(level)
    return min(allowed, key=lambda a: abs(_LEVELS.index(a) - idx) if a in _LEVELS else 99)


def _budget_for(intent: Optional[bool], effort: Optional[str], budget: Optional[int],
                notes: dict) -> int:
    """预算（2.5 系列）。官方只定义 0=关闭、-1=动态；中间档是**本内核的判断值**。

    用到中间档时会往 `notes` 记一条，避免把判断值当成官方口径。
    """
    if budget is not None:
        return budget
    if intent is False:
        return 0
    if effort:
        level = _EFFORT_ALIAS.get(effort.lower(), effort.lower())
        if level in _BUDGET_BY_EFFORT:
            notes.setdefault("thinking_budget_guess",
                             f"档位 {effort} → thinkingBudget={_BUDGET_BY_EFFORT[level]}"
                             "（非官方口径，本内核按档位语义铺开）")
            return _BUDGET_BY_EFFORT[level]
        notes.setdefault("thinking_budget_guess", f"档位 {effort} 无对应值，已按动态(-1)下发")
    return -1


def _wants_thoughts(extra: dict) -> bool:
    """是否要思考摘要。默认 True —— 拿不到摘要就等于内核的 reasoning 通道是空的。"""
    for key in ("include_thoughts", "includeThoughts"):
        value = extra.get(key)
        if isinstance(value, bool):
            return value
    return True


__all__ = ["GeminiProvider", "DEFAULT_BASE_URL", "GEMINI_DEFAULT_BASE_URL"]

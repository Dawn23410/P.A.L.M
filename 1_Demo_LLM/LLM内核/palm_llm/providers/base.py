"""Provider 抽象基类与工厂。"""
from __future__ import annotations

import asyncio
import base64
import json
import time
from typing import Optional

import httpx

from ..errors import (
    NotConfiguredError, TransportError, classify_error,
)
from ..models import Message, ModelParameters, ProviderConfig
from ..obs import log_event, request_id as _request_id
from ..retry import DEFAULT as DEFAULT_RETRY, RetryPolicy
from ._telemetry import Meter
from ._tooltext import TextToolFilter, declared_names, filter_events, text_tool_events

# ============================ 按事件循环复用的 HTTP 客户端 ============================
# 早期实现是「全局单例」：在 Web 服务（每请求独立线程 + 独立事件循环）场景下，
# 跨事件循环复用同一个 httpx.AsyncClient 会卡死；而按 id(loop) 缓存又会因
# 循环对象被 GC 后 id 复用，拿到「已关闭循环」的 client。最终方案：
# 以「事件循环对象本身」为键缓存（对象身份唯一，不会因 id 复用串号），
# 并在每次取用时清理已关闭的循环，兼顾连接复用与跨循环安全。
_clients: dict = {}


def get_client() -> httpx.AsyncClient:
    """返回当前事件循环复用的异步 HTTP 客户端（HTTP/2 + 连接池 + 保活）。

    需在运行中的协程内调用（会取 get_running_loop）。
    若环境中未安装 h2 依赖，自动降级为 HTTP/1.1 并给出一次警告，避免脚本闪退。
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    # 清理已关闭 / 已关闭客户端的残留条目（防止内存泄漏与串号）
    for k in [k for k, v in _clients.items() if (k.is_closed() if k else True) or v.is_closed]:
        try:
            if loop is not None:
                loop.create_task(_clients[k].aclose())  # 有运行中循环时挂任务优雅关闭
            # 无循环时跳过 await（进程退出场景，连接随进程回收）
        except Exception:
            pass
        _clients.pop(k, None)

    if loop is not None:
        client = _clients.get(loop)
        if client is not None and not client.is_closed:
            return client

    http2 = True
    try:
        import h2  # noqa: F401  探测 h2 是否可用（HTTP/2 必需）
    except ImportError:
        http2 = False
        print("[警告] 未安装 h2，HTTP/2 不可用，已回退 HTTP/1.1（性能略降）。"
              " 建议执行：pip install h2")
    client = httpx.AsyncClient(
        http2=http2,  # ★ 优先 HTTP/2（SSE 流式延迟更低、头压缩、无队头阻塞）
        timeout=httpx.Timeout(connect=5.0, read=300.0, write=10.0, pool=5.0),
        limits=httpx.Limits(
            max_connections=100,
            max_keepalive_connections=20,  # 复用已建立的连接
            keepalive_expiry=60.0,         # 连接保活 60s
        ),
    )
    if loop is not None:
        _clients[loop] = client
    return client


async def close_client() -> None:
    """程序退出时优雅关闭所有客户端（可选）。"""
    global _clients
    for c in list(_clients.values()):
        if not c.is_closed:
            try:
                await c.aclose()
            except Exception:
                pass
    _clients = {}


# ============================ Provider 共享件 ============================
# 各协议实现（openai_compat / anthropic / ollama 原生 …）共用的首字节超时、流拼接与消息归一。
# 放这里而不是让各自复制一份：流式+故障转移的时序细节很脆，两份实现必然漂移。

FIRST_BYTE_TIMEOUT = 15.0  # 首字节专用超时（秒）


class FirstByteTimeout(TransportError):
    """首字节等待超时（连接可能已被服务端关闭，应换连接重试）。

    归入 `TransportError` 子类：万一它逃逸到调用方，也是"可重试的传输错误"，
    语义不会退化成未知异常。
    """

    def __init__(self) -> None:
        super().__init__("首字节超时")

    def __str__(self) -> str:
        return (f"首字节 {FIRST_BYTE_TIMEOUT}s 内未到达"
                "（连接可能已被服务端关闭，或网关风控/网络异常）")


async def chain(first, rest):
    """把已取出的首行与其余行拼成一条异步流。

    不能直接用 itertools.chain —— 它会尝试同步迭代异步迭代器而报错。
    """
    yield first
    async for item in rest:
        yield item


async def iter_sse_lines(resp: httpx.Response):
    """逐行产出 SSE/NDJSON 文本行；首字节专用短超时内未到达则抛 FirstByteTimeout。

    三家 provider 的「首字节超时 + 拆行」逻辑完全一样，却各自写了一份 —— 这正是
    base.py 注释里说的"流式+故障转移的时序细节很脆，两份实现必然漂移"。调用方在拿到
    resp 后先 `mark_ack()`（响应头已到：网络/排队已走完），再读首行受 `FIRST_BYTE_TIMEOUT`
    约束，死连接在此快速失败、触发上层换连接重试；之后把首行与其余行拼成一条流。
    """
    aiter = resp.aiter_lines()
    try:
        first = await asyncio.wait_for(aiter.__anext__(), timeout=FIRST_BYTE_TIMEOUT)
    except asyncio.TimeoutError as e:
        raise FirstByteTimeout() from e
    async for line in chain(first, aiter):
        yield line


def to_chat_message(m: Message, echo_reasoning: bool = False) -> dict:
    """把 Message 归一为厂商 payload 的 message 结构。

    统一走 Message.to_openai()：集中处理 system / 多模态 / tool_calls /
    role="tool" 结果回填等全部形态，避免多处转换逻辑漂移。

    `echo_reasoning` 决定是否把上一轮的思考作为 `reasoning_content` 送回 —— 这是
    供应商契约而非偏好：DeepSeek 带 tools 时**必须**回传（否则 400）、Kimi K3 无条件
    必须回传；反之 legacy `deepseek-reasoner` 收到该字段直接 400。
    **默认 False（不发）是安全侧**：漏发只在"必须回传"的厂商上出错且错误明确，
    误发则会让"必须剥离"的厂商静默 400。是否回传由 `Profile.needs_reasoning_echo`
    决定，调用方显式传入。
    """
    to_openai = getattr(m, "to_openai", None)
    out = to_openai() if callable(to_openai) else {"role": m.role, "content": m.content}
    if echo_reasoning and m.reasoning and out.get("role") == "assistant":
        out["reasoning_content"] = m.reasoning
    return out


def normalize_tool_calls(raw) -> Optional[list[dict]]:
    """把任意来源的 tool_calls 归一为内核口径（OpenAI 结构）。

    归一四件事：补 `index`（缺了按位置补）、补 `id`、`type` 兜底 `function`、
    `arguments` 必须是 JSON **字符串**（原生端点给的是对象）。

    为什么上提到公共层：分片拼装出来的（流式）与整包下发的（非流式）必须是**同一形状**，
    否则调用方按 `index` 聚合时会在其中一条路径上拿到 `None`；两份实现也必然漂移。
    """
    if not raw:
        return None
    out = []
    for i, tc in enumerate(raw):
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function") or {}
        args = fn.get("arguments")
        out.append({
            "index": tc.get("index", i),
            "id": tc.get("id") or f"call_{i}",
            "type": tc.get("type") or "function",
            "function": {
                "name": fn.get("name") or "",
                "arguments": args if isinstance(args, str)
                else json.dumps(args or {}, ensure_ascii=False),
            },
        })
    return out or None


class BaseProvider:
    """所有模型提供方的统一接口。

    complete() 为异步生成器，依次产出字典：
        {"content": "文本片段"}                      # 增量 token
        {"reasoning": "思维链片段"}                  # 深度思考模型
        {"tool_call_delta": {"index","id","name"}}   # 工具调用开始（拿到名字即下发）
        {"tool_calls": [ ...OpenAI 原生结构... ]}    # 完整工具调用（流结束时，arguments 已拼接完整）
        {"done": True, "usage": {...}}               # 结束（usage 可选，原样透传厂商字段）
        {"done": True, "usage": {...}, "stats": {}}  # stats 为 telemetry 归一后的统一字段
    若出错则抛出 RuntimeError。

    `usage` 与 `stats` 的分工：`usage` 保留厂商原始字段（向后兼容，调用方若已依赖某家
    独有键不会被打断）；`stats` 是跨协议归一后的稳定字段（缓存命中、TTFT、输出速度等），
    新代码应只读 `stats`。归一逻辑见 `telemetry.py`。
    """

    def __init__(self, cfg: ProviderConfig):
        self.cfg = cfg
        self.name = cfg.name
        self.type = cfg.type
        # 重试策略：cfg 未指定则用默认（低延迟档）。见 retry.py 的取舍说明。
        self.retry: RetryPolicy = cfg.retry or DEFAULT_RETRY

    async def complete(
        self, messages: list[Message], params: ModelParameters, model: str, stream: bool = True
    ):
        raise NotImplementedError

    # ---- 公共工具 ----

    async def prewarm(self) -> float:
        """预热：预建立到服务端的 TCP+TLS 连接并放入复用池，把握手移出首字关键路径。

        通过一次轻量 GET <base_url>/models 完成——无论 200/401/404，只要响应到达
        即代表连接已建立并入池，后续请求可零握手复用。失败静默（预热尽力而为）。
        返回预热耗时（ms）。
        """
        client = get_client()
        t0 = time.perf_counter()
        try:
            await client.get(
                self.cfg.base_url.rstrip("/") + "/models",
                headers={"Authorization": f"Bearer {self.cfg.api_key}"},
            )
        except Exception:
            pass  # 预热尽力而为：网络未就绪时让正式请求自行处理错误
        return (time.perf_counter() - t0) * 1000

    def _check_key(self) -> None:
        if not self.cfg.api_key:
            raise NotConfiguredError(f"[{self.name}] 未配置 API Key，请在设置中填写。",
                                     provider=self.name)

    def _begin(self, model: str) -> str:
        """请求入口：校验配置 + 确保本次请求有 request_id（日志/排障关联用）。

        各 provider 的 `complete()` 首行都调它 —— 把"请求开始"这一个横切关注点
        收在一处，避免每个 provider 各写一份（也保证 request_id 一定被种下）。
        """
        self._check_key()
        rid = _request_id()
        log_event("request.start", level="debug",
                  provider=self.name, type=self.type, model=model)
        return rid

    async def _backoff(self, attempt: int, exc: BaseException, model: str) -> None:
        """按策略退避并记一条重试日志（attempt 从 1 计）。

        低延迟档 `delay=0` → 只记日志不等待；稳定档 → 指数退避 + 抖动，
        并优先尊重上游 `Retry-After`。
        """
        delay = self.retry.delay_for(attempt, exc)
        log_event("retry.scheduled", level="warning", provider=self.name, model=model,
                  attempt=attempt, delay=round(delay, 3), error=type(exc).__name__)
        if delay:
            await asyncio.sleep(delay)

    async def _run_with_retry(
        self, model: str, stream: bool, payload: dict, notes: dict
    ):
        """通用的「发请求 + 有界重试 + 已产出不重试」骨架（机制留内核，策略各 provider 填）。

        与 anthropic/gemini 原生实现**逐字一致**，仅 HTTP 状态异常类由子类 `self._status_cls`
        决定（协议错误 4xx/5xx 不可重试、按状态分类；纯传输失败按 `RetryPolicy` 换连接重试）。
        已向调用方产出内容后中断一律归 `StreamInterruptedError`（绝不重试，防重复生成/计费）。
        """
        names = declared_names(payload.get("tools"))
        last: Optional[BaseException] = None
        for attempt in range(1, self.retry.max_attempts + 1):
            meter = Meter(model=model)
            emitted = False
            try:
                if not stream:
                    done = await self._fetch_once(payload, meter, model, notes)
                    for ev in filter_events(done, names):
                        emitted = True
                        yield ev
                    return
                flt = TextToolFilter(names)
                async for ev in self._stream(payload, meter, model, notes):
                    for out_ev in text_tool_events(flt, ev):
                        emitted = True
                        yield out_ev
                return
            except self._status_cls as e:
                raise classify_error(
                    f"[{self.name}] {e.status}: {e.text}",
                    status=e.status, provider=self.name, model=model, text=e.text) from e
            except (httpx.TransportError, FirstByteTimeout) as e:
                last = e
                if emitted:
                    raise classify_error(
                        f"[{self.name}] {type(e).__name__}: {e}",
                        exc=e, provider=self.name, model=model,
                        interrupted=True) from e
                if attempt >= self.retry.max_attempts:
                    break
                await self._backoff(attempt, e, model)
        raise classify_error(
            f"[{self.name}] 连接失败（已自动重试 {self.retry.max_attempts - 1} 次）："
            f"{type(last).__name__}: {last or '未知连接错误'}",
            exc=last, provider=self.name, model=model) from last

    async def image_to_b64(self, url: str):
        """将图片 URL 解析为 (media_type, base64_str)。支持 data URI 与远程 http(s)。"""
        if url.startswith("data:"):
            header, b64 = url.split(",", 1)
            media = header.split(";")[0].split(":")[1]
            return media, b64
        client = get_client()  # ★ 复用全局单例，而非每次新建
        r = await client.get(url)
        r.raise_for_status()
        media = r.headers.get("content-type", "image/png")
        return media, base64.b64encode(r.content).decode()

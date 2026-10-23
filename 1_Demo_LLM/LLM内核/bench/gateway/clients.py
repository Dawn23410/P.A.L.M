"""四类客户端的统一封装（同一份入参、同一个 mock 上游，只换调用路径）。

对照对象（用户勾选的四项 + 直连基线）
------------------------------------
==================  ==========================================  ============
键                  路径                                        同语言？
==================  ==========================================  ============
``httpx_direct``    手写 httpx POST + 自己解析 SSE（**基线**）   是
``palm_kernel``     本仓库 LLM 内核 OpenAICompatProvider         是
``litellm``         LiteLLM（Python）                           是
``openai_sdk``      OpenAI 官方 Python SDK                      是
==================  ==========================================  ============

「净开销」的定义：`消费同一条流所耗墙钟 − httpx_direct`。所有客户端都必须**把流读完**
（含收尾帧），否则拿到的只是"谁更早返回"，不是同一件事。

⚠️ 公平性约束（写在代码里，避免日后被"优化"掉）
- 同一个循环、同一份 prompt、同一组 max_tokens、同一 stream 开关
- 都做预热（TCP/TLS/连接池）后再计时
- 都开连接复用（keep-alive），不新建 client
- litellm 强制 `num_retries=0`：默认重试会让个别慢样本被"重试掩盖"
"""
from __future__ import annotations

import json
from typing import Callable, Optional

import httpx

PROMPT = "用一句话说明什么是控制变量法。"
OnFirst = Optional[Callable[[], None]]


class BaseClient:
    name = "base"

    def __init__(self, base_url: str, model: str, max_tokens: int = 16):
        # base_url 形如 http://127.0.0.1:18080/v1（与 OpenAI SDK 的 base_url 口径一致）
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_tokens = max_tokens

    async def start(self) -> None:
        """建连接、预热。计时开始前调用。"""

    async def call(self, stream: bool, on_first: OnFirst = None) -> None:
        """跑一次完整请求并把流读完。`on_first` 在首个正文帧到达时被调一次（TTFT 用）。"""

    async def aclose(self) -> None:
        """释放资源。"""

    @staticmethod
    def _fire(on_first: OnFirst) -> None:
        if on_first is not None:
            on_first()

    # ── 共用 ──
    @property
    def payload(self) -> dict:
        return {
            "model": self.model,
            "messages": [{"role": "user", "content": PROMPT}],
            "max_tokens": self.max_tokens,
            "temperature": 0.0,
        }


# ───────────────────────── 1. 直连基线 ─────────────────────────
class HttpxDirect(BaseClient):
    """手写基线：不算"框架"，代表"自己写那几十行"的下限。

    刻意与内核保持同一份 httpx 配置（连接池/超时），否则比的是配置而不是实现。

    `headers` 用于把请求指向**自托管网关**：网关常靠自定义头路由
    （Portkey 的 `x-portkey-provider` / `x-portkey-custom-host`），
    此时客户端本身仍是这份手写实现 —— 变的是上游，不是客户端。
    """

    name = "httpx_direct"

    def __init__(self, *a, headers: Optional[dict] = None, **kw):
        super().__init__(*a, **kw)
        self._client: Optional[httpx.AsyncClient] = None
        self._headers = dict(headers or {})

    async def start(self) -> None:
        self._client = httpx.AsyncClient(
            headers=self._headers,
            timeout=httpx.Timeout(connect=5.0, read=300.0, write=10.0, pool=5.0),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20,
                                keepalive_expiry=60.0),
        )
        try:
            await self._client.get(self.base_url + "/models")
        except Exception:      # noqa: BLE001  预热尽力而为
            pass

    async def call(self, stream: bool, on_first: OnFirst = None) -> None:
        body = dict(self.payload, stream=stream)
        if not stream:
            r = await self._client.post(self.base_url + "/chat/completions", json=body)
            r.raise_for_status()
            self._fire(on_first)
            r.json()
            return
        async with self._client.stream("POST", self.base_url + "/chat/completions",
                                       json=body) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith("data: ") and line[6:] != "[DONE]":
                    obj = json.loads(line[6:])       # 真解析，不能只数行
                    if (obj.get("choices") or [{}])[0].get("delta", {}).get("content"):
                        self._fire(on_first)
                        on_first = None

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()


# ───────────────────────── 2. 本仓库内核 ─────────────────────────
class PalmKernel(BaseClient):
    """本仓库 LLM 内核（OpenAI 兼容通道）。"""

    name = "palm_kernel"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        from palm_llm import Message, ModelParameters, ProviderConfig, get_provider_instance

        self._Message = Message
        self._Params = ModelParameters
        self._prov = get_provider_instance(ProviderConfig(
            name="bench", type="openai_compat", base_url=self.base_url, api_key="bench"))

    async def start(self) -> None:
        await self._prov.prewarm()

    async def call(self, stream: bool, on_first: OnFirst = None) -> None:
        params = self._Params(max_tokens=self.max_tokens, temperature=0.0)
        msgs = [self._Message(role="user", content=PROMPT)]
        async for ev in self._prov.complete(msgs, params, self.model, stream=stream):
            if on_first is not None and ev.get("content"):
                self._fire(on_first)
                on_first = None

    async def aclose(self) -> None:
        from palm_llm.providers.base import close_client
        await close_client()


# ───────────────────────── 3. LiteLLM ─────────────────────────
class LiteLLM(BaseClient):
    """LiteLLM（Python）。这是"同语言主流框架"的正面对照。"""

    name = "litellm"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        import litellm

        self._litellm = litellm
        litellm.suppress_debug_info = True
        litellm.drop_params = False

    async def call(self, stream: bool, on_first: OnFirst = None) -> None:
        got = await self._litellm.acompletion(
            model=f"openai/{self.model}",
            api_base=self.base_url,
            api_key="bench",
            messages=[{"role": "user", "content": PROMPT}],
            max_tokens=self.max_tokens,
            temperature=0.0,
            stream=stream,
            num_retries=0,          # ★ 默认重试会让慢样本被掩盖
            timeout=120,
        )
        if stream:
            async for chunk in got:
                if on_first is not None and _delta_content(chunk):
                    self._fire(on_first)
                    on_first = None
        else:
            self._fire(on_first)
            _ = got.choices[0].message.content


# ───────────────────────── 4. OpenAI 官方 SDK ─────────────────────────
class OpenAISDK(BaseClient):
    """OpenAI 官方 Python SDK（指向同一个 mock）。"""

    name = "openai_sdk"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(base_url=self.base_url, api_key="bench",
                                   max_retries=0)

    async def start(self) -> None:
        try:
            await self._client.models.list()
        except Exception:      # noqa: BLE001
            pass

    async def call(self, stream: bool, on_first: OnFirst = None) -> None:
        kw = dict(model=self.model,
                  messages=[{"role": "user", "content": PROMPT}],
                  max_tokens=self.max_tokens, temperature=0.0, stream=stream)
        if stream:
            got = await self._client.chat.completions.create(**kw)
            async for chunk in got:
                if on_first is not None and _delta_content(chunk):
                    self._fire(on_first)
                    on_first = None
        else:
            await self._client.chat.completions.create(**kw)
            self._fire(on_first)

    async def aclose(self) -> None:
        await self._client.close()


def _delta_content(chunk) -> bool:
    """从各家 chunk 对象里取首帧正文（不碰 choices 为空的心跳/usage 帧）。"""
    choices = getattr(chunk, "choices", None) or []
    if not choices:
        return False
    delta = getattr(choices[0], "delta", None)
    return bool(getattr(delta, "content", None)) if delta is not None else False


REGISTRY = {
    "httpx_direct": HttpxDirect,
    "palm_kernel": PalmKernel,
    "litellm": LiteLLM,
    "openai_sdk": OpenAISDK,
}


def build(name: str, base_url: str, model: str, max_tokens: int,
          headers: Optional[dict] = None) -> BaseClient:
    cls = REGISTRY[name]
    return cls(base_url, model, max_tokens, headers=headers) if headers else \
        cls(base_url, model, max_tokens)

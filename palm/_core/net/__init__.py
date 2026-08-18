"""网卡门面：P.A.L.M 唯一对外网络出口（fail-closed，纯标准库实现）。

设计铁律：
1. 本模块自身**绝不 import httpx / requests / socket 等联网原语**——联网能力
   仅由「网卡砖」经 register_card(...) 注入执行器。其他砖一律经本门面请求外网。
2. 无网卡注册（或已拔出）→ 一切外网请求抛 NetworkForbidden（fail-closed），
   连带着 install_guard 兜住的「偷偷直连」也一并拒绝。
3. 本机回环（127.0.0.1 / localhost / ::1）不属外网出口，守卫放行，保证离线时
   本地模型服务（Ollama）仍可用。

执行器契约（由网卡砖注入）：
    execute(method, url, *, headers=None, content=None, json=None,
            params=None, timeout=None, stream=False, **kw) -> httpx.Response
返回 httpx.Response（网卡砖是唯一持有 httpx 之处），门面原样透传。
"""
from __future__ import annotations

import asyncio
import contextvars
import io
import sys
from dataclasses import dataclass
from typing import Any, Callable, Optional
from urllib.parse import urlparse

# ---- 铁律异常 ----
_NETWORK_FORBIDDEN_MSG = "未挂载网卡或网卡已拔出：外网请求被拒绝（fail-closed）"


class NetworkForbidden(RuntimeError):
    """无网卡 / 已拔出时抛出的铁律异常，fail-closed 的硬边界。"""


# ---- 统计 ----
@dataclass
class NetStats:
    """网卡累计统计：所有经门面的外网进出字节与请求数。"""
    requests: int = 0
    bytes_in: int = 0
    bytes_out: int = 0


_STATS = NetStats()

# ---- 离线标志：开启=进程内 fail-closed（与拔卡等价，但保留执行器可恢复）----
_OFFLINE = False


def set_offline(value: bool) -> None:
    """设置离线状态。开启后一切外网请求被拒（与拔卡等价，关闭即恢复）。

    这是离线限制的唯一真相源——网卡砖持有并暴露离线开关（原「离线模式」砖已归档，
    其 /api/offline 与 is_offline 能力已迁至网卡砖，离线现在本就是禁用网卡）。
    """
    global _OFFLINE
    _OFFLINE = bool(value)


def is_offline() -> bool:
    return _OFFLINE


# ---- 统一响应对象（纯标准库，不依赖 httpx）----
# 网卡砖经 httpx 实发后把响应包成 NetResponse 透传给各砖；各砖只消费本对象，
# 从而源码层面不持有任何 httpx/requests 接口。
class NetResponse:
    """网卡门面统一响应：覆盖各砖实际用到的全部读取接口。"""

    def __init__(self, status_code: int, headers: dict, *, content: bytes | None = None,
                 url: str = "", sync_gen=None, async_gen=None, box: dict | None = None):
        self._status_code = status_code
        self.headers: dict = dict(headers or {})
        self.url = url
        self._content = content
        self._sync_gen = sync_gen      # 同步流式：生成器，逐块产出 bytes
        self._async_gen = async_gen    # 异步流式：异步生成器，逐块产出 bytes
        self._box = box                # 延迟流式状态：{status, headers} 在首块前填充

    @property
    def status_code(self) -> int:
        if self._box is not None and self._box.get("status") is not None:
            return self._box["status"]
        return self._status_code

    @property
    def content(self) -> bytes:
        if self._content is None and self._sync_gen is not None:
            self._content = b"".join(self.iter_bytes())
        return self._content or b""

    @property
    def text(self) -> str:
        return (self._content or b"").decode("utf-8", errors="replace")

    def json(self):
        import json as _json
        return _json.loads(self.text)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}: {self.text[:300]}")

    def read(self) -> bytes:
        """同步读尽（流式响应消费为 content）。"""
        if self._content is None:
            self._content = b"".join(self.iter_bytes())
        return self._content

    async def aread(self) -> bytes:
        """异步读尽（流式响应消费为 content）。"""
        if self._content is None:
            self._content = b"".join([c async for c in self.aiter_bytes()])
        return self._content

    # ---- 同步流式 ----
    def iter_bytes(self):
        if self._sync_gen is not None:
            for chunk in self._sync_gen:
                yield chunk
        elif self._content:
            yield self._content

    def iter_lines(self):
        buf = b""
        for chunk in self.iter_bytes():
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                yield line
        if buf:
            yield buf

    # ---- 异步流式 ----
    async def aiter_bytes(self):
        if self._async_gen is not None:
            async for chunk in self._async_gen:
                yield chunk
        elif self._content:
            yield self._content

    async def aiter_lines(self):
        buf = b""
        async for chunk in self.aiter_bytes():
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                yield line
        if buf:
            yield buf


# ---- 执行器注册（sync / async 双形态，覆盖 httpx.Client 与 AsyncClient）----
_CARD_SYNC: Optional[Callable] = None
_CARD_ASYNC: Optional[Callable] = None

# 网卡砖执行自身的 httpx 调用时设此标志，避免守卫递归拦截。
_INTERNAL = contextvars.ContextVar("netcard_internal", default=False)

_LOOPBACK = ("127.0.0.1", "localhost", "::1", "0.0.0.0")


def is_loopback(host: str) -> bool:
    """判断主机是否为本机回环（不属外网出口）。"""
    h = (host or "").split(":")[0].strip().lower()
    if h.startswith("[") and h.endswith("]"):
        h = h[1:-1]
    return h in _LOOPBACK


def _host_of(url: str) -> str:
    try:
        return urlparse(url).hostname or ""
    except Exception:
        return ""


def host_of(url: str) -> str:
    """公开主机提取，供网卡砖做策略裁决。"""
    return _host_of(url)


def register_card(sync_executor: Callable, async_executor: Optional[Callable] = None) -> None:
    """网卡砖注册执行器。async_executor 缺省复用 sync_executor。"""
    global _CARD_SYNC, _CARD_ASYNC
    _CARD_SYNC = sync_executor
    _CARD_ASYNC = async_executor or sync_executor


def unplug() -> None:
    """软拔卡：撤销执行器，此后所有外网请求 fail-closed。"""
    global _CARD_SYNC, _CARD_ASYNC
    _CARD_SYNC = None
    _CARD_ASYNC = None


def is_card_present() -> bool:
    return _CARD_SYNC is not None


def stats() -> NetStats:
    return _STATS


class _InternalCtx:
    """网卡砖执行器自用上下文：内部调用绕过守卫，防止递归。"""

    def __enter__(self):
        self._tok = _INTERNAL.set(True)
        return self

    def __exit__(self, *exc):
        _INTERNAL.reset(self._tok)


def internal() -> _InternalCtx:
    return _InternalCtx()


# ---- 门面：同步 / 异步 ----
def request(method: str, url: str, *, headers=None, content=None, json=None,
            params=None, timeout=None, stream: bool = False, **kw):
    """同步外网请求门面。无卡或离线即 fail-closed。"""
    if _CARD_SYNC is None or _OFFLINE:
        raise NetworkForbidden(_NETWORK_FORBIDDEN_MSG)
    _STATS.requests += 1
    return _CARD_SYNC(method=method, url=url, headers=headers, content=content,
                      json=json, params=params, timeout=timeout, stream=stream, **kw)


async def arequest(method: str, url: str, *, headers=None, content=None, json=None,
                   params=None, timeout=None, stream: bool = False, **kw):
    """异步外网请求门面。无卡或离线即 fail-closed。"""
    if _CARD_ASYNC is None or _OFFLINE:
        raise NetworkForbidden(_NETWORK_FORBIDDEN_MSG)
    _STATS.requests += 1
    return await _CARD_ASYNC(method=method, url=url, headers=headers, content=content,
                             json=json, params=params, timeout=timeout, stream=stream, **kw)


def get(url, **kw):
    return request("GET", url, **kw)


def post(url, **kw):
    return request("POST", url, **kw)


def put(url, **kw):
    return request("PUT", url, **kw)


def delete(url, **kw):
    return request("DELETE", url, **kw)


# ===== 运行时拦截守卫 =====
# 目的：即使其他砖偷偷 import httpx/requests/urllib/socket 直连外网，也被拦截并
# 改走门面（无卡即失败）。回环地址一律放行，不影响本地服务。
_GUARD = {"installed": False, "originals": {}}


def _route_external(method, url, *, headers=None, content=None, json=None,
                    params=None, timeout=None, stream: bool = False,
                    async_mode: bool = False):
    """守卫路由：回环 / 内部调用→返回 None（走原始路径）；外网→经门面。

    返回 None 表示应放行原始发送；async_mode=False 返回响应对象，
    async_mode=True 返回 arequest 协程（由调用方 await）。
    """
    host = _host_of(url)
    if is_loopback(host) or _INTERNAL.get():
        return None
    if async_mode:
        return arequest(method, url, headers=headers, content=content, json=json,
                        params=params, timeout=timeout, stream=stream)
    return request(method, url, headers=headers, content=content, json=json,
                   params=params, timeout=timeout, stream=stream)


def install_guard() -> None:
    """安装运行时拦截守卫。幂等。"""
    if _GUARD["installed"]:
        return
    _patch_httpx()
    _patch_requests()
    _patch_urllib()
    _patch_socket()
    _GUARD["installed"] = True


def uninstall_guard() -> None:
    """卸载守卫，恢复原始联网原语。"""
    for name, orig in _GUARD["originals"].items():
        mod, _, attr = name.rpartition(".")
        try:
            setattr(sys.modules[mod], attr, orig)
        except Exception:
            pass
    _GUARD["originals"].clear()
    _GUARD["installed"] = False


def _save(orig, name: str) -> None:
    if name not in _GUARD["originals"]:
        _GUARD["originals"][name] = orig


def _patch_httpx() -> None:
    try:
        import httpx
    except Exception:
        return
    o = _GUARD["originals"]
    # 函数式 API：httpx.get/post/... 均内部调用 httpx.request
    if hasattr(httpx, "request"):
        orig = httpx.request
        _save(orig, "httpx.request")
        httpx.request = _httpx_request_fn(orig)
    # Client.send（同步）/ AsyncClient.send（异步）分别挂不同守卫
    _save(httpx.Client.send, "httpx.Client.send")
    httpx.Client.send = _sync_send_fn(httpx.Client.send)
    _save(httpx.AsyncClient.send, "httpx.AsyncClient.send")
    httpx.AsyncClient.send = _async_send_fn(httpx.AsyncClient.send)


def _httpx_request_fn(orig):
    def wrapper(method, url, *args, **kwargs):
        routed = _route_external(method, url, headers=kwargs.get("headers"),
                                 json=kwargs.get("json"), data=kwargs.get("data"),
                                 params=kwargs.get("params"),
                                 timeout=kwargs.get("timeout"),
                                 stream=kwargs.get("stream", False))
        if routed is None:
            return orig(method, url, *args, **kwargs)
        return routed
    return wrapper


def _sync_send_fn(orig_send):
    def wrapper(self, request, *args, **kwargs):
        method = request.method
        url = str(request.url)
        stream = kwargs.get("stream", False)
        routed = _route_external(method, url, headers=dict(request.headers),
                                 content=request.content, stream=stream)
        if routed is None:
            return orig_send(self, request, *args, **kwargs)
        return routed
    return wrapper


def _async_send_fn(orig_send):
    async def wrapper(self, request, *args, **kwargs):
        method = request.method
        url = str(request.url)
        stream = kwargs.get("stream", False)
        routed = _route_external(method, url, headers=dict(request.headers),
                                 content=request.content, stream=stream,
                                 async_mode=True)
        if routed is None:
            return await orig_send(self, request, *args, **kwargs)
        return await routed
    return wrapper


def _patch_requests() -> None:
    try:
        import requests
    except Exception:
        return
    o = _GUARD["originals"]
    orig_send = requests.Session.send
    _save(orig_send, "requests.Session.send")
    o["requests.Session.send"] = orig_send

    def send_wrapper(self, request, *args, **kwargs):
        routed = _route_external(request.method, request.url,
                                 headers=dict(request.headers),
                                 content=request.body, stream=True)
        if routed is None:
            return orig_send(self, request, *args, **kwargs)
        return _adapt_to_requests(routed, request.url)

    requests.Session.send = send_wrapper


def _adapt_to_requests(resp, url):
    import requests
    from requests.structures import CaseInsensitiveDict
    r = requests.Response()
    r.status_code = resp.status_code
    r.headers = CaseInsensitiveDict(resp.headers)
    r._content = getattr(resp, "content", b"") or b""
    r.url = url
    return r


def _patch_urllib() -> None:
    try:
        import urllib.request as ul
    except Exception:
        return
    orig = ul.urlopen
    _save(orig, "urllib.request.urlopen")

    def urlopen_wrapper(url, *args, **kwargs):
        target = url if isinstance(url, str) else getattr(url, "full_url", None)
        host = _host_of(target) if target else ""
        if is_loopback(host):
            return orig(url, *args, **kwargs)
        method = "GET"
        data = None
        if not isinstance(url, str):
            data = getattr(url, "data", None)
            method = getattr(url, "method", "GET") or "GET"
        routed = _route_external(method, target, content=data, stream=True)
        if routed is None:
            return orig(url, *args, **kwargs)
        return _adapt_to_urllib(routed)

    ul.urlopen = urlopen_wrapper


def _adapt_to_urllib(resp):
    class _UrlopenShim:
        def __init__(self, resp):
            self._b = io.BytesIO(getattr(resp, "content", b"") or b"")
            self.headers = resp.headers
            self.status = resp.status_code
            self.url = ""

        def read(self, *a):
            return self._b.read(*a)

        def info(self):
            return self.headers

        def getcode(self):
            return self.status

        def close(self):
            pass

    return _UrlopenShim(resp)


def _patch_socket() -> None:
    import socket
    o = _GUARD["originals"]
    orig_cc = socket.create_connection
    _save(orig_cc, "socket.create_connection")

    def cc_wrapper(*args, **kwargs):
        host = _sock_host(args, kwargs)
        if is_loopback(host) or _INTERNAL.get():
            return orig_cc(*args, **kwargs)
        # 外网裸 socket：上层 httpx/requests 已拦截；此处兜底拒绝。
        raise NetworkForbidden(_NETWORK_FORBIDDEN_MSG)

    socket.create_connection = cc_wrapper

    orig_connect = socket.socket.connect
    _save(orig_connect, "socket.socket.connect")

    def connect_wrapper(self, address):
        host = _addr_host(address)
        if is_loopback(host) or _INTERNAL.get():
            return orig_connect(self, address)
        raise NetworkForbidden(_NETWORK_FORBIDDEN_MSG)

    socket.socket.connect = connect_wrapper


def _sock_host(args, kwargs):
    if args:
        a0 = args[0]
        if isinstance(a0, tuple) and a0:
            return str(a0[0])
        return str(a0)
    addr = kwargs.get("address", ("", 0))
    return str(addr[0]) if isinstance(addr, tuple) and addr else ""


def _addr_host(address):
    if isinstance(address, tuple) and address:
        return str(address[0])
    return str(address)

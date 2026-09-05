"""网卡执行器：将 httpx 注入 palm 网卡门面（唯一出网出口）。

palm 自身不持有 httpx/requests/socket；所有外网（连 LLM、取 Ollama 嵌入）
都必须经由 net 门面，而门面在启动期需要本函数注册执行器，否则 fail-closed。
本微核心在 live 模式下初始化时调用一次 register_netcard()。

性能与正确性要点：
- 同步执行器用线程安全 Client 单例（httpx.Client 官方线程安全）。
- 异步执行器用**固定网络事件循环线程**：AsyncClient 只在该 loop 上创建与使用，
  杜绝跨 event loop 使用 AsyncClient（httpx 官方不支持，会引发 task 泄漏与告警）。
  非网络 loop 的调用经 run_coroutine_threadsafe 调度到网络 loop。
- stream 参数原样透传（palm provider 用 aiter_lines 消费）；客户端单例复用连接。
"""
import asyncio
import threading

import httpx

# 解耦：优先经 DI 容器取「net」门面（与「业务统一经 container 取用」保持一致），
# 失败则回退到直接 import，保证引导期/测试期不崩。
try:
    from palm._core.container import container
    _net_handle = container.get("net")
    net = _net_handle.impl if _net_handle is not None else None
except Exception:
    net = None
if net is None:
    from palm._core import net  # noqa: E402

_logger = None

# 固定网络事件循环与单例客户端
_NET_LOOP: asyncio.AbstractEventLoop | None = None
_NET_READY: threading.Event | None = None
_SYNC_CLIENT: httpx.Client | None = None
_ASYNC_CLIENT: httpx.AsyncClient | None = None


def _log(msg: str):
    global _logger
    if _logger is None:
        from .logging_setup import get_logger
        _logger = get_logger()
    _logger.warning(msg)


def _net_thread():
    """固定网络事件循环线程：常驻，承载 AsyncClient 的全部异步 I/O。"""
    global _NET_LOOP
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _NET_LOOP = loop
    _NET_READY.set()
    loop.run_forever()


def submit_coro(coro):
    """把协程调度到固定网络事件循环，返回 concurrent.futures.Future。"""
    if _NET_LOOP is None:
        raise RuntimeError("网卡未初始化：先调用 ensure_net()")
    return asyncio.run_coroutine_threadsafe(coro, _NET_LOOP)


def register_netcard() -> None:
    """注册 sync + async 执行器（返回真实 httpx.Response，门面原样透传）。"""
    global _SYNC_CLIENT, _ASYNC_CLIENT, _NET_READY
    if net.is_card_present():
        return

    _NET_READY = threading.Event()
    threading.Thread(target=_net_thread, daemon=True, name="netcard-loop").start()
    _NET_READY.wait(timeout=5.0)

    async def _make_async_client():
        global _ASYNC_CLIENT
        _ASYNC_CLIENT = httpx.AsyncClient(timeout=60.0)
        return _ASYNC_CLIENT

    # AsyncClient 必须在网络 loop 内创建（绑定该 loop 的连接池）
    submit_coro(_make_async_client()).result(timeout=5.0)
    _SYNC_CLIENT = httpx.Client(timeout=60.0)

    def _sync(method, url, *, headers=None, content=None, json=None,
              params=None, timeout=None, stream=False, **kw):
        req = _SYNC_CLIENT.build_request(
            method, url, headers=headers, content=content,
            json=json, params=params, timeout=timeout,
        )
        return _SYNC_CLIENT.send(req, stream=stream)

    async def _async(method, url, *, headers=None, content=None, json=None,
                     params=None, timeout=None, stream=False, **kw):
        req = _ASYNC_CLIENT.build_request(
            method, url, headers=headers, content=content,
            json=json, params=params, timeout=timeout,
        )
        loop = asyncio.get_running_loop()
        if loop is _NET_LOOP:
            return await _ASYNC_CLIENT.send(req, stream=stream)
        # 跨线程调用：调度到网络 loop，AsyncClient 始终只在网络 loop 上运行
        return await asyncio.wrap_future(
            submit_coro(_ASYNC_CLIENT.send(req, stream=stream)))

    net.register_card(_sync, _async)


def ensure_net() -> None:
    """幂等确保网卡已挂载；未挂载则注册。"""
    if not net.is_card_present():
        register_netcard()


def warmup(base_url: str, api_key: str = "") -> None:
    """后台预热：建连并探测端点，让第一条对话免去连接握手（失败静默）。"""
    if _SYNC_CLIENT is None:
        return

    def _do():
        try:
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
            _SYNC_CLIENT.get(f"{base_url.rstrip('/')}/models",
                             headers=headers, timeout=10.0)
        except Exception:
            pass

    threading.Thread(target=_do, daemon=True, name="netcard-warmup").start()

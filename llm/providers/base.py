"""Provider 抽象基类与工厂。"""
from __future__ import annotations

import asyncio
import base64

import httpx

from ..models import Message, ModelParameters, ProviderConfig

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
            _clients[k].aclose()
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


class BaseProvider:
    """所有模型提供方的统一接口。

    complete() 为异步生成器，依次产出字典：
        {"content": "文本片段"}    # 增量 token
        {"done": True, "usage": {...}}  # 结束（usage 可选）
    若出错则抛出 RuntimeError。
    """

    def __init__(self, cfg: ProviderConfig):
        self.cfg = cfg
        self.name = cfg.name
        self.type = cfg.type

    async def complete(
        self, messages: list[Message], params: ModelParameters, model: str, stream: bool = True
    ):
        raise NotImplementedError

    # ---- 公共工具 ----

    def _check_key(self) -> None:
        if not self.cfg.api_key:
            raise RuntimeError(f"[{self.name}] 未配置 API Key，请在设置中填写。")

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

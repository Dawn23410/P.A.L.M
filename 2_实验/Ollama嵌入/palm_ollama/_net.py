"""网卡门面适配 + 标准库降级：palm_ollama 的统一出网入口。

主工程在场时走 `palm._core.net`（唯一出网执行器，含回环放行与 fail-closed 策略）；
独立部署时用标准库 urllib 直连。两种模式都返回同一形状的响应对象
（status_code / headers / text / json() / iter_bytes() / iter_lines()），调用方无需关心环境。

为何上提为包级：原实现只在 `workspace/_net.py`（模型工作区的下载与探测），
而包内多处都要出网，各自复制一份门面探测逻辑必然漂移；`workspace/_net.py`
保留为兼容转发，既有导入路径不变。

注：对话适配器已迁至 `LLM内核/palm_llm/providers/ollama.py`（该处直接用 httpx），
不再是本模块的使用方 —— 本模块现只服务嵌入与模型工作区。
"""
from __future__ import annotations

import json as _json
import urllib.error
import urllib.request

try:  # 主工程在场：复用其网卡门面
    from palm._core.net import is_card_present as _facade_card
    from palm._core.net import request as _facade_request

    USES_HOST_NET = True
except Exception:  # noqa: BLE001  独立部署：标准库直连
    USES_HOST_NET = False


class _StdlibResponse:
    """urllib 响应的统一形状适配。

    `iter_lines()` 随读随产（不整块缓冲），供 NDJSON/SSE 流式消费；
    非 2xx 由 `request()` 包装成同样形状，使调用方读法与门面模式一致。
    """

    def __init__(self, resp):
        self._resp = resp
        self.status_code = getattr(resp, "status", None) or getattr(resp, "code", 0)
        self.headers = getattr(resp, "headers", {})
        self._closed = False

    def iter_bytes(self, chunk_size: int = 8192):
        """增量产出响应体。

        ★ 优先 `read1()`：它"有多少给多少"，是流式消费的正确原语。
        不可用时才退化为 `read()` —— 注意 `http.client` 的 `read(n)` 语义是
        **阻塞到读满 n 字节或流结束**，对 NDJSON/SSE 这类小分片流会造成人为缓冲延迟。
        实测（ollama /api/chat 流，本地 1.7B 模型，2026-09-22，总时长一致 ~1.79s）：

            读取方式        首块到达      总时长
            read(8192)      478.6ms      1809ms
            read1(8192)      59.6ms      1796ms

        即首字延迟被凭空抬高约 400ms（约 40 行 NDJSON 的等待量）。
        """
        reader = getattr(self._resp, "read1", None) or self._resp.read
        try:
            while True:
                chunk = reader(chunk_size)
                if not chunk:
                    break
                yield chunk
        finally:
            self.close()

    def iter_lines(self):
        """逐行产出；行跨 chunk 时自动拼接。"""
        buf = b""
        for chunk in self.iter_bytes():
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                yield line.decode("utf-8", "ignore")
        if buf:
            yield buf.decode("utf-8", "ignore")

    def text(self) -> str:
        return b"".join(self.iter_bytes()).decode("utf-8", "ignore")

    def json(self):
        return _json.loads(self.text())

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            try:
                self._resp.close()
            except Exception:  # noqa: BLE001  关闭失败无需上抛
                pass


def is_card_present() -> bool:
    """门面在场时用其判断；独立部署无门面概念，视为可用（是否外网由调用方负责）。"""
    return _facade_card() if USES_HOST_NET else True


def request(method: str, url: str, *, headers=None, json=None,
            timeout: float = 30.0, stream: bool = False, **kwargs):
    """发一次请求，返回统一形状的响应对象。

    `stream=True` 时响应体未被读取，由调用方经 `iter_lines()` / `iter_bytes()` 消费。
    传输层异常不在此吞掉（由调用方决定 fail-closed 语义）。
    """
    if USES_HOST_NET:
        return _facade_request(method, url, headers=headers, json=json,
                               timeout=timeout, stream=stream, **kwargs)
    data = _json.dumps(json).encode("utf-8") if json is not None else None
    hdrs = dict(headers or {})
    if data is not None:
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    try:
        return _StdlibResponse(urllib.request.urlopen(req, timeout=timeout))
    except urllib.error.HTTPError as exc:  # 与门面一致：非 2xx 也返回响应，交给调用方判读
        return _StdlibResponse(exc)


__all__ = ["request", "is_card_present", "USES_HOST_NET"]

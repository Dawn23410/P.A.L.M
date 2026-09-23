#!/usr/bin/env python3
"""确定性 mock 上游：一个 OpenAI 兼容的 /v1/chat/completions，用于控制变量对照。

为什么要自己写一个
------------------
控制变量法的前提是**上游完全一样**。用真实厂商端点做对照，网络抖动与供应商负载
会把网关的几十微秒差异整个淹掉（实测口径：真实模型延迟 500ms~5s，网关差异往往不可见）。
本 mock 把上游固定成"本地进程 + 固定延迟 + 固定 token 数"，于是：

    净开销 = 经过网关/内核的耗时 − 直连 mock 的耗时

一条直线的差值，方差可控、可复现。

刻意保留的"真实感"
------------------
- 流式走 **chunked transfer encoding**（真实厂商都这么发；若改成 Connection: close，
  每个请求都要重连，绝对数会虚高、也会掩盖网关差异）
- 首字节前有 `--ack-delay-ms`，模拟模型思考；chunk 间有 `--chunk-delay-ms`
- 支持 keep-alive、`stream_options.include_usage`、`usage` 收尾帧
- 服务端侧记录每条请求的**处理耗时**（handler 进入→body 写完），
  供 `/ _stats` 取用：用它可以从客户端墙钟里减掉服务端时间，得到更纯的客户端净开销

用法
----
    python3 mock_upstream.py --port 18080 --chunks 8 --ack-delay-ms 0 --chunk-delay-ms 0
"""
from __future__ import annotations

import argparse
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ARGS = argparse.Namespace(
    chunks=8, ack_delay_ms=0.0, chunk_delay_ms=0.0,
    model="bench-model", prompt_tokens=32, completion_tokens=8,
)
_LOCK = threading.Lock()
_SAMPLES: list[float] = []


def _chunk(payload: dict) -> bytes:
    body = ("data: " + json.dumps(payload, separators=(",", ":")) + "\n\n").encode()
    return b"%x\r\n" % len(body) + body + b"\r\n"


def _sse_delta(content: str | None, finish: str | None, with_role: bool = False) -> dict:
    delta: dict = {}
    if with_role:
        delta["role"] = "assistant"
    if content is not None:
        delta["content"] = content
    return {
        "id": "chatcmpl-bench0001", "object": "chat.completion.chunk",
        "created": 1758520000, "model": ARGS.model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"          # 开 keep-alive
    server_version = "bench-mock/1.0"
    # ⚠️ 必须关 Nagle。流式响应是一个 chunk 一次小写：默认 Nagle 会等对端 ACK，
    # 而对端的延迟 ACK 是 40ms —— 于是每个请求被凭空加上 ~40ms，
    # 把网关那几毫秒的差异整个盖住。这是本地回环基准的头号假象。
    disable_nagle_algorithm = True

    def setup(self) -> None:
        super().setup()
        try:
            self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass

    def log_message(self, fmt, *a):        # 静音，别把日志刷进 stdout 影响计时
        pass

    # ── 路由 ──
    def do_GET(self):                      # noqa: N802
        if self.path.rstrip("/").endswith("/models"):
            self._json({"object": "list", "data": [
                {"id": ARGS.model, "object": "model", "owned_by": "bench"}]})
        elif self.path.rstrip("/").endswith("/_stats"):
            with _LOCK:
                samples = list(_SAMPLES)
            self._json({"count": len(samples), "server_ms": samples})
        elif self.path.rstrip("/").endswith("/_reset"):
            with _LOCK:
                _SAMPLES.clear()
            self._json({"ok": True})
        else:
            self._send(404, b"not found", "text/plain")

    def do_POST(self):                     # noqa: N802
        if not self.path.rstrip("/").endswith("/chat/completions"):
            self._send(404, b"not found", "text/plain")
            return
        t0 = time.perf_counter()
        length = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            req = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            self._json({"error": {"message": "bad json"}}, status=400)
            return

        want_usage = bool((req.get("stream_options") or {}).get("include_usage"))
        if req.get("stream"):
            self._stream(want_usage, t0)
        else:
            self._json(self._full_object(want_usage), begin=t0)

    # ── 响应体 ──
    def _usage(self) -> dict:
        return {"prompt_tokens": ARGS.prompt_tokens,
                "completion_tokens": ARGS.completion_tokens,
                "total_tokens": ARGS.prompt_tokens + ARGS.completion_tokens}

    def _full_object(self, with_usage: bool) -> dict:
        obj = {
            "id": "chatcmpl-bench0001", "object": "chat.completion",
            "created": 1758520000, "model": ARGS.model,
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant",
                                     "content": "tok " * ARGS.completion_tokens}}],
        }
        if with_usage:
            obj["usage"] = self._usage()
        return obj

    def _stream(self, want_usage: bool, t0: float) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        if ARGS.ack_delay_ms:
            time.sleep(ARGS.ack_delay_ms / 1000.0)      # 模拟首字节前的思考

        def emit(payload: dict) -> None:
            self.wfile.write(_chunk(payload))
            self.wfile.flush()          # 立刻推走：否则小写会被缓冲/攒批，TTFT 失真

        try:
            emit(_sse_delta(None, None, with_role=True))
            for _ in range(ARGS.completion_tokens):
                if ARGS.chunk_delay_ms:
                    time.sleep(ARGS.chunk_delay_ms / 1000.0)
                emit(_sse_delta("tok ", None))
            emit(_sse_delta(None, "stop"))
            if want_usage:
                emit({"id": "chatcmpl-bench0001", "object": "chat.completion.chunk",
                      "created": 1758520000, "model": ARGS.model,
                      "choices": [], "usage": self._usage()})
            self.wfile.write(b"0\r\n\r\n")            # 收尾 chunk
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return                                      # 客户端提前断开：不是错误
        self._record(t0)

    def _json(self, obj: dict, status: int = 200, begin: float | None = None) -> None:
        body = json.dumps(obj).encode()
        self._send(status, body, "application/json")
        if begin is not None:
            self._record(begin)

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    @staticmethod
    def _record(t0: float) -> None:
        with _LOCK:
            _SAMPLES.append(round((time.perf_counter() - t0) * 1000, 3))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=18080)
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--chunks", type=int, default=8,
                   help="（兼容保留）chunk 数由 --completion-tokens 决定")
    p.add_argument("--completion-tokens", type=int, default=8)
    p.add_argument("--prompt-tokens", type=int, default=32)
    p.add_argument("--ack-delay-ms", type=float, default=0.0)
    p.add_argument("--chunk-delay-ms", type=float, default=0.0)
    p.add_argument("--model", default="bench-model")
    args = p.parse_args()

    ARGS.model = args.model
    ARGS.completion_tokens = args.completion_tokens
    ARGS.prompt_tokens = args.prompt_tokens
    ARGS.ack_delay_ms = args.ack_delay_ms
    ARGS.chunk_delay_ms = args.chunk_delay_ms

    srv = ThreadingHTTPServer((args.host, args.port), _Handler)
    srv.daemon_threads = True
    print(f"mock upstream on http://{args.host}:{args.port} "
          f"(ack={args.ack_delay_ms}ms chunk={args.chunk_delay_ms}ms "
          f"tokens={args.completion_tokens})", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()

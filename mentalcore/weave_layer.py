"""织语层（WeaveFace）独立模块 —— 从心智魔方核心中拆出。

设计目标：织语面是相对独立的「语料风格模块」生产者，不应与完整 MentalCore
（六面 + MockLLM + 记忆 + 存储 + Chroma）强耦合。本模块把织语面单独拎出来：

  - 默认 mode="mock"：纯本地计算，仅依赖 WeaveFace + 默认角色卡，
    不装配 MockLLM / 存储 / Chroma，无网络、无外部依赖即可产出风格模块。
  - mode="bridge"：转发到心智魔方桥接（默认 7788）走完整六面流水线。

HTTP 服务（可选，本服务只是把织语层暴露成独立端点）：
  POST /api/weave        {"text": "..."}
        -> {"ok":true,"source":"weave","content":...,"persona":...,"mode":...,
            "fields"?, "emotion"?, "affinity_delta"?, "manifest"?}
  GET  /api/weave/health -> {"ok":true,"mode":...,"persona":...}
默认监听 127.0.0.1:7799（WEAVE_HOST / WEAVE_PORT 覆盖）。
WEAVE_MODE=bridge 时本服务仅作转发代理。
"""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# weave_layer.py 位于 P.A.L.M/mentalcore/，需把该目录加入 sys.path 才能 import mentalcore 子包
_BRIDGE_DIR = os.path.dirname(os.path.abspath(__file__))
if _BRIDGE_DIR not in sys.path:
    sys.path.insert(0, _BRIDGE_DIR)

from mentalcore.faces.weave import WeaveFace
from mentalcore.faces.base import FaceContext
from mentalcore.persona_card import default_persona


class WeaveLayer:
    """独立织语层：默认本地 mock，可切 bridge 转发到完整心智魔方。

    拆出的意义：mock 模式下只用到 WeaveFace 与角色卡，不触碰 MockLLM /
    记忆面 / 存储面 / Chroma，因此可在完全无后端依赖的情况下产出「语料风格模块」。
    """

    def __init__(self, mode: str = "mock", bridge_url: str = "http://127.0.0.1:7788"):
        self.mode = mode
        self.bridge_url = bridge_url.rstrip("/")
        self._persona = None
        self._lock = threading.Lock()

    @property
    def persona(self):
        """默认角色卡懒加载（单例），mock 模式下是唯一需要的外部状态。"""
        if self._persona is None:
            with self._lock:
                if self._persona is None:
                    self._persona = default_persona()
        return self._persona

    def produce(self, text: str) -> dict:
        """产出织语层注入模块（语料风格模块）。mock 模式本地计算，零网络。

        返回结构与 bridge 模式对齐，便于前端统一消费：
          {source, content, persona, mode}
        """
        p = self.persona
        ctx = FaceContext(user_text=text or "", persona=p)
        module = WeaveFace().produce_module(ctx)
        content = module.content if module else ""
        return {
            "source": "weave",
            "content": content,
            "persona": p.name,
            "mode": self.mode,
        }

    def produce_via_bridge(self, text: str) -> dict | None:
        """bridge 模式：转发到心智魔方桥接（7788）走完整六面流水线。

        成功返回完整结果字典；任何失败（服务未起 / 超时 / 解析错）返回 None，
        由调用方降级到本地 mock。
        """
        import urllib.request
        import urllib.error

        payload = json.dumps({"text": text}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.bridge_url}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            d = json.loads(resp.read().decode("utf-8"))
        if not d.get("ok"):
            return None
        return {
            "source": "weave",
            "content": d.get("body", ""),
            "persona": d.get("persona"),
            "mode": "bridge",
            "fields": d.get("fields", {}),
            "emotion": d.get("emotion"),
            "affinity_delta": d.get("affinity_delta"),
            "manifest": d.get("manifest"),
            "model": d.get("model"),
        }


_LAYER = None
_LAYER_LOCK = threading.Lock()


def get_layer() -> WeaveLayer:
    """懒加载单例：mode 由环境变量 WEAVE_MODE 决定，默认 mock。"""
    global _LAYER
    if _LAYER is None:
        with _LAYER_LOCK:
            if _LAYER is None:
                mode = os.environ.get("WEAVE_MODE", "mock").strip().lower()
                if mode not in ("mock", "bridge"):
                    mode = "mock"
                bridge = os.environ.get("WEAVE_BRIDGE_URL", "http://127.0.0.1:7788").strip()
                _LAYER = WeaveLayer(mode=mode, bridge_url=bridge)
    return _LAYER


class Handler(BaseHTTPRequestHandler):
    server_version = "WeaveLayer/0.1"
    protocol_version = "HTTP/1.1"

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        sys.stderr.write("[weave-layer] " + (fmt % args) + "\n")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/weave/health":
            layer = get_layer()
            self._send_json({"ok": True, "mode": layer.mode, "persona": layer.persona.name})
        else:
            self._send_json({"ok": False, "error": "not found"}, status=404)

    def do_POST(self):
        path = self.path.split("?")[0]
        if path != "/api/weave":
            self._send_json({"ok": False, "error": "not found"}, status=404)
            return
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length) if length else b"{}"
            data = json.loads(raw.decode("utf-8") or "{}")
        except Exception as e:
            self._send_json({"ok": False, "error": f"请求解析失败: {e}"}, status=400)
            return
        text = (data.get("text") or "").strip()
        if not text:
            self._send_json({"ok": False, "error": "text 为空"}, status=400)
            return
        layer = get_layer()
        if layer.mode == "bridge":
            try:
                bridged = layer.produce_via_bridge(text)
                if bridged is not None:
                    self._send_json({"ok": True, **bridged})
                    return
            except Exception as e:
                sys.stderr.write(f"[weave-layer] bridge 转发失败，降级本地 mock：{e}\n")
        # 默认（mock）或 bridge 失败：本地产出风格模块
        self._send_json({"ok": True, **layer.produce(text)})


def main():
    host = os.environ.get("WEAVE_HOST", "127.0.0.1")
    port = int(os.environ.get("WEAVE_PORT", "7799"))
    layer = get_layer()
    server = ThreadingHTTPServer((host, port), Handler)
    sys.stderr.write(
        f"[weave-layer] 织语层已就绪（mode={layer.mode}），监听 http://{host}:{port}\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

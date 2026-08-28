"""心智魔方 · 织语层 HTTP 桥接服务（轻量、零 Web 框架依赖）。

把 MentalCoreSlotPort 暴露给前端 Chat 页：mock 模式下即走织语面 + MockLLM，
live 模式（配置 MENTALCORE_MODE=live + 端点）自动切换真实模型。

仅用 Python 标准库做 HTTP；mentalcore 本身需要 httpx/gmssl/pydantic
（mock 模式 chromadb 不装配，可缺失，记忆面自动降级）。

路由：
  POST /api/chat   {"text": "..."}
        -> {"ok":true,"body","fields","emotion","affinity_delta","manifest","model","persona"}
  GET  /api/health -> {"ok":true,"mode","model","persona"}
  GET  /api/persona-> 角色卡字段
  GET  /api/model  -> model_info
支持跨域（CORS），默认监听 127.0.0.1:7788（MENTALCORE_HOST / MENTALCORE_PORT 覆盖）。
"""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# bridge.py 位于 P.A.L.M/mentalcore/，需把该目录加入 sys.path 才能 import mentalcore 子包
_BRIDGE_DIR = os.path.dirname(os.path.abspath(__file__))
if _BRIDGE_DIR not in sys.path:
    sys.path.insert(0, _BRIDGE_DIR)

from mentalcore.config import load_config
from mentalcore.core import build_core
from mentalcore.persona_card import default_persona

_CORE = None
_CORE_LOCK = threading.Lock()
_SEND_LOCK = threading.Lock()


def get_core():
    """懒加载单例 MentalCore：mock 模式 persist=False，历史与好感度在内存中跨轮连续。"""
    global _CORE
    if _CORE is None:
        with _CORE_LOCK:
            if _CORE is None:
                cfg = load_config()
                _CORE = build_core(cfg, default_persona())
    return _CORE


# IntentRouter 位于 mentalcore.exo.intent_router，但 exo 包的 __init__ 因缺失
# Worker cube 源码无法 import；这里按文件直接加载，绕过损坏的包 __init__。
def _load_intent_router():
    import importlib.util as _ilu
    import sys as _sys
    # 包实际位于嵌套的 mentalcore/mentalcore/ 下（import mentalcore 解析到此处）
    p = os.path.join(_BRIDGE_DIR, "mentalcore", "exo", "intent_router.py")
    spec = _ilu.spec_from_file_location("mcore_intent_router", p)
    mod = _ilu.module_from_spec(spec)
    # 必须注册进 sys.modules，否则 @dataclass 等装饰器查找模块元数据时失败
    _sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod.IntentRouter


def _build_faces_state(core):
    """把 MentalCore 六面（实际 5 个 face 实例 + 好感度）快照成前端可视化结构。"""
    from mentalcore.faces.base import FaceContext
    p = core.persona
    ctx = FaceContext(user_text="", persona=p, history=core.history)
    emotion_face = next((f for f in core.faces if f.name == "emotion"), None)
    stage_name = emotion_face._stage_name(ctx) if emotion_face else "陌生"
    _wd = "一二三四五六日"
    return [
        {
            "name": "persona", "label": "人格面",
            "description": "角色卡静态设定（性格 / 缺点 / 语气 / 话痨度 / 背景）",
            "state": {
                "name": p.name, "tagline": p.tagline,
                "pillars": list(p.personality_pillars),
                "flaws": list(p.flaws), "tone": p.tone,
                "talkativeness": p.talkativeness,
                "age": p.age, "background": p.background,
                "example": p.example_dialogue,
            },
        },
        {
            "name": "emotion", "label": "情感面（好感度）",
            "description": "信任地基 base / 当下心情 dynamics / 羁绊 bond；整面可由 affinity_enabled 关闭",
            "state": {
                "base": emotion_face.base if emotion_face else 0,
                "dynamics": emotion_face.dynamics if emotion_face else 0,
                "bond": emotion_face.bond if emotion_face else 0,
                "stage_name": stage_name,
                "affinity_enabled": p.affinity_enabled,
            },
        },
        {
            "name": "weave", "label": "织语面",
            "description": "产出「语料风格模块」注入 LLM（口吻 / 格式约束 / 内心独白规范）",
            "state": {"format_spec": p.format_spec},
        },
        {
            "name": "rhythm", "label": "律动面",
            "description": "时间感知 + 日程切片 + 生日触发（dynamic_updates_enabled 关闭则不注入）",
            "state": {
                "enabled": p.dynamic_updates_enabled,
                "now": ctx.now.strftime("%Y-%m-%d %H:%M 星期") + _wd[ctx.now.weekday()],
                "schedule": [list(s) for s in p.schedule] if p.schedule else [],
            },
        },
        {
            "name": "memory", "label": "记忆面",
            "description": "短期记忆（近期对话）+ 长期语义召回",
            "state": {
                "recent_turns": len(core.history),
                "semantic_available": bool(getattr(core.semantic_memory, "available", False)),
            },
        },
    ]


def _build_guardrail(cfg):
    """护栏（guardrail）档位配置——仅展示配置，不假装执行引擎在线。"""
    return {
        "profile": getattr(cfg, "exo_profile", "strict"),
        "rules_yaml": getattr(cfg, "exo_rules_yaml", "") or "",
        "emotion_via_llm": getattr(cfg, "emotion_via_llm", True),
        "mode": getattr(cfg, "mode", "mock"),
        "crypto_enabled": getattr(cfg, "crypto_enabled", True),
        "tiers": ["hardline", "strict", "loose", "ai", "whitelist"],
        "note": "执行引擎(Worker)源码在本仓库缺失，护栏仅展示配置档位；实际拦截逻辑待补全。",
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "MentalCoreBridge/0.1"
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
        sys.stderr.write("[mentalcore-bridge] " + (fmt % args) + "\n")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        path, _, qs = self.path.partition("?")
        try:
            core = get_core()
        except Exception as e:
            self._send_json({"ok": False, "error": f"core 未就绪: {e}"}, status=503)
            return
        if path == "/api/health":
            self._send_json({
                "ok": True,
                "mode": load_config().mode,
                "model": core.get_model_info(),
                "persona": core.persona.name,
                "faces": [f.name for f in core.faces],
            })
        elif path == "/api/faces":
            self._send_json({"ok": True, "faces": _build_faces_state(core)})
        elif path == "/api/guardrail":
            self._send_json({"ok": True, **_build_guardrail(load_config())})
        elif path == "/api/route":
            from urllib.parse import parse_qs
            text = (parse_qs(qs).get("text", [""])[0] or "").strip()
            if not text:
                self._send_json({"ok": False, "error": "text 为空"}, status=400)
                return
            router = _load_intent_router()()
            r = router.route(text, worker_active=False)
            self._send_json({
                "ok": True,
                "intent": r.intent,
                "task_goal": r.task_goal,
                "intervention_action": r.intervention_action,
                "redirect_instruction": r.redirect_instruction,
                "confidence": r.confidence,
                "note": "意图路由为纯关键词匹配（零 LLM）；Worker 未在线时 intervention/query 降级为 chat。",
            })
        elif path == "/api/persona":
            p = core.persona
            self._send_json({
                "ok": True,
                "id": p.id, "name": p.name, "tagline": p.tagline,
                "tone": p.tone, "pillars": list(p.personality_pillars),
            })
        elif path == "/api/model":
            self._send_json({"ok": True, **core.get_model_info()})
        else:
            self._send_json({"ok": False, "error": "not found"}, status=404)

    def do_POST(self):
        path = self.path.split("?")[0]
        if path != "/api/chat":
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
        try:
            core = get_core()
            with _SEND_LOCK:  # 串行化对话调用，避免单例 history 竞争
                pkt, manifest, emotion = core.send_message(text)
                affinity_delta = core.last_affinity_delta
            self._send_json({
                "ok": True,
                "body": pkt.body,
                "fields": pkt.fields,
                "emotion": emotion,
                "affinity_delta": affinity_delta,
                "manifest": manifest,
                "model": core.get_model_info(),
                "persona": core.persona.name,
            })
        except Exception as e:
            self._send_json({"ok": False, "error": f"推理失败: {e}"}, status=500)


def main():
    host = os.environ.get("MENTALCORE_HOST", "127.0.0.1")
    port = int(os.environ.get("MENTALCORE_PORT", "7788"))
    server = ThreadingHTTPServer((host, port), Handler)
    try:
        get_core()
        sys.stderr.write(
            f"[mentalcore-bridge] 心智魔方已就绪（织语层 + MockLLM），监听 http://{host}:{port}\n")
    except Exception as e:
        sys.stderr.write(
            f"[mentalcore-bridge] 警告：core 预热失败，将在首次请求时重试：{e}\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

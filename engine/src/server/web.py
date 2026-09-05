"""AI 对话 WebUI 服务端（仅依赖标准库，无需额外安装）。

- 静态托管 frontend/ 目录（根路径 -> README.md 复用说明；/md-renderer.js 可复用控件；/view -> 实时答案查看器；style.css / app.js / vendor/*）
- 通过 SSE 把后端真实 AI（backend.chat.run_chat）的流式回复推送到浏览器
- 提供配置 / 提供方 / 会话 / 上传 等 REST 接口

运行：
    .venv/Scripts/python.exe web.py            # 默认 http://127.0.0.1:8080
    .venv/Scripts/python.exe web.py --port 9000
    .venv/Scripts/python.exe web.py --sandbox  # 额外启用代码沙箱端点 /api/run（python/node/bash，有风险）
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import html
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent   # src/server
ROOT = HERE.parent.parent                # 项目根目录（含 backend/、frontend/、src/）
FRONTEND_DIR = ROOT / "frontend"
sys_path = str(ROOT)
import sys
if sys_path not in sys.path:
    sys.path.insert(0, sys_path)

from backend.config import load_config, save_config, get_provider, UPLOAD_DIR
from backend import storage
from backend.models import (
    AppConfig, ChatRequest, Message, ModelParameters, ProviderConfig, Preset,
)

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
LAST_ANSWER_FILE = ROOT / "data" / "last_answer.json"
LANG_STATS_FILE = ROOT / "lang_stats.json"
EMOJI_STATS_FILE = ROOT / "emoji_stats.json"
EMOJI_COMMON_FILE = FRONTEND_DIR / "vendor" / "emoji-common.js"
EMOJI_FULL_FILE = FRONTEND_DIR / "vendor" / "emoji-full.js"
EMOJI_PROMOTE_THRESHOLD = 5  # 7天内某非常见 emoji 使用次数≥此值，则升入 common 集合
MASK = "********"

# ============ 代码沙箱执行（默认关闭，需 --sandbox 或 ENABLE_SANDBOX=1 启用） ============
# 警告：启用后 /api/run 会真实执行 python/node/bash 代码（命令执行风险），仅限本机可信环境。
# 启用后同时启动透明网络拦截代理（默认断网 + 用户授权 + 配额熔断）。
SANDBOX_ENABLED = False
SANDBOX_TIMEOUT = 10  # 单次执行最长时间（秒）
SANDBOX_PROXY_PORT = int(os.environ.get("SANDBOX_PROXY_PORT", "18100"))
SANDBOX_ISOLATE_USER = os.environ.get("SANDBOX_USER")  # 物理隔离账户（可选）

from src.sandbox import net as sandbox_net
from src.sandbox import ast as sandbox_ast
from src.sandbox import threat as sandbox_threat
from src.sandbox import run as sandbox_run
from src.sandbox import honeypot as sandbox_honeypot


def _resolve_interp(lang: str):
    """解析语言对应的解释器路径（支持环境变量覆盖，回退 PATH 查找）。"""
    if lang == "python":
        env = os.environ.get("SANDBOX_PYTHON")
        if env:
            return env
        # web.py 自身通常由受管 python 启动：直接复用 sys.executable 保证可用
        if sys.executable and "python" in os.path.basename(sys.executable).lower():
            return sys.executable
        return shutil.which("python3") or shutil.which("python")
    if lang == "node":
        env = os.environ.get("SANDBOX_NODE")
        if env:
            return env
        return shutil.which("node")
    if lang == "bash":
        env = os.environ.get("SANDBOX_BASH")
        if env:
            return env
        return shutil.which("bash") or shutil.which("sh")
    return None


def _interp_args(interp: str, lang: str, code: str):
    if lang == "python":
        return [interp, "-c", code]
    if lang == "node":
        return [interp, "-e", code]
    if lang == "bash":
        return [interp, "-c", code]
    return None


def run_code_sandbox(lang: str, code: str, timeout: int = SANDBOX_TIMEOUT) -> dict:
    """在子进程中执行代码；返回 {output, error, exitCode, ...}。非安全沙箱（仅超时隔离）。"""
    interp = _resolve_interp(lang)
    if not interp:
        return {"output": "", "error": "未找到 %s 解释器（请用 SANDBOX_%s 环境变量或 PATH 提供）"
                % (lang, lang.upper()), "exitCode": None, "missing": True}
    try:
        args = _interp_args(interp, lang, code)
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return {"output": proc.stdout or "", "error": proc.stderr or "", "exitCode": proc.returncode}
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or "")
        err = (e.stderr or "") + ("\n[超时] 执行超过 %ds 被中止" % timeout)
        return {"output": out, "error": err, "exitCode": None, "timeout": True}
    except Exception as e:  # noqa: BLE001
        return {"output": "", "error": "执行失败：%s" % e, "exitCode": None}


def _mask_config(cfg: AppConfig) -> dict:
    """返回配置 dict，api_key 统一遮罩（非空则替换为 ******）。"""
    d = json.loads(cfg.model_dump_json())
    for p in d.get("providers", []):
        if p.get("api_key"):
            p["api_key"] = MASK
        p.pop("base_url_internal", None)
    return d


def _apply_config_incoming(incoming: dict) -> AppConfig:
    """处理前端回写的配置：若 api_key 为遮罩值，则保留磁盘上的真实值。"""
    current = load_config()
    cur_keys = {p.id: p.api_key for p in current.providers}
    for p in incoming.get("providers", []):
        if p.get("api_key") == MASK:
            p["api_key"] = cur_keys.get(p["id"], "")
    return AppConfig.model_validate(incoming)


# ============ Emoji 使用统计（7天滑动窗口）与 common 集合自动升舱 ============
_emoji_common_keys_cache = None  # 进程内缓存 common 键集合（升舱后失效）


def _date_key(ts: float | None = None) -> str:
    return datetime.date.fromtimestamp(ts if ts is not None else time.time()).isoformat()


def _emoji_obj_from_file(path: Path) -> dict:
    """解析 `window.X = { "k": "v", ... };` 形式文件，返回 {name: unicode}。
    容错 JS 风格尾逗号（浏览器允许，但 json.loads 不允许）。"""
    try:
        txt = path.read_text(encoding="utf-8")
    except Exception:
        return {}
    m = re.search(r"=\s*\{(.*)\}\s*;", txt, re.S)
    if not m:
        return {}
    obj_str = m.group(1)
    obj_str = re.sub(r",\s*$", "", obj_str.rstrip())  # 去除对象末尾尾逗号
    try:
        return json.loads("{" + obj_str + "}")
    except Exception:
        return {}


def _common_keys() -> set:
    global _emoji_common_keys_cache
    if _emoji_common_keys_cache is None:
        _emoji_common_keys_cache = set(_emoji_obj_from_file(EMOJI_COMMON_FILE).keys())
    return _emoji_common_keys_cache


def _load_emoji_stats() -> dict:
    try:
        d = json.loads(EMOJI_STATS_FILE.read_text(encoding="utf-8"))
    except Exception:
        d = {}
    if not isinstance(d, dict):
        d = {}
    d.setdefault("by_day", {})
    return d


def _prune_emoji_stats(d: dict) -> dict:
    """仅保留最近 7 个自然日的分桶，保持文件精简且窗口正确。"""
    today = _date_key()
    cutoff = (datetime.date.fromisoformat(today) - datetime.timedelta(days=6)).isoformat()
    by_day = {k: v for k, v in d.get("by_day", {}).items() if k >= cutoff}
    d["by_day"] = by_day
    return d


def _merged7(d: dict) -> dict:
    out: dict = {}
    for day, m in d.get("by_day", {}).items():
        if not isinstance(m, dict):
            continue
        for k, v in m.items():
            if isinstance(v, int):
                out[k] = out.get(k, 0) + v
    return out


def _emoji_summary(d: dict) -> dict:
    merged = _merged7(d)
    common = _common_keys()
    total = sum(merged.values())
    common_hits = sum(v for k, v in merged.items() if k in common)
    suggestions = sorted(
        [k for k, v in merged.items()
         if k not in common and v >= EMOJI_PROMOTE_THRESHOLD],
        key=lambda k: -merged[k],
    )
    return {
        "counts": merged,
        "commonCount": len(common),
        "fullCount": len(_emoji_obj_from_file(EMOJI_FULL_FILE)),
        "total": total,
        "commonHits": common_hits,
        "hitRate": (common_hits / total) if total else 1.0,
        "threshold": EMOJI_PROMOTE_THRESHOLD,
        "suggestions": suggestions,
        "lastExpand": d.get("last_expand"),
    }


def _expand_common(promote: list) -> int:
    """把 promote 中的 emoji 升入 common 集合（重写 emoji-common.js）。
    保留原 common 顺序，再从 emoji-full.js 取值追加。返回新增条数。"""
    global _emoji_common_keys_cache
    full = _emoji_obj_from_file(EMOJI_FULL_FILE)
    cur = _emoji_obj_from_file(EMOJI_COMMON_FILE)
    cur_order = list(cur.keys())
    cur_set = set(cur_order)
    added = []
    for name in promote:
        if name in full and name not in cur_set:
            added.append(name)
    if not added:
        return 0
    new_order = cur_order + added
    lines = [
        "/* emoji-common.js — 一级常见 emoji（随 UI 同步加载）*/",
        "/* 自动维护：服务端按 7 天使用频率将高频非常见 emoji 升入本集合 */",
        "window.EMOJI_MAP = {",
    ]
    body = []
    for k in new_order:
        if k in full:
            body.append('  "%s": "%s"' % (k, full[k]))
    lines.append(",\n".join(body))
    lines.append("};")
    EMOJI_COMMON_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _emoji_common_keys_cache = None  # 失效缓存
    return len(added)


def _emoji_expand_now() -> dict:
    """将 7 天内达阈值的非常见 emoji 升入 common 集合，返回结果。GET/POST 共用。"""
    d = _prune_emoji_stats(_load_emoji_stats())
    summary = _emoji_summary(d)
    added = _expand_common(summary["suggestions"])
    if added:
        d = _load_emoji_stats()
        d["last_expand"] = _date_key()
        try:
            EMOJI_STATS_FILE.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
    return {
        "expanded": added,
        "commonCount": _emoji_summary(_load_emoji_stats())["commonCount"],
    }



class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    # ---------- CORS（允许面板从 file:// 或任意来源调用本机 API） ----------
    def end_headers(self):
        # 所有响应统一注入跨域头，使以 file:// 双击打开的面板也能访问本机接口
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Max-Age", "86400")
        super().end_headers()

    def do_OPTIONS(self):
        # 预检请求：POST + JSON Content-Type 会触发浏览器预检，直接返回 204 + CORS 头
        self.send_response(204)
        self.end_headers()

    # ---------- 工具 ----------
    def _send_json(self, obj, status: int = 200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, text: str, status: int = 200, ctype: str = "text/plain; charset=utf-8"):
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0") or "0")
        return self.rfile.read(length) if length else b""

    @staticmethod
    def _decode_body(body: bytes) -> str:
        """容错解码：优先 UTF-8，回落到中文 GBK / latin-1（兼容 Windows 终端的编码差异）。"""
        for enc in ("utf-8", "cp936", "latin-1"):
            try:
                return body.decode(enc)
            except UnicodeDecodeError:
                continue
        return body.decode("utf-8", "replace")

    def _serve_static(self, url_path: str):
        if url_path in ("/", ""):
            rel = "README.md"
        else:
            rel = url_path.lstrip("/")
        # 防目录穿越
        target = (FRONTEND_DIR / rel).resolve()
        if not str(target).startswith(str(FRONTEND_DIR.resolve())) or not target.is_file():
            self.send_error(404, "Not Found")
            return
        ctype, _ = mimetypes.guess_type(str(target))
        ctype = ctype or "application/octet-stream"
        # 强制 UTF-8：避免浏览器以本地编码（如 GBK）解码含中文的 .js/.html/.css 等文本导致乱码
        if "charset" not in ctype and (
            ctype.startswith("text/")
            or ctype in ("application/javascript", "application/json", "application/xml")
        ):
            ctype += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(target.stat().st_size))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        data = target.read_bytes()
        self.wfile.write(data)
        try:
            self.wfile.flush()
        except Exception:
            pass

    # ---------- 路由 ----------
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == "/favicon.ico":
            # 浏览器会自动请求 /favicon.ico；直接返回 204，避免控制台 404 噪音
            self.send_response(204)
            self.end_headers()
            return
        if path == "/api/config":
            return self._send_json(_mask_config(load_config()))
        if path == "/api/run":
            # 仅返回沙箱启用状态（不执行任何代码）
            return self._send_json({"enabled": SANDBOX_ENABLED})
        if path == "/api/net/pending":
            itc = sandbox_net.get_interceptor()
            if not itc:
                return self._send_json({"enabled": False, "pending": []})
            return self._send_json({"enabled": True, "pending": itc.list_pending()})
        if path == "/api/net/policy":
            itc = sandbox_net.get_interceptor()
            if not itc:
                return self._send_json({"enabled": False})
            return self._send_json({"enabled": True, **itc.status()})
        if re.match(r"^/api/net/threat$", path):
            # ?host=example.com[&ip=1.2.3.4]
            q = urllib.parse.parse_qs(parsed.query)
            host = (q.get("host") or [""])[0]
            ip = (q.get("ip") or [None])[0]
            return self._send_json(sandbox_threat.check(host, ip))
        if re.match(r"^/api/net/url-check$", path):
            # ?url=http://example.com:8080/path  -> URL 沙箱异常检测
            q = urllib.parse.parse_qs(parsed.query)
            url = (q.get("url") or [""])[0]
            return self._send_json(sandbox_threat.check_url(url))
        if path == "/api/honeypot/audit":
            # 蜜罐审计汇总：按策略/按 PID 统计 + 最近事件 + 升级告警
            return self._send_json(sandbox_honeypot.get_honeypot().get_audit())
        if path == "/api/honeypot/decoys":
            # 诱饵清单（供前端展示陷阱类型与签名）
            return self._send_json({
                "decoy_root": str(sandbox_honeypot.DECOY_ROOT),
                "event_log": str(sandbox_honeypot.EVENT_LOG_DEFAULT),
                "decoys": sandbox_honeypot.list_decoys(),
            })
        if path == "/api/providers":
            cfg = load_config()
            return self._send_json([
                {"id": p.id, "name": p.name, "type": p.type, "models": p.models}
                for p in cfg.providers
            ])
        if path == "/view":
            # 极简 Markdown 阅读器：只展示大模型实际回答，不含任何其它 UI
            return self._serve_static("/view.html")
        if path == "/api/last":
            # 返回最近一次由脚本推送的大模型回答（供 /view 阅读器展示）
            try:
                d = json.loads(LAST_ANSWER_FILE.read_text(encoding="utf-8"))
            except Exception:
                d = {"markdown": "", "updated_at": 0}
            return self._send_json(d)
        if path == "/api/lang-stats":
            # 返回长时间语言包加载计数（跨会话持久化在 lang_stats.json）
            try:
                d = json.loads(LANG_STATS_FILE.read_text(encoding="utf-8"))
            except Exception:
                d = {}
            return self._send_json(d)
        if path == "/api/emoji-stats":
            # 返回 7 天滑动窗口的 emoji 使用统计 + 命中率 + 升舱建议
            d = _prune_emoji_stats(_load_emoji_stats())
            try:
                EMOJI_STATS_FILE.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass
            return self._send_json(_emoji_summary(d))
        if path == "/api/emoji-expand":
            # 手动触发：将 7 天内达阈值的非常见 emoji 升入 common 集合
            return self._send_json(_emoji_expand_now())
        if path == "/api/conversations":
            return self._send_json(storage.list_conversations())
        m = re.match(r"^/api/conversations/([\w-]+)$", path)
        if m:
            conv = storage.get_conversation(m.group(1))
            if conv is None:
                return self._send_json({"error": "not found"}, 404)
            return self._send_json(json.loads(conv.model_dump_json()))
        if path.startswith("/uploads/"):
            fname = path[len("/uploads/"):]
            f = (UPLOAD_DIR / fname).resolve()
            if str(f).startswith(str(UPLOAD_DIR.resolve())) and f.is_file():
                ctype, _ = mimetypes.guess_type(str(f))
                self.send_response(200)
                self.send_header("Content-Type", ctype or "application/octet-stream")
                self.send_header("Content-Length", str(f.stat().st_size))
                self.end_headers()
                self.wfile.write(f.read_bytes())
                return
            return self.send_error(404)
        if path.startswith("/api/"):
            return self._send_json({"error": "unknown endpoint"}, 404)
        return self._serve_static(path)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        body = self._read_body()
        if path == "/api/run":
            if not SANDBOX_ENABLED:
                return self._send_json(
                    {"error": "沙箱未启用。请以 --sandbox 参数重启 web.py，或设置环境变量 ENABLE_SANDBOX=1。"},
                    403,
                )
            try:
                data = json.loads(self._decode_body(body))
            except Exception as e:
                return self._send_json({"error": str(e)}, 400)
            lang = (data.get("lang") or "").lower()
            code = data.get("code") or ""
            if lang not in ("python", "node", "bash"):
                return self._send_json({"error": "不支持的语言（仅 python / node / bash）"}, 400)
            if not code.strip():
                return self._send_json({"output": "", "error": "", "exitCode": 0})
            result = sandbox_run.run_code_isolated(
                lang, code, timeout=SANDBOX_TIMEOUT, proxy_port=SANDBOX_PROXY_PORT)
            # 附带 AST 预分析（执行后回看，便于审计）
            try:
                result["analysis"] = sandbox_ast.analyze(lang, code)
            except Exception:
                pass
            return self._send_json(result)
        if path == "/api/net/decision":
            itc = sandbox_net.get_interceptor()
            if not itc:
                return self._send_json({"error": "沙箱网络拦截未启用"}, 400)
            try:
                data = json.loads(self._decode_body(body))
            except Exception as e:
                return self._send_json({"error": str(e)}, 400)
            req_id = data.get("id")
            verdict = data.get("verdict")
            if verdict not in ("allow_once", "allow_session", "allow_permanent"):
                return self._send_json({"error": "verdict 必须为 allow_once/allow_session/allow_permanent"}, 400)
            return self._send_json(itc.decide(req_id, verdict))
        if path == "/api/net/quota":
            itc = sandbox_net.get_interceptor()
            if not itc:
                return self._send_json({"error": "沙箱网络拦截未启用"}, 400)
            try:
                data = json.loads(self._decode_body(body))
                limit = int(data.get("limit", itc.quota.limit))
            except Exception as e:
                return self._send_json({"error": str(e)}, 400)
            return self._send_json(itc.set_quota(limit))
        if path == "/api/honeypot/deploy":
            # 重新部署（刷新）诱饵陷阱文件
            try:
                counts = sandbox_honeypot.deploy_decoys()
            except Exception as e:  # noqa
                return self._send_json({"ok": False, "error": str(e)}, 500)
            return self._send_json({"ok": True, **counts})
        if path == "/api/honeypot/ack":
            # 确认策略二升级告警：终止进程 + 该外传目标进永久黑名单。
            # 关联的网络代理待审请求（req_id 存于 alert）走 decide(deny_permanent)：
            # 写黑名单 + 唤醒 + HoneypotKill(pid)；再标记 alert 已确认并记录事件。
            try:
                data = json.loads(self._decode_body(body))
            except Exception as e:
                return self._send_json({"error": str(e)}, 400)
            alert_id = data.get("id")
            if not alert_id:
                return self._send_json({"error": "缺少 id"}, 400)
            hp = sandbox_honeypot.get_honeypot()
            alert = next((a for a in hp.alerts if a["id"] == alert_id and not a["ack"]), None)
            if not alert:
                return self._send_json({"ok": False, "error": "告警不存在或已确认"})
            deny_res = None
            itc2 = sandbox_net.get_interceptor()
            req_id = alert.get("req_id")
            if itc2 is not None and req_id:
                # 走既有裁决通道：deny_permanent -> 黑名单 + 唤醒 + 终止进程
                deny_res = itc2.decide(req_id, "deny_permanent")
            ack_res = hp.ack_alert(alert_id)  # 标记已确认 + 记录事件 + 终止进程（兜底）
            return self._send_json({"ok": True, "ack": ack_res, "deny": deny_res})
        if path == "/api/sandbox/analyze":
            try:
                data = json.loads(self._decode_body(body))
            except Exception as e:
                return self._send_json({"error": str(e)}, 400)
            lang = (data.get("lang") or "python").lower()
            code = data.get("code") or ""
            return self._send_json(sandbox_ast.analyze(lang, code))
        if path == "/api/config":
            try:
                incoming = json.loads(self._decode_body(body))
            except Exception as e:
                return self._send_json({"error": str(e)}, 400)
            try:
                cfg = _apply_config_incoming(incoming)
                save_config(cfg)
            except Exception as e:
                return self._send_json({"error": str(e)}, 400)
            return self._send_json(_mask_config(load_config()))
        if path == "/api/conversations":
            conv = storage.create_conversation()
            return self._send_json({"id": conv.id, "title": conv.title})
        if path == "/api/chat/stream":
            return self._handle_stream(body)
        if path == "/api/upload":
            try:
                data = json.loads(self._decode_body(body))
                name = os.path.basename(data.get("name", "upload.png"))
                raw = data.get("data", "")
                if raw.startswith("data:"):
                    raw = raw.split(",", 1)[1]
                b64 = re.sub(r"\s+", "", raw)
                blob = __import__("base64").b64decode(b64)
                # 简单类型校验
                if not name.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
                    name += ".png"
                save_path = UPLOAD_DIR / name
                # 避免覆盖：加随机后缀
                if save_path.exists():
                    stem, ext = os.path.splitext(name)
                    name = f"{stem}_{os.urandom(3).hex()}{ext}"
                    save_path = UPLOAD_DIR / name
                save_path.write_bytes(blob)
                return self._send_json({"url": f"/uploads/{name}"})
            except Exception as e:
                return self._send_json({"error": str(e)}, 400)
        if path == "/api/show":
            # 脚本把大模型实际回答推送到这里，供 /view 阅读器展示
            try:
                data = json.loads(self._decode_body(body))
                md = data.get("markdown") or data.get("content") or ""
                LAST_ANSWER_FILE.write_text(
                    json.dumps({"markdown": md, "updated_at": time.time()}, ensure_ascii=False),
                    encoding="utf-8",
                )
                return self._send_json({"ok": True, "length": len(md)})
            except Exception as e:
                return self._send_json({"error": str(e)}, 400)
        if path == "/api/lang-stats":
            # 接收前端增量 {increments:{name:delta}}，累加到 lang_stats.json 后返回最新全量
            try:
                payload = json.loads(self._decode_body(body))
                inc = payload.get("increments", {}) if isinstance(payload, dict) else {}
            except Exception as e:
                return self._send_json({"error": str(e)}, 400)
            if not isinstance(inc, dict):
                return self._send_json({"error": "increments must be object"}, 400)
            try:
                try:
                    cur = json.loads(LANG_STATS_FILE.read_text(encoding="utf-8"))
                except Exception:
                    cur = {}
                if not isinstance(cur, dict):
                    cur = {}
                for k, v in inc.items():
                    if isinstance(v, int):
                        cur[k] = (cur.get(k, 0) if isinstance(cur.get(k, 0), int) else 0) + v
                LANG_STATS_FILE.write_text(json.dumps(cur, ensure_ascii=False), encoding="utf-8")
                return self._send_json(cur)
            except Exception as e:
                return self._send_json({"error": str(e)}, 400)
        if path == "/api/emoji-stats":
            # 接收前端增量 {increments:{name:delta}}，按当日分桶累加（7天滑动）
            try:
                payload = json.loads(self._decode_body(body))
                inc = payload.get("increments", {}) if isinstance(payload, dict) else {}
            except Exception as e:
                return self._send_json({"error": str(e)}, 400)
            if not isinstance(inc, dict):
                return self._send_json({"error": "increments must be object"}, 400)
            try:
                d = _load_emoji_stats()
                d = _prune_emoji_stats(d)
                today = _date_key()
                bucket = d.setdefault("by_day", {}).setdefault(today, {})
                for k, v in inc.items():
                    if isinstance(v, int):
                        bucket[k] = (bucket.get(k, 0) if isinstance(bucket.get(k, 0), int) else 0) + v
                EMOJI_STATS_FILE.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
                # 自动升舱：有达阈值的非常见 emoji 且今日尚未升舱，则重写 common
                summary = _emoji_summary(d)
                if summary["suggestions"] and d.get("last_expand") != today:
                    added = _expand_common(summary["suggestions"])
                    if added:
                        d = _load_emoji_stats()
                        d["last_expand"] = today
                        EMOJI_STATS_FILE.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
                        summary = _emoji_summary(d)
                return self._send_json(summary)
            except Exception as e:
                return self._send_json({"error": str(e)}, 400)
        if path == "/api/emoji-expand":
            # 手动触发：将 7 天内达阈值的非常见 emoji 升入 common 集合
            return self._send_json(_emoji_expand_now())
        return self._send_json({"error": "unknown endpoint"}, 404)

    def do_DELETE(self):
        m = re.match(r"^/api/conversations/([\w-]+)$", self.path)
        if m:
            ok = storage.delete_conversation(m.group(1))
            return self._send_json({"deleted": ok})
        return self._send_json({"error": "unknown endpoint"}, 404)

    # ---------- SSE 流式 ----------
    def _handle_stream(self, body: bytes):
        try:
            payload = json.loads(self._decode_body(body))
        except Exception as e:
            err = f"data: {json.dumps({'type':'error','message':str(e)})}\n\n".encode("utf-8")
            self.send_response(400)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Content-Length", str(len(err)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(err)
            return
        req = ChatRequest.model_validate(payload)

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        self.wfile.flush()

        async def _run():
            async for ev in __import__("backend.chat", fromlist=["run_chat"]).run_chat(req):
                line = "data: " + json.dumps(ev, ensure_ascii=False) + "\n\n"
                try:
                    self.wfile.write(line.encode("utf-8"))
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    break

        try:
            asyncio.run(_run())
        except Exception as e:
            try:
                self.wfile.write(
                    f"data: {json.dumps({'type':'error','message':str(e)})}\n\n".encode()
                )
                self.wfile.flush()
            except Exception:
                pass
        # SSE 结束标记
        try:
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except Exception:
            pass

    def log_message(self, fmt, *args):
        pass  # 静默


def main():
    ap = argparse.ArgumentParser(description="AI 对话 WebUI 服务端")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--sandbox", action="store_true",
                    help="启用代码沙箱执行端点 /api/run（会真实执行 python/node/bash，有命令执行风险，仅限本机可信环境）")
    args = ap.parse_args()
    global SANDBOX_ENABLED
    SANDBOX_ENABLED = bool(args.sandbox) or (os.environ.get("ENABLE_SANDBOX") == "1")
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"AI 对话 WebUI 已启动： http://{args.host}:{args.port}")
    if SANDBOX_ENABLED:
        print("⚠️  代码沙箱已启用：/api/run 将真实执行 python/node/bash 代码（命令执行风险，仅限本机可信环境）")
        itc = sandbox_net.start_interceptor(SANDBOX_PROXY_PORT, sandbox_net.DEFAULT_QUOTA,
                                            SANDBOX_ISOLATE_USER)
        fw = itc.status().get("firewall") or {}
        print("🔒 透明网络拦截代理已启动：127.0.0.1:%d（默认断网，需用户授权）" % SANDBOX_PROXY_PORT)
        if fw.get("applied"):
            print("   防火墙默认拒绝已生效（%s）" % ", ".join(fw.get("rules", [])))
        elif fw.get("reason"):
            print("   [提示] 防火墙未生效：%s（代理拦截仍工作，建议以管理员运行并指定 SANDBOX_USER）" % fw["reason"])
        # 诱饵蜜罐：初始化单例 + 部署高仿真陷阱文件（沙箱子进程经 shim 命中四策略）
        sandbox_honeypot.set_event_log(sandbox_honeypot.EVENT_LOG_DEFAULT)
        sandbox_honeypot.get_honeypot(sandbox_honeypot.EVENT_LOG_DEFAULT)  # 预热单例
        counts = sandbox_honeypot.deploy_decoys()
        print("🍯 诱饵蜜罐已部署：%d 个陷阱文件 @ %s（策略一/二/三/四 全开）"
              % (counts.get("files", 0), sandbox_honeypot.DECOY_ROOT))
        import atexit
        atexit.register(itc.stop)
    print("按 Ctrl+C 停止。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WebUI 开发服务器（Python 版）

与 core/devserver.js 行为一致：
  - 静态托管 webui 目录（ES Module 必须走 http，浏览器不允许 file:// 加载模块）
  - 提供 /__hmr 接口：返回 pages/ 下各模块与 index.html 的 mtime，供前端热重载

为什么要自己写而不用 python -m http.server：
  Python 自带的 mimetypes 表对这个项目是错的 —— .woff2/.woff/.ttf 认不出来
  （会以 application/octet-stream 下发），.mjs 会被当成 text/plain。
  字体和模块的 MIME 必须准确。

用法：
  python core/devserver.py [端口] [--no-browser]
  端口省略时从 5173 起自动找空闲端口。
"""

import json
import mimetypes
import os
import socket
import sys
import threading
import time
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

# ---------------------------------------------------------------- 路径

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGES_DIR = os.path.join(ROOT, "pages")

# ---------------------------------------------------------------- MIME

# 显式指定，覆盖 Python 默认表里错误/缺失的项
TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".map": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".ttf": "font/ttf",
    ".otf": "font/otf",
    ".txt": "text/plain; charset=utf-8",
    ".wasm": "application/wasm",
}
for _ext, _mime in TYPES.items():
    mimetypes.add_type(_mime.split(";")[0], _ext)

# ---------------------------------------------------------------- HMR

def collect_mtimes():
    """收集 pages/ 下所有模块文件 + index.html 的修改时间（毫秒）"""
    out = {}
    try:
        for name in os.listdir(PAGES_DIR):
            if not name.endswith((".js", ".mjs", ".css")):
                continue
            try:
                full = os.path.join(PAGES_DIR, name)
                out[os.path.splitext(name)[0]] = int(os.path.getmtime(full) * 1000)
            except OSError:
                pass
    except OSError:
        pass
    try:
        out["index.html"] = int(os.path.getmtime(os.path.join(ROOT, "index.html")) * 1000)
    except OSError:
        pass
    return out

# ---------------------------------------------------------------- 处理器

class Handler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def guess_type(self, path):
        ext = os.path.splitext(str(path))[1].lower()
        if ext in TYPES:
            return TYPES[ext]
        return super().guess_type(path)

    def end_headers(self):
        # 开发期一律不缓存，免得改完刷新还是旧的
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        if self.path.split("?")[0] == "/__hmr":
            body = json.dumps(
                {"modules": collect_mtimes(), "ts": int(time.time() * 1000)},
                ensure_ascii=False,
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def log_message(self, fmt, *args):
        # 只报错误，正常请求不刷屏
        try:
            code = args[1]
        except IndexError:
            code = ""
        if isinstance(code, str) and code[:1] in ("4", "5"):
            sys.stdout.write("  [%s] %s\n" % (code, self.path))
            sys.stdout.flush()

# ---------------------------------------------------------------- 端口

def pick_port(start):
    """从 start 起找一个能绑上的端口"""
    for port in range(start, start + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return 0

# ---------------------------------------------------------------- 主流程

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a for a in sys.argv[1:] if a.startswith("--")]
    want = int(args[0]) if args and args[0].isdigit() else 5173

    port = pick_port(want)
    if not port:
        print("\n  [错误] %d 起的 50 个端口都被占用了。\n" % want)
        return 1
    if port != want:
        print("\n  (端口 %d 被占用，改用 %d)" % (want, port))

    url = "http://localhost:%d/" % port
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)

    print("")
    print("  ┌────────────────────────────────────────────┐")
    print("  │   WebUI 开发服务器已启动                    │")
    print("  └────────────────────────────────────────────┘")
    print("")
    print("     地址：%s" % url)
    print("     根目录：%s" % ROOT)
    print("")
    print("     热重载监控 pages/ —— 改完模块保存，页面自动重载该模块。")
    print("     关闭本窗口或按 Ctrl+C 即停止服务。")
    print("")

    if "--no-browser" not in flags:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  已停止。\n")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P.A.L.M 前端截图工具（基于 Edge 无头模式）。

用途：把本地 HTML 真实渲染成 PNG，用于排查排版 / 错位 / 响应式问题。
依赖：本机已安装 Microsoft Edge（默认路径见 EDGE）。

用法：
  python shoot_html.py <html文件> <输出目录> [视图...] [--size WxH]

视图写法：
  cmd / tasks / memory / role / auto / voice / guard / evolve / settings
  深色变体：dark=cmd  （等价于 ?theme=dark#cmd）
  尺寸：--size 1000x800

示例：
  python shoot_html.py ../frontend/palm-console.html ./shots cmd tasks guard dark=cmd --size 1440x900
"""
import os
import sys
import subprocess
import urllib.request

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
if not os.path.exists(EDGE):
    EDGE = r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"


def to_file_url(path: str, theme_dark: bool, view: str) -> str:
    abs_path = os.path.abspath(path).replace("\\", "/")
    url = "file:///" + abs_path
    query = "?theme=dark" if theme_dark else ""
    hash_part = "#" + view if view else ""
    return url + query + hash_part


def shoot(html_file: str, out_dir: str, view: str, width: int, height: int) -> str:
    theme_dark = view.startswith("dark=")
    real_view = view.split("=", 1)[1] if theme_dark else view
    url = to_file_url(html_file, theme_dark, real_view)

    name = ("dark_" if theme_dark else "") + (real_view or "home") + f"_{width}x{height}.png"
    out_dir_abs = os.path.abspath(out_dir)
    os.makedirs(out_dir_abs, exist_ok=True)
    out_path = os.path.join(out_dir_abs, name)

    cmd = [
        EDGE,
        "--headless=new",
        "--no-sandbox",
        "--disable-gpu",
        "--hide-scrollbars",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        f"--window-size={width},{height}",
        "--virtual-time-budget=2500",
        f"--screenshot={out_path}",
        url,
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
    return out_path


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        print(__doc__)
        sys.exit(1)

    html_file = args[0]
    out_dir = args[1]
    rest = args[2:]

    size = (1440, 900)
    views = []
    i = 0
    while i < len(rest):
        a = rest[i]
        if a.startswith("--size"):
            if "=" in a:
                w, h = a.split("=", 1)[1].split("x")
            else:
                i += 1
                w, h = rest[i].split("x")
            size = (int(w), int(h))
        else:
            views.append(a)
        i += 1
    if not views:
        views = ["cmd"]

    os.makedirs(out_dir, exist_ok=True)
    print(f"截图目标：{html_file}")
    print(f"视口：{size[0]}x{size[1]}  输出目录：{out_dir}")
    for v in views:
        try:
            p = shoot(html_file, out_dir, v, size[0], size[1])
            print(f"  ✓ {v:12s} -> {p}")
        except Exception as e:
            print(f"  ✗ {v:12s} 失败：{e}")


if __name__ == "__main__":
    main()

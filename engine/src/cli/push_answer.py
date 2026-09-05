"""把脚本获得的大模型回答推送到 Web 阅读器（/view）。

用法：
    python push_answer.py answer.md                 # 推送一个 .md 文件
    python push_answer.py answer.md --host 127.0.0.1 --port 8080
    cat answer.md | python push_answer.py -          # 从标准输入读取
    python push_answer.py - --host 127.0.0.1 --port 8080 < answer.md

阅读器页面：http://127.0.0.1:8080/view
（该页面只渲染 Markdown，无任何其它 UI 或链接。）
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request


def main():
    ap = argparse.ArgumentParser(description="推送大模型回答到 Web 阅读器")
    ap.add_argument("file", help="Markdown 文件路径，或用 - 表示从标准输入读取")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()

    if args.file == "-":
        md = sys.stdin.read()
    else:
        md = open(args.file, encoding="utf-8").read()

    url = f"http://{args.host}:{args.port}/api/show"
    body = json.dumps({"markdown": md}).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            resp = json.loads(r.read().decode("utf-8"))
        print(f"已推送 {resp.get('length', len(md))} 字到阅读器： "
              f"http://{args.host}:{args.port}/view")
    except Exception as e:
        print(f"推送失败：{e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""AI 对话组件真实 API 验证脚本（无头）。

通过 POST /api/chat/stream（SSE）调用真实大模型，收集完整 Markdown 回答，
校验每条用例对目标渲染特性的覆盖率，并度量 TTFT / 延迟 / token。

仅依赖标准库（urllib / json / re / time / argparse），可在本项目受管 Python 下直接运行：

    python test_runner.py                      # 跑全部 14 条（默认 zhipu / glm-4-plus）
    python test_runner.py --only p01,p05,p09   # 只跑指定 id
    python test_runner.py --model glm-4.5-air  # 切换模型
    python test_runner.py --max-tokens 1000    # 限制每条输出长度
    python test_runner.py --base http://127.0.0.1:9000

注意：API Key 始终留在后端（web.py 代理），本脚本只与本地 web.py 通信，不接触密钥。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent  # 项目根
PROMPTS_FILE = ROOT / "frontend" / "prompts.json"
RESULTS_FILE = ROOT / "test_results.json"


# ---------------------------------------------------------------------------
# SSE 流式客户端
# ---------------------------------------------------------------------------
def stream_chat(base: str, provider: str, model: str, content: str,
                max_tokens: int, timeout: int = 120):
    """POST /api/chat/stream，逐事件回调，返回 (full_markdown, usage, ttft, latency, error)。"""
    url = base.rstrip("/") + "/api/chat/stream"
    payload = json.dumps({
        "provider": provider,
        "model": model,
        "content": content,
        # 关闭思维链，让回答直接以 content 形式流式下发（渲染验证只需要最终答案 markdown）
        "parameters": {"temperature": 0.7, "max_tokens": max_tokens,
                       "extra_body": {"thinking": {"type": "disabled"}}},
    }).encode("utf-8")

    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "text/event-stream")

    full = []
    usage = {}
    ttft = None
    latency = None
    error = None
    t0 = time.time()

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace")
                if not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    break
                if not data:
                    continue
                try:
                    ev = json.loads(data)
                except json.JSONDecodeError:
                    continue
                etype = ev.get("type")
                if etype == "token":
                    if ttft is None:
                        ttft = time.time() - t0
                    full.append(ev.get("content", ""))
                elif etype == "reasoning":
                    # 思维链不计入正文 markdown（避免污染渲染校验）
                    pass
                elif etype == "done":
                    usage = ev.get("usage", {}) or {}
                elif etype == "error":
                    error = ev.get("message", "unknown error")
                elif etype == "meta":
                    pass
            latency = time.time() - t0
    except urllib.error.HTTPError as e:
        error = "HTTP %s: %s" % (e.code, e.read().decode("utf-8", "replace")[:300])
    except Exception as e:  # noqa: BLE001
        error = "请求失败: %s" % e

    return "".join(full), usage, ttft, latency, error


# ---------------------------------------------------------------------------
# 渲染特性覆盖率
# ---------------------------------------------------------------------------
def estimate_tokens(text: str) -> int:
    """与前端组件一致的启发式 token 估算（CJK≈1，英文词≈1.3，标点≈0.3）。"""
    cjk = len(re.findall(r"[一-鿿]", text))
    words = len(re.findall(r"[A-Za-z0-9]+", text))
    punct = len(re.findall(r"[^\sA-Za-z0-9一-鿿]", text))
    return int(round(cjk * 1.0 + words * 1.3 + punct * 0.3))


def check_coverage(markdown: str, markers: list) -> dict:
    """返回 {matched, total, missing, hit_rate}。"""
    total = len(markers)
    if total == 0:
        return {"matched": 0, "total": 0, "missing": [], "hit_rate": 1.0}
    missing = []
    matched = 0
    for m in markers:
        try:
            if re.search(m, markdown, re.MULTILINE):
                matched += 1
            else:
                missing.append(m)
        except re.error:
            # 正则无效时按"未匹配"处理，但记录
            missing.append(m + " (bad-regex)")
    return {
        "matched": matched,
        "total": total,
        "missing": missing,
        "hit_rate": matched / total,
    }


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="AI 组件真实 API 验证脚本")
    ap.add_argument("--base", default="http://127.0.0.1:8080", help="web.py 地址")
    ap.add_argument("--provider", default="zhipu")
    ap.add_argument("--model", default="glm-4.5-air")
    ap.add_argument("--max-tokens", type=int, default=1500)
    ap.add_argument("--only", default="", help="只跑指定 id，逗号分隔，如 p01,p05")
    ap.add_argument("--out", default=str(RESULTS_FILE), help="结果 JSON 输出路径")
    ap.add_argument("--no-stream-ok", action="store_true", help="允许无 SSE（一般不需）")
    args = ap.parse_args()

    if not PROMPTS_FILE.exists():
        print("✗ 找不到 prompts 文件:", PROMPTS_FILE, file=sys.stderr)
        sys.exit(1)

    data = json.loads(PROMPTS_FILE.read_text(encoding="utf-8"))
    prompts = data["prompts"]

    only = set(x.strip() for x in args.only.split(",") if x.strip())
    if only:
        prompts = [p for p in prompts if p["id"] in only]

    print("=" * 72)
    print("AI 组件真实 API 验证  ·  模型 %s/%s  ·  用例 %d 条  ·  最大输出 %d tokens"
          % (args.provider, args.model, len(prompts), args.max_tokens))
    print("=" * 72)

    results = []
    total_hit = 0
    total_markers = 0
    ok_count = 0

    for i, p in enumerate(prompts, 1):
        print("\n[%d/%d] %s — %s  (特性: %s)"
              % (i, len(prompts), p["id"], p["title"], "/".join(p.get("features", []))))
        md, usage, ttft, latency, error = stream_chat(
            args.base, args.provider, args.model, p["prompt"], args.max_tokens)

        cov = check_coverage(md, p.get("markers", []))
        tok = usage.get("completion_tokens") or estimate_tokens(md)

        if error:
            print("   ✗ 错误: %s" % error)
            status = "error"
        else:
            status = "ok"
            ok_count += 1
            total_hit += cov["matched"]
            total_markers += cov["total"]
            print("   ✓ 长度 %d 字符 · token≈%s · TTFT %.2fs · 延迟 %.2fs · 覆盖 %d/%d (%.0f%%)"
                  % (len(md), tok, ttft or 0, latency or 0,
                     cov["matched"], cov["total"], cov["hit_rate"] * 100))
            if cov["missing"]:
                print("   未命中: %s" % ", ".join(cov["missing"][:6]))

        results.append({
            "id": p["id"],
            "title": p["title"],
            "category": p.get("category", ""),
            "status": status,
            "error": error,
            "chars": len(md),
            "tokens": tok,
            "ttft": round(ttft, 3) if ttft else None,
            "latency": round(latency, 3) if latency else None,
            "usage": usage,
            "coverage": cov,
            "markdown": md,
        })

    # ---- 汇总 ----
    overall = (total_hit / total_markers) if total_markers else 1.0
    print("\n" + "=" * 72)
    print("汇总: 成功 %d/%d · 渲染特性总覆盖率 %d/%d (%.1f%%)"
          % (ok_count, len(results), total_hit, total_markers, overall * 100))
    print("=" * 72)

    out = {
        "provider": args.provider,
        "model": args.model,
        "max_tokens": args.max_tokens,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "overall_coverage": round(overall, 4),
        "success": ok_count,
        "total": len(results),
        "results": results,
    }
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("结果已写入:", args.out)


if __name__ == "__main__":
    main()

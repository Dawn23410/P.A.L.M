#!/usr/bin/env python3
"""单客户端计时器：对同一个 mock 上游跑 N 次，落盘原始样本 + 统计量。

用法
----
    python3 harness.py --client palm_kernel --base-url http://127.0.0.1:18080/v1 \\
        --model bench-model --iters 200 --warmup 20 --out results/palm_kernel.json

口径（与报告一致，别改）
------------------------
- **一次调用** = 把整条流读完（含收尾帧）的墙钟；不是"首字节"也不是"发出即返回"
- `warmup` 次不计入统计：连接池、JIT、DNS 都得先热掉
- 顺序单发（并发 1）：网关差异本就在毫秒级，并发一来排队噪声就把信号埋了
- TTFT 单列：只对流式有意义，且是"首个含 content/token 的帧"到达时间
- 记 `--server-stats` 可额外取 mock 侧处理耗时，用于把服务端时间从墙钟里减出去
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from pathlib import Path

# litellm 导入时会联网拉 model cost map —— 不设这个会卡在 DNS 上（离线/受限网络下尤其明显）
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

sys.path.insert(0, str(Path(__file__).resolve().parent))
# 内核本体在仓库根（bench/gateway → bench → 内核根），不在本目录内
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from clients import build  # noqa: E402


def _pct(samples: list[float], q: float) -> float:
    """线性插值分位数（样本量小的时候比最近秩法稳）。"""
    if not samples:
        return 0.0
    ordered = sorted(samples)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q / 100.0
    lo, hi = int(pos), min(int(pos) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def summarize(samples: list[float]) -> dict:
    if not samples:
        return {}
    return {
        "n": len(samples),
        "mean": round(statistics.fmean(samples), 3),
        "p50": round(_pct(samples, 50), 3),
        "p90": round(_pct(samples, 90), 3),
        "p99": round(_pct(samples, 99), 3),
        "min": round(min(samples), 3),
        "max": round(max(samples), 3),
        "stdev": round(statistics.pstdev(samples), 3),
    }


async def run(args) -> dict:
    headers = {}
    for item in args.header or []:
        if ":" in item:
            k, _, v = item.partition(":")
            headers[k.strip()] = v.strip()
    client = build(args.client, args.base_url, args.model, args.max_tokens,
                   headers=headers or None)
    await client.start()

    for _ in range(args.warmup):
        await client.call(args.stream)

    walls: list[float] = []
    ttfts: list[float] = []
    errors = 0
    for _ in range(args.iters):
        t0 = time.perf_counter()
        first: list[float] = []
        try:
            await client.call(args.stream, on_first=lambda: first.append(
                (time.perf_counter() - t0) * 1000))
        except Exception as exc:      # noqa: BLE001  失败也要记，不能悄悄丢样本
            errors += 1
            if errors <= 3:
                print(f"  [err] {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        walls.append((time.perf_counter() - t0) * 1000)
        if first:
            ttfts.append(first[0])

    await client.aclose()

    server = None
    if args.server_stats:
        try:
            import httpx

            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(args.server_stats)
                server = summarize(r.json().get("server_ms") or [])
        except Exception as exc:      # noqa: BLE001
            print(f"  [warn] 取服务端样本失败：{exc}", file=sys.stderr)

    return {
        "label": args.label or args.client,
        "client": args.client,
        "base_url": args.base_url,
        "model": args.model,
        "stream": bool(args.stream),
        "iters": args.iters,
        "warmup": args.warmup,
        "errors": errors,
        "wall_ms": summarize(walls),
        "ttft_ms": summarize(ttfts),
        "server_ms": server,
        "samples_ms": [round(x, 3) for x in walls],
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--client", required=True)
    p.add_argument("--base-url", required=True)
    p.add_argument("--model", default="bench-model")
    p.add_argument("--iters", type=int, default=200)
    p.add_argument("--warmup", type=int, default=20)
    p.add_argument("--max-tokens", type=int, default=16)
    p.add_argument("--label", default="")
    p.add_argument("--out", default="")
    p.add_argument("--server-stats", default="",
                   help="mock 的 /_stats 地址，用于取服务端侧处理耗时")
    p.add_argument("--header", action="append", default=[],
                   metavar="K:V", help="附加请求头（自托管网关靠头路由时用）")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--stream", dest="stream", action="store_true", default=True)
    g.add_argument("--no-stream", dest="stream", action="store_false")
    args = p.parse_args()

    result = asyncio.run(run(args))
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
    w = result["wall_ms"]
    print(f"{result['label']:<16} n={w.get('n', 0)} "
          f"mean={w.get('mean', 0):>8.3f}ms p50={w.get('p50', 0):>8.3f} "
          f"p90={w.get('p90', 0):>8.3f} p99={w.get('p99', 0):>8.3f} "
          f"err={result['errors']}")


if __name__ == "__main__":
    main()

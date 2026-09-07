# -*- coding: utf-8 -*-
"""P.A.L.M 模型 API 拉起脚本。

档位独立端口（规范：localhost ≥10000）:
    full     -> 10000
    balanced -> 10001
    lite     -> 10002

自定义语料（给用户用自己语料库的机会）:
    --corpus-dir <目录>   指向含 mengyao_hq_part*.jsonl 的目录
    --data-dir <目录>     向量索引缓存目录（缺省随引擎）

用法:
    python start_server.py --tier balanced --corpus-dir "D:/我的语料"
    python start_server.py                 # full 档, 端口 10000, 内置语料
"""
from __future__ import annotations

import argparse
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="梦瑶本地对话引擎 · P.A.L.M 模型 API")
    ap.add_argument("--tier", choices=["full", "balanced", "lite"],
                    default="full", help="本实例档位(默认 full)")
    ap.add_argument("--host", default="127.0.0.1", help="监听地址")
    ap.add_argument("--port", type=int, default=None,
                    help="监听端口(缺省按档位: full=10000/balanced=10001/lite=10002)")
    ap.add_argument("--corpus-dir", default=None,
                    help="自定义语料目录(含 mengyao_hq_part*.jsonl)")
    ap.add_argument("--data-dir", default=None, help="索引缓存目录(缺省随引擎)")
    ap.add_argument("--preload", action="store_true",
                    help="启动时立即加载引擎(失败时服务照常起, 心跳报 error+原因)")
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    if args.corpus_dir:
        os.environ["PALM_CORPUS_DIR"] = os.path.abspath(args.corpus_dir)
    if args.data_dir:
        os.environ["PALM_DATA_DIR"] = os.path.abspath(args.data_dir)
    # 必须在 import server 之前设好环境变量（server 在导入时读取）
    from local_reply.server import TIER_PORTS, create_app, preload_engine  # noqa: E402

    port = args.port if args.port is not None else TIER_PORTS[args.tier]
    if port < 10000:
        raise SystemExit("接口规范: 端口必须 >= 10000")
    app = create_app(default_tier=args.tier)
    if args.preload:
        ok, err = preload_engine(args.tier)
        if ok:
            print(f"[palm-models-api] 引擎预热完成 (tier={args.tier}, "
                  f"corpus={os.environ.get('PALM_CORPUS_DIR', '内置')})")
        else:
            print(f"[palm-models-api] 引擎预热失败, 服务仍启动: {err}")
    print(f"[palm-models-api] http://{args.host}:{port}"
          f"/p.a.l.m/models/api/heartbeat  (tier={args.tier})")
    import uvicorn  # noqa: E402
    uvicorn.run(app, host=args.host, port=port, log_level="info")


if __name__ == "__main__":
    main()

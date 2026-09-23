"""FastAPI 生产部署入口（与 palm-chat 的 FastAPI 栈统一的 HTTP 服务层）。

SSE 事件 = meta / reasoning / token / done / error，data: [DONE] 收尾。
（原标准库 http.server 的零依赖 WebUI 已移除，本文件是唯一的服务入口。）

端点：
  GET    /health                    存活探针（生产负载均衡必需）
  GET    /api/config                配置读取（api_key 遮罩）
  POST   /api/config                配置写入（遮罩值自动回填真实 key）
  GET    /api/conversations         会话列表
  GET    /api/conversations/{cid}   会话详情
  DELETE /api/conversations/{cid}   删除会话
  POST   /api/chat/stream           SSE 流式对话

运行：
    uvicorn palm_llm.server.api:app --host 127.0.0.1 --port 10083
    python -m palm_llm.server.api            # 等价快捷方式

端口：10083（>10000 顺次高位：GSV 10080 / Cosy 10081 / palm-chat 10082 之后）。
依赖：pip install "palm-llm[deploy]"（fastapi + uvicorn）。
"""
from __future__ import annotations

import argparse
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import storage
from .chat import prewarm_active_provider, run_chat
from .config import ensure_dirs, load_config, save_config
from .metrics import snapshot as metrics_snapshot
from .models import AppConfig, ChatRequest

ensure_dirs()

MASK = "********"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """启动时预热 active provider 连接（握手移出首次提问关键路径）。"""
    try:
        await prewarm_active_provider()
    except Exception:
        pass  # 预热尽力而为，不阻塞服务启动
    yield


app = FastAPI(title="palm-llm server", version="0.2.0", lifespan=lifespan)

# CORS：本地开发前端 + palm-chat 前端
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:10082", "http://127.0.0.1:10082",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    """存活探针：生产负载均衡 / 监控必需。"""
    return {"status": "ok", "service": "palm-llm", "version": "0.2.0"}


@app.get("/metrics")
def metrics() -> dict:
    """开销监控：请求数/错误数/耗时/per-provider/token 累计/（可选）RSS 与 CPU。"""
    return metrics_snapshot()


def _mask(cfg: AppConfig) -> dict:
    d = json.loads(cfg.model_dump_json())
    for p in d.get("providers", []):
        if p.get("api_key"):
            p["api_key"] = MASK
    return d


@app.get("/api/config")
def read_config() -> dict:
    return _mask(load_config())


class ConfigIn(BaseModel):
    config: dict


@app.post("/api/config")
def write_config(body: ConfigIn) -> dict:
    """遮罩值自动回填磁盘上的真实 key，避免前端回写把 key 冲掉。"""
    current = load_config()
    cur_keys = {p.id: p.api_key for p in current.providers}
    for p in body.config.get("providers", []):
        if p.get("api_key") == MASK:
            p["api_key"] = cur_keys.get(p["id"], "")
    save_config(AppConfig.model_validate(body.config))
    return {"ok": True}


@app.get("/api/conversations")
def list_conversations() -> list[dict]:
    return storage.list_conversations()


@app.get("/api/conversations/{cid}")
def read_conversation(cid: str) -> dict:
    conv = storage.get_conversation(cid)
    if conv is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return conv.model_dump()


@app.delete("/api/conversations/{cid}")
def delete_conversation(cid: str) -> dict:
    return {"deleted": storage.delete_conversation(cid)}


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest) -> StreamingResponse:
    """SSE 流式对话（事件契约与 web.py 一致）。"""

    async def gen():
        try:
            async for ev in run_chat(req):
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        except Exception as e:  # 错误事件化，保持 SSE 通道不中断语义
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


def main() -> None:
    ap = argparse.ArgumentParser(description="palm-llm FastAPI 服务端（生产入口）")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=10083)  # >10000 顺次高位
    args = ap.parse_args()
    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()

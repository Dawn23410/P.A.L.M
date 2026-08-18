"""models 砖块：模型供应商发现与流式生成后端。

- 模型发现：POST /api/models/discover（给定供应商与连接信息拉取模型清单）。
- 流式生成：经 capabilities 暴露 create_stream（即 provider.stream_chat），供 chat 砖在 /api/chat 内取流。
- 文件能力：暴露 is_model_file_capable / file_handling_mode，供 chat / system 经注册表取用，不跨砖 import。

自身聚合 provider.py（三协议）与 capabilities.py（文件能力表）；无跨砖调用。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from palm_sdk.net import arequest

from palm_sdk.core.logging import get_logger
from palm_sdk.security import require_api_token
from palm_sdk.bricks.base import Brick, BrickManifest, registry
from palm_sdk.schemas.chat import DiscoverRequest

logger = get_logger(__name__)
from .capabilities import file_handling_mode, is_model_file_capable
from .provider import stream_chat

router = APIRouter(prefix="/api", tags=["models"])


@router.post("/models/discover", dependencies=[Depends(require_api_token)])
async def discover_models(body: DiscoverRequest):
    """模型发现：给定供应商类型与连接信息，拉取可用模型列表。

    支持 OpenAI 兼容（GET {base_url}/models）与 Anthropic 原生（GET {base_url}/v1/models）
    两种列表协议。用于在「设置 › 模型 › 添加模型」里展示可勾选的模型清单。
    """
    base_url = body.base_url.rstrip("/")
    logger.info("模型发现请求 provider=%s", body.provider)
    if not base_url:
        raise HTTPException(status_code=400, detail="请求地址（base_url）不能为空")
    # 协议类型由前端按所选供应商自动推导（anthropic 走原生，其余走 OpenAI 兼容）。
    mode = body.mode or ("anthropic" if body.provider == "anthropic" else "openai")
    try:
        if mode == "anthropic":
            ids = await _list_anthropic(base_url, body.api_key)
        else:
            ids = await _list_openai(base_url, body.api_key)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502, detail=f"获取模型列表失败：{type(exc).__name__}: {exc}"
        ) from exc
    return {"models": [{"id": i} for i in ids]}


async def _list_openai(base_url: str, api_key: str) -> list[str]:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    # 经网卡门面转发（外网 GET，默认拒绝未授权主机）。
    resp = await arequest("GET", f"{base_url}/models", headers=headers, timeout=30.0)
    if resp.status_code != 200:
        raise RuntimeError(f"list {resp.status_code}: {resp.text[:300]}")
    model_list = resp.json()
    items = model_list.get("data") or []
    return [m["id"] for m in items if isinstance(m, dict) and "id" in m]


async def _list_anthropic(base_url: str, api_key: str) -> list[str]:
    headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
    resp = await arequest("GET", f"{base_url}/v1/models", headers=headers, timeout=30.0)
    if resp.status_code != 200:
        raise RuntimeError(f"list {resp.status_code}: {resp.text[:300]}")
    model_info = resp.json()
    items = model_info.get("models", [])
    return [m["id"] for m in items if isinstance(m, dict) and "id" in m]


brick = Brick(
    manifest=BrickManifest(
        name="models",
        title="模型供应商",
        description="模型发现（/api/models/discover）与流式生成后端（provider 三协议），经 capabilities 暴露 create_stream / 文件能力供 chat 砖取用。",
        bus_type="pcie",
    ),
    router=router,
    # 经注册表暴露能力：chat 砖经 create_stream 取流；system / chat 经文件能力判断附件处理。
    capabilities={
        "create_stream": stream_chat,
        "is_model_file_capable": is_model_file_capable,
        "file_handling_mode": file_handling_mode,
        "model_supports_files": is_model_file_capable,
    },
)
registry.register(brick)
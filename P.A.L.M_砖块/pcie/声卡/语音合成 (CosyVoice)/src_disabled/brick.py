"""cosyvoice 砖块（完整砖，进程内持有 CosyVoice2，非薄代理）。

设计立场（与 tts_sovits 的薄代理模式相反）：
- 本砖是完整砖：CosyVoice2 模型在砖进程内直接加载与推理。路由、capability、Agent
  工具都直接调用 engine，不经过任何 client/serve HTTP 代理，不依赖独立子进程。
- cosyvoice 重依赖在首次造音时懒导入（engine._load_model），未安装则 capability 降级，
  不阻断 P.A.L.M 启动；模型懒加载，避免常驻占显存。
- 侧重点仍是音色创造：产出参考音频供 GSV 经 refer_wav_path 克隆。
- 经 agent 砖块的 register_tool 能力注册 Agent 工具，避免砖块间直接互调。
"""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from palm_sdk.core.config import settings
from palm_sdk.core.logging import get_logger
from palm_sdk.security import require_api_token
from palm_sdk.bricks.base import Brick, BrickManifest, registry
from palm_sdk.permission import PermissionSpec, RiskLevel, require_permission
from .engine import create_voice, is_available, list_voices, _model_dir, _output_dir, _device
from .tool import CreateVoiceTool

logger = get_logger(__name__)
router = APIRouter(prefix="/api/cosy", tags=["cosyvoice"])


def _extract_payload(payload: dict) -> dict:
    return {
        "description": payload.get("description", ""),
        "seed_audio": payload.get("seed_audio", ""),
        "seed_text": payload.get("seed_text", ""),
        "sample_text": payload.get("sample_text", ""),
        "voice_id": payload.get("voice_id", ""),
    }


@router.post("/create_voice", dependencies=[Depends(require_api_token), Depends(require_permission("cosyvoice.create_voice"))])
async def api_create_voice(payload: dict) -> dict:
    try:
        return create_voice(**_extract_payload(payload))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("/voices", dependencies=[Depends(require_api_token)])
async def api_list_voices() -> dict:
    return {"voices": list_voices()}


@router.get("/status", dependencies=[Depends(require_api_token)])
async def api_status() -> dict:
    available = is_available()
    note = "" if available else "cosyvoice 未安装：请运行 `python plugins/cosyvoice/install.py`。"
    return {
        "available": available,
        "mode": "in-process (完整砖)",
        "model_dir": _model_dir(),
        "output_dir": _output_dir(),
        "device": _device(),
        "note": note,
    }


@router.get("/audio/{filename}", dependencies=[Depends(require_api_token)])
async def api_serve_audio(filename: str) -> Response:
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="非法文件名")
    path = os.path.join(settings.COSY_OUTPUT_DIR, filename)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="音频不存在")
    media = "audio/wav"
    with open(path, "rb") as fh:
        data = fh.read()
    return Response(content=data, media_type=media)


async def _create_voice_via_brick(description: str = "", seed_audio: str = "",
                                  seed_text: str = "", sample_text: str = "",
                                  voice_id: str = "") -> dict:
    """供其它砖块经 capability 调用：返回元数据（含 GSV 克隆所需路径与原文）。"""
    return create_voice(
        description=description,
        seed_audio=seed_audio,
        seed_text=seed_text,
        sample_text=sample_text,
        voice_id=voice_id,
    )


async def _list_voices_via_brick() -> list[dict]:
    return list_voices()


async def _is_available_via_brick() -> bool:
    return is_available()


brick = Brick(
    manifest=BrickManifest(
        name="cosyvoice",
        title="音色创造 (CosyVoice2)",
        description="基于 CosyVoice2 的音色创造砖块（完整砖，进程内持有模型，非薄代理）。"
        "用自然语言描述 + 基底参考音频，产出可克隆的参考音频（.wav + .txt），"
        "供 GSV（GPT-SoVITS）经 refer_wav_path 克隆做实时合成。",
        bus_type="pcie",
        can_accept_files=False,
        # 完整砖：模型在砖进程内直接推理，不走隔离子进程/HTTP 代理。
        isolation="inproc",
        endpoint="inproc://",
    ),
    router=router,
    capabilities={
        # 直接调用 engine，无 subprocess_spec（无独立 serve）。
        "create_voice": _create_voice_via_brick,
        "list_voices": _list_voices_via_brick,
        "is_available": _is_available_via_brick,
    },
    permissions=[
        PermissionSpec(
            key="cosyvoice.create_voice",
            title="音色创造",
            description="让助手用自然语言描述 + 基底音频创造一个新音色（参考音频落盘，供 GSV 克隆）。",
            risk=RiskLevel.LOW,
            brick="cosyvoice",
        ),
    ],
)

_agent_brick = registry.get("agent")
if _agent_brick is not None:
    register_tool = _agent_brick.capabilities.get("register_tool")
    if register_tool is not None:
        register_tool(CreateVoiceTool())
    else:
        logger.warning("agent 砖块未暴露 register_tool 能力，CreateVoiceTool 未注册。")
else:
    logger.warning("agent 砖块尚未注册，CreateVoiceTool 延后不可用；请确认 cosyvoice 在 agent 之后导入。")

registry.register(brick)
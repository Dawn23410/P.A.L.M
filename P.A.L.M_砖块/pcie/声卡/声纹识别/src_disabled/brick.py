"""声纹识别砖块：本地说话人识别（CAM++ / sherpa-onnx，独立子进程引擎）。

标准砖块模式（与 stt 一致）：推理引擎跑在砖块内独立 venv（声纹识别/.venv-speaker）
的独立子进程，主进程绝不 import sherpa_onnx。识别结果经 emit 到事件总线
（voice.speaker），供对话/记忆链路按说话人切换角色与个性化（规格 §8.3 接线点）。

独立性：权重（src/speaker_models/campplus_*.onnx）与依赖（.venv-speaker）全部内聚于
砖目录，物理复制、不软链，可独立搬运（架构铁律：重 ML 运行时隔离 + 自带依赖）。
"""
from __future__ import annotations

import atexit
import asyncio
import os
import threading

from fastapi import APIRouter, Depends, HTTPException

from palm_sdk.bricks.base import Brick, BrickManifest, registry
from palm_sdk.bricks._shared import eventbus
from palm_sdk.core.config import settings
from palm_sdk.core.logging import get_logger
from palm_sdk.permission import PermissionSpec, RiskLevel, require_permission
from palm_sdk.security import require_api_token
from .client import (
    SpeakerClientError, enroll as engine_enroll, fetch_status,
    identify as engine_identify, list_speakers as engine_list,
    remove as engine_remove, verify as engine_verify,
)
from .launcher import discover_venv_python, engine_url, probe_ready, shutdown_runtime, spawn_runtime

logger = get_logger(__name__)
router = APIRouter(prefix="/api/speaker", tags=["speaker"])

_runtime_proc = None
_runtime_lock = asyncio.Lock()


def _try_launch_on_startup() -> None:
    # 标准砖块模式：启动即拉起引擎（Popen 非阻塞，模型在子进程后台加载）。
    # 未安装 venv / 缺模型时静默降级，不阻断 P.A.L.M 启动。
    global _runtime_proc
    cfg_auto = os.environ.get("SPEAKER_AUTO_LAUNCH", "true").lower() == "true"
    if not cfg_auto or _runtime_proc is not None:
        return
    if discover_venv_python() is None:
        logger.info("未检测到 声纹识别/.venv-speaker，跳过自动拉起（请先安装依赖并下载模型）。")
        return
    try:
        _runtime_proc = spawn_runtime()
        logger.info("已拉起声纹引擎（PID=%s）。", _runtime_proc.pid)
    except (FileNotFoundError, OSError) as exc:
        logger.warning("自动拉起声纹引擎失败：%s", exc)


async def _ensure_runtime() -> None:
    global _runtime_proc
    if _runtime_proc is not None:
        return
    if os.environ.get("SPEAKER_AUTO_LAUNCH", "true").lower() != "true":
        return
    async with _runtime_lock:
        if _runtime_proc is not None:
            return
        try:
            _runtime_proc = spawn_runtime()
        except (FileNotFoundError, OSError) as exc:
            logger.warning("自动拉起声纹引擎失败：%s", exc)
            return
        is_ready = await probe_ready(engine_url(), timeout=30)
        if not is_ready:
            logger.warning("声纹引擎启动后健康检查未通过（可能缺少模型）。")


@router.get("/status", dependencies=[Depends(require_api_token)])
async def status() -> dict:
    engine_state = fetch_status(engine_url())
    venv_present = discover_venv_python() is not None
    note = ""
    if engine_state is None:
        note = "引擎未就绪：请先安装 声纹识别/.venv-speaker 依赖，并下载 CAM++ 模型到 src/speaker_models/。"
    elif not engine_state.get("ready"):
        note = "模型缺失：" + "、".join(engine_state.get("missing", [])) + "（放入后重启生效）。"
    return {
        "available": engine_state is not None and engine_state.get("ready", False),
        "speakers": (engine_state or {}).get("speakers", []),
        "missing": (engine_state or {}).get("missing", []),
        "venv_present": venv_present,
        "model": (engine_state or {}).get("model"),
        "note": note,
    }


@router.post("/enroll", dependencies=[Depends(require_api_token), Depends(require_permission("speaker.enroll"))])
async def enroll(payload: dict) -> dict:
    name = str(payload.get("name", "")).strip()
    wav_path = str(payload.get("wav_path", "")).strip()
    if not name or not wav_path or not os.path.isfile(wav_path):
        raise HTTPException(status_code=400, detail="需提供有效 name 与 wav_path")
    await _ensure_runtime()
    try:
        return engine_enroll(engine_url(), name, wav_path)
    except SpeakerClientError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.post("/identify", dependencies=[Depends(require_api_token)])
async def identify(payload: dict) -> dict:
    wav_path = str(payload.get("wav_path", "")).strip()
    if not wav_path or not os.path.isfile(wav_path):
        raise HTTPException(status_code=400, detail="需提供有效 wav_path")
    await _ensure_runtime()
    try:
        result = engine_identify(engine_url(), wav_path)
    except SpeakerClientError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    # 识别结果广播到事件总线，供对话/记忆链路消费。
    eventbus.emit(eventbus.VOICE_SPEAKER, {
        "speaker": result.get("speaker"),
        "similarity": result.get("similarity"),
        "match": result.get("match"),
        "source": "api",
    })
    return result


@router.post("/verify", dependencies=[Depends(require_api_token), Depends(require_permission("speaker.enroll"))])
async def verify(payload: dict) -> dict:
    name = str(payload.get("name", "")).strip()
    wav_path = str(payload.get("wav_path", "")).strip()
    if not name or not wav_path or not os.path.isfile(wav_path):
        raise HTTPException(status_code=400, detail="需提供有效 name 与 wav_path")
    await _ensure_runtime()
    try:
        return engine_verify(engine_url(), name, wav_path)
    except SpeakerClientError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("/list", dependencies=[Depends(require_api_token)])
async def list_speakers() -> dict:
    try:
        return {"speakers": engine_list(engine_url())}
    except SpeakerClientError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.post("/remove", dependencies=[Depends(require_api_token), Depends(require_permission("speaker.enroll"))])
async def remove(payload: dict) -> dict:
    name = str(payload.get("name", "")).strip()
    if not name:
        raise HTTPException(status_code=400, detail="需提供 name")
    try:
        return engine_remove(engine_url(), name)
    except SpeakerClientError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


def _cleanup_runtime() -> None:
    global _runtime_proc
    if _runtime_proc is not None:
        shutdown_runtime(_runtime_proc, engine_url())


atexit.register(_cleanup_runtime)

_try_launch_on_startup()

brick = Brick(
    manifest=BrickManifest(
        name="speaker",
        title="声纹识别",
        description="基于 CAM++（sherpa-onnx）的本地说话人识别砖块：嵌入提取 + 声纹库跑在独立子进程（.venv-speaker），识别结果经事件总线广播，供对话/记忆链路按说话人个性化。",
        bus_type="cpu",
    ),
    router=router,
    capabilities={
        # 供其他砖块经公共接口调用，不直接 import 内部模块。
        "is_speaker_available": lambda: fetch_status(engine_url()) is not None,
        "enroll_speaker": lambda name, wav_path: engine_enroll(engine_url(), name, wav_path),
        "identify_speaker": lambda wav_path: engine_identify(engine_url(), wav_path),
        "verify_speaker": lambda name, wav_path: engine_verify(engine_url(), name, wav_path),
        "list_speakers": lambda: engine_list(engine_url()),
    },
    permissions=[
        PermissionSpec(
            key="speaker.enroll",
            title="声纹注册",
            description="写入声纹库（注册/删除说话人），属持久化中风险操作。",
            risk=RiskLevel.MEDIUM,
            brick="speaker",
        ),
    ],
)
registry.register(brick)

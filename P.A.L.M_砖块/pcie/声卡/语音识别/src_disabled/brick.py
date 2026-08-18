"""stt 砖块：本地语音识别（sherpa-onnx 流式 ASR，独立子进程引擎）。

标准砖块模式（与 tts_sovits 一致）：推理引擎跑在砖块内独立 venv（bricks/stt/.venv-stt）的
独立子进程，主进程绝不 import sherpa_onnx。引擎识别事件经轮询拉回主进程后
emit 到事件总线（voice.transcript / voice.partial / voice.vad_state），
供 chat 等砖块订阅走对话链路（规格文档 §8.3 接线点）。
"""
from __future__ import annotations

import atexit
import asyncio
import os
import threading

from fastapi import APIRouter, Depends, HTTPException

# 相对导入（与既有砖一致）：dev.py 以 backend.app.main 启动时，绝对导入
# app.* 会解析出第二份 registry，导致本砖注册到孤立实例而路由不挂载。
from palm_sdk.core.config import settings
from palm_sdk.core.logging import get_logger
from palm_sdk.security import require_api_token
from palm_sdk.bricks.base import Brick, BrickManifest, registry
from palm_sdk.bricks._shared import eventbus
from palm_sdk.permission import PermissionSpec, RiskLevel, require_permission
from .client import (
    SttClientError, fetch_events, fetch_status,
    start_listening as engine_start, stop_listening as engine_stop,
    update_keywords as engine_update_keywords,
)
from .interrupt import classify_interrupt
from .launcher import discover_venv_python, probe_ready, shutdown_runtime, spawn_runtime

logger = get_logger(__name__)
router = APIRouter(prefix="/api/stt", tags=["stt"])

_runtime_proc = None
_runtime_lock = asyncio.Lock()
_last_event_seq = 0
_poll_stop = threading.Event()
# 语音→对话链路：前端 start 监听时把当前选中的模型配置随请求传入，
# 转发 transcript 事件时透传给 chat 砖（chat 订阅后用它生成回复）。
_voice_context = {"provider": None, "model": ""}

# 引擎事件类型 → 事件总线常量（规格文档 §3.5 事件定义）。
_ENGINE_EVENT_MAP = {
    "transcript": eventbus.VOICE_TRANSCRIPT,
    "partial": eventbus.VOICE_PARTIAL,
    "vad_state": eventbus.VOICE_VAD_STATE,
}


def _keywords_file() -> str:
    return settings.STT_KWS_KEYWORDS


def _read_keywords() -> list[str]:
    path = _keywords_file()
    if not path or not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [line.strip() for line in fh if line.strip()]


def _load_token_set() -> set[str]:
    """KWS tokens.txt 的有效 token 集合；文件缺失返回空集（跳过校验）。"""
    model_dir = settings.STT_KWS_MODEL
    tokens_path = os.path.join(model_dir, "tokens.txt") if model_dir else ""
    if not tokens_path or not os.path.isfile(tokens_path):
        return set()
    tokens: set[str] = set()
    with open(tokens_path, encoding="utf-8") as fh:
        for line in fh:
            token = line.split()[0] if line.strip() else ""
            if token:
                tokens.add(token)
    return tokens


def _validate_keywords(lines: list[str], token_set: set[str]) -> str:
    """逐行校验拼音 token（@ 前的部分）；返回首个错误描述，全通过返回空串。

    无效 token 会让引擎 KWS 重建在 C++ 层 abort 直接杀死引擎进程，
    必须在写文件前拦截。
    """
    for line in lines:
        for token in line.split("@")[0].split():
            if token and token not in token_set:
                return f"关键词「{line}」含无效拼音 token: {token}"
    return ""


def _try_launch_on_startup() -> None:
    # 标准砖块模式：启动即拉起引擎（Popen 非阻塞，模型在子进程后台加载）。
    # 未安装 venv / 缺模型时静默降级，不阻断 P.A.L.M 启动。
    global _runtime_proc
    if not settings.STT_AUTO_LAUNCH or _runtime_proc is not None:
        return
    if discover_venv_python() is None:
        logger.info("未检测到 bricks/stt/.venv-stt，跳过自动拉起（请先安装 STT 依赖）。")
        return
    try:
        _runtime_proc = spawn_runtime()
        logger.info("已拉起 STT 引擎（PID=%s）。", _runtime_proc.pid)
    except (FileNotFoundError, OSError) as exc:
        logger.warning("自动拉起 STT 引擎失败：%s", exc)


async def _ensure_runtime() -> None:
    # 首次请求时尚未拉起（启动期探测未完成）才补拉，避免重复拉起。
    global _runtime_proc
    if _runtime_proc is not None:
        return
    if not settings.STT_AUTO_LAUNCH:
        return
    async with _runtime_lock:
        if _runtime_proc is not None:
            return
        try:
            _runtime_proc = spawn_runtime()
        except (FileNotFoundError, OSError) as exc:
            logger.warning("自动拉起 STT 引擎失败：%s", exc)
            return
        is_ready = await probe_ready(settings.STT_API_URL, timeout=30)
        if not is_ready:
            logger.warning("STT 引擎启动后健康检查未通过（可能缺少模型）。")


def _poll_events_loop() -> None:
    """后台轮询引擎事件队列，转发到进程内事件总线（规格 §8.3 接线点）。"""
    global _last_event_seq
    while not _poll_stop.wait(0.5):
        if _runtime_proc is None or _runtime_proc.poll() is not None:
            continue
        try:
            events = fetch_events(settings.STT_API_URL, _last_event_seq)
        except SttClientError:
            continue
        for item in events:
            _last_event_seq = max(_last_event_seq, item["seq"])
            event_type = _ENGINE_EVENT_MAP.get(item["type"])
            if event_type:
                payload = dict(item["payload"])
                if event_type == eventbus.VOICE_TRANSCRIPT:
                    payload["provider"] = _voice_context["provider"]
                    payload["model"] = _voice_context["model"]
                    # 打断判定（规格 Task 3）：转写文本 → 语义分流 → 广播打断信号，
                    # TTS 播放层据此停止（真打断）或恢复（假警报）。
                    verdict = classify_interrupt(payload.get("text", ""))
                    eventbus.emit(eventbus.VOICE_INTERRUPTION, {**payload, **verdict})
                eventbus.emit(event_type, payload)


@router.get("/status", dependencies=[Depends(require_api_token)])
async def status() -> dict:
    engine_state = fetch_status(settings.STT_API_URL)
    venv_present = discover_venv_python() is not None
    note = ""
    if engine_state is None:
        note = "引擎未就绪：请先安装 bricks/stt/.venv-stt 依赖，并将模型放入 Data/stt_models/。"
    elif engine_state.get("missing"):
        note = "模型缺失：" + "、".join(engine_state["missing"]) + "（放入 Data/stt_models/ 后重启生效）。"
    return {
        "available": engine_state is not None,
        "listening": bool(engine_state and engine_state.get("listening")),
        "models": (engine_state or {}).get("models", {}),
        "missing": (engine_state or {}).get("missing", []),
        "venv_present": venv_present,
        "auto_launch": settings.STT_AUTO_LAUNCH,
        "sample_rate": settings.STT_SAMPLE_RATE,
        "note": note,
    }


@router.post("/start", dependencies=[Depends(require_api_token), Depends(require_permission("stt.listen"))])
async def start(payload: dict | None = None) -> dict:
    # 语音→对话链路：前端把当前选中的模型配置随 start 传入，事件转发时透传给 chat 砖。
    global _voice_context
    if payload:
        _voice_context = {
            "provider": payload.get("provider"),
            "model": str(payload.get("model") or "").strip(),
        }
    await _ensure_runtime()
    try:
        result = engine_start(settings.STT_API_URL)
    except SttClientError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"started": result.get("ok", False), "message": result.get("message", "")}


@router.post("/stop", dependencies=[Depends(require_api_token), Depends(require_permission("stt.listen"))])
async def stop() -> dict:
    try:
        result = engine_stop(settings.STT_API_URL)
    except SttClientError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"stopped": result.get("ok", False)}


@router.get("/keywords", dependencies=[Depends(require_api_token)])
async def get_keywords() -> dict:
    return {"keywords": _read_keywords(), "path": _keywords_file()}


@router.put("/keywords", dependencies=[Depends(require_api_token), Depends(require_permission("stt.listen"))])
async def put_keywords(payload: dict) -> dict:
    lines = [str(item).strip() for item in payload.get("keywords", [])]
    token_set = _load_token_set()
    if token_set:
        error = _validate_keywords(lines, token_set)
        if error:
            raise HTTPException(status_code=400, detail=error)
    path = _keywords_file()
    if not path:
        raise HTTPException(status_code=503, detail="未配置关键词文件路径（STT_KWS_KEYWORDS），无法保存")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + ("\n" if lines else ""))
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"写入关键词文件失败: {exc}")
    try:
        result = engine_update_keywords(settings.STT_API_URL, lines)
    except SttClientError:
        result = {"ok": True, "message": "关键词已保存（引擎未就绪，待其启动后生效）"}
    return {"ok": result.get("ok", False), "message": result.get("message", "")}


def _cleanup_runtime() -> None:
    if _runtime_proc is not None:
        _poll_stop.set()
        shutdown_runtime(_runtime_proc, settings.STT_API_URL)


atexit.register(_cleanup_runtime)

_try_launch_on_startup()
_poll_thread = threading.Thread(target=_poll_events_loop, daemon=True, name="stt-event-poll")
_poll_thread.start()

brick = Brick(
    manifest=BrickManifest(
        name="stt",
        title="语音识别",
        description="基于 sherpa-onnx 的本地语音识别砖块：VAD + KWS + 流式 ASR 跑在独立子进程（.venv-stt），识别文本经事件总线广播，供对话链路消费。",
        bus_type="cpu",
    ),
    router=router,
    capabilities={
        # 供其他砖块经公共接口调用，不直接 import 内部模块。
        "is_stt_available": lambda: fetch_status(settings.STT_API_URL) is not None,
        "start_listening": lambda: engine_start(settings.STT_API_URL),
        "stop_listening": lambda: engine_stop(settings.STT_API_URL),
        "list_keywords": _read_keywords,
    },
    permissions=[
        PermissionSpec(
            key="stt.listen",
            title="语音识别监听",
            description="打开麦克风进行语音识别（调用本地 sherpa-onnx STT 引擎）。",
            risk=RiskLevel.MEDIUM,
            brick="stt",
        ),
    ],
)
registry.register(brick)
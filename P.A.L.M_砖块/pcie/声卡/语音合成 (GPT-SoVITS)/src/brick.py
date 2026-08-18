"""tts_sovits 砖块：把 GPT-SoVITS 作为 P.A.L.M 的语音合成能力。

设计立场（标准砖块模式）：
- 源码随砖块分发：GPT-SoVITS 源码在 gpt_sovits/，依赖安装在独立 venv（.venv-gsv）。
- 绝不 import GPT-SoVITS 的重依赖，运行时作为独立进程存在；连不上就自动降级，不污染 P.A.L.M 进程。
- 通过 agent 砖块的 register_tool 能力注册 Agent 工具，避免砖块间直接互调。
"""
from __future__ import annotations

import os
import subprocess
import tempfile

import httpx

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from palm_sdk.core.config import settings
from palm_sdk.bricks._shared.paths import fallback_dir, resolve_storage
from palm_sdk.core.logging import get_logger
from palm_sdk.security import require_api_token
from palm_sdk.bricks.base import Brick, BrickManifest, registry
from palm_sdk.bricks._shared.transport import SubprocessSpec
from palm_sdk.bricks._shared.handle import get_handle
from palm_sdk.permission import PermissionSpec, RiskLevel, require_permission
from .client import TtsClientError, check_upstream_health, synthesize_speech, synthesize_speech_stream
from .tool import TtsTool

logger = get_logger(__name__)
router = APIRouter(prefix="/api/tts", tags=["tts_sovits"])


# ── 子进程启动命令（收敛自原 launcher.py，改由管理芯片托管）────────
def _discover_venv_python() -> str | None:
    """定位独立 venv 的 Python（api.py 的运行解释器）。

    探测顺序：SOVITS_VENV_PYTHON 环境变量 → 项目根 .venv-gsv/Scripts|bin/python。
    """
    if settings.SOVITS_VENV_PYTHON and os.path.isfile(settings.SOVITS_VENV_PYTHON):
        return settings.SOVITS_VENV_PYTHON
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    candidates = [
        os.path.join(project_root, ".venv-gsv", "Scripts", "python.exe"),
        os.path.join(project_root, ".venv-gsv", "bin", "python"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def _resolve_model_path(rel_or_abs: str) -> str:
    if os.path.isabs(rel_or_abs):
        return rel_or_abs
    return os.path.join(settings.SOVITS_ROOT, rel_or_abs)


def _build_gsv_cmd(port: int) -> list[str]:
    """构造拉起 GPT-SoVITS api.py 的命令（cwd 固定为 SOVITS_ROOT，模型用相对路径）。"""
    python = _discover_venv_python()
    if python is None:
        raise FileNotFoundError(
            "未找到 .venv-gsv 虚拟环境，无法自动拉起 GPT-SoVITS。"
            "请先运行 `python plugins/tts_sovits/install.py` 安装依赖。"
        )
    cmd = [
        python, "api.py",
        "-a", "127.0.0.1", "-p", str(port), "-d", settings.SOVITS_INFER_DEVICE,
        "-sm", "normal",
        "-cp", "，。？！；：",
        "-s", _resolve_model_path(settings.SOVITS_SOVITS_MODEL),
        "-g", _resolve_model_path(settings.SOVITS_GPT_MODEL),
        "-hb", _resolve_model_path(settings.SOVITS_HUBERT_DIR),
        "-b", _resolve_model_path(settings.SOVITS_BERT_DIR),
    ]
    refer_wav = settings.SOVITS_DEFAULT_REFER_WAV
    refer_text = settings.SOVITS_DEFAULT_REFER_TEXT
    refer_lang = settings.SOVITS_DEFAULT_REFER_LANG
    if refer_wav and refer_text and refer_lang:
        cmd += ["-dr", refer_wav, "-dt", refer_text, "-dl", refer_lang]
    return cmd


def _split_ogg_streams(audio: bytes) -> list[bytes]:
    """按 ogg 页序列号切出独立 ogg 流（GSV 流式逐块输出，每块是独立 ogg 文件）。"""
    streams: list[bytes] = []
    bounds: list[tuple[int, int]] = []
    prev_serial: int | None = None
    start = 0
    pos = 0
    while True:
        i = audio.find(b"OggS", pos)
        if i < 0:
            break
        serial = int.from_bytes(audio[i + 14:i + 18], "little")
        if prev_serial is not None and serial != prev_serial:
            bounds.append((start, i))
            start = i
        prev_serial = serial
        pos = i + 4
    if prev_serial is not None:
        bounds.append((start, len(audio)))
    for b0, b1 in bounds:
        streams.append(audio[b0:b1])
    return streams


def _merge_ogg_blocks(audio: bytes) -> bytes:
    # GSV 流式模式按标点逐块输出独立 ogg，整段拼接无法解码；且 ogg 间
    # `-c copy` 直接拼接不可靠（偶发坏文件）。改为：逐块解码 wav → concat
    # demuxer 拼接 → 返回单个 wav（ffmpeg 最稳定路径）。单流/非 ogg 原样返回。
    streams = _split_ogg_streams(audio)
    if len(streams) <= 1:
        return audio
    ffmpeg = "ffmpeg"  # 使用系统 PATH 中的 ffmpeg（标准砖块无自带 runtime）
    try:
        with tempfile.TemporaryDirectory() as tmp:
            wavs = []
            for i, chunk in enumerate(streams):
                bpath = os.path.join(tmp, f"b{i}.ogg")
                with open(bpath, "wb") as fh:
                    fh.write(chunk)
                wpath = os.path.join(tmp, f"b{i}.wav")
                proc = subprocess.run(
                    [ffmpeg, "-y", "-i", bpath, "-c:a", "pcm_s16le", wpath],
                    capture_output=True, timeout=60,
                )
                if proc.returncode != 0 or not os.path.isfile(wpath):
                    return audio
                wavs.append(wpath)
            listf = os.path.join(tmp, "list.txt")
            with open(listf, "w") as fh:
                for w in wavs:
                    fh.write(f"file '{w.replace(os.sep, '/')}'\n")
            out = os.path.join(tmp, "merged.wav")
            proc = subprocess.run(
                [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", listf,
                 "-c:a", "pcm_s16le", out],
                capture_output=True, timeout=60,
            )
            if proc.returncode == 0 and os.path.isfile(out):
                with open(out, "rb") as fh:
                    return fh.read()
    except (OSError, subprocess.SubprocessError):
        pass
    return audio


def _port_ready_sync(timeout: float = 1.0) -> bool:
    """同步探测上游端口是否已有 GSV 服务（手动拉起/外部托管时不重复 spawn）。

    任何 HTTP 响应（200/400/500）都视为已有服务监听；仅连接失败才算未就绪。
    """
    if not settings.SOVITS_API_URL:
        return False
    try:
        httpx.get(settings.SOVITS_API_URL.rstrip("/") + "/", timeout=timeout)
        return True
    except httpx.HTTPError:
        return False


async def _ensure_chip() -> None:
    """经管理芯片托管子进程：若端口已有外部 GSV（手动/上次实例）则跳过，
    否则由 tts_sovits 芯片（SubprocessTransport）拉起并探测就绪。

    此前砖内自管的 _runtime_proc / _ensure_runtime / _try_launch_on_startup /
    _cleanup_runtime 已收敛删除——进程生命周期完全交给 BrickHandle，应用关闭
    时经 lifespan 统一 dispose，杜绝孤儿进程。venv 缺失时 load() 抛
    FileNotFoundError，由调用方捕获降级为 503（不阻断主程序）。
    """
    if _port_ready_sync():
        return  # 外部已托管，芯片无需 spawn（避免双实例 bind 冲突）
    handle = get_handle("tts_sovits")
    if handle is None:
        return
    try:
        await handle.load()
    except (FileNotFoundError, OSError) as exc:
        logger.warning("GPT-SoVITS 子进程拉起失败（降级，合成将 503）：%s", exc)


def _sniff_media_type(audio: bytes, fallback: str) -> str:
    # GSV 流式模式（-sm normal）强制输出 ogg，非流式为 wav——按魔数嗅探修正
    # 媒体类型，避免把 ogg 字节标成 audio/wav 导致前端播放器误解析。
    if audio[:4] == b"RIFF":
        return "wav"
    if audio[:4] == b"OggS":
        return "ogg"
    return fallback


@router.post("/synthesize", dependencies=[Depends(require_api_token), Depends(require_permission("tts.speak"))])
async def synthesize(payload: dict) -> Response:
    await _ensure_chip()
    if not settings.SOVITS_API_URL:
        raise HTTPException(status_code=503, detail="未配置 SOVITS_API_URL，无法合成")
    try:
        audio = await synthesize_speech(payload, settings.SOVITS_API_URL, settings.SOVITS_API_ROUTE)
    except TtsClientError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    audio = _merge_ogg_blocks(audio)
    media_type = _sniff_media_type(audio, payload.get("media_type", "wav"))
    return Response(content=audio, media_type=f"audio/{media_type}")


@router.post("/synthesize-stream", dependencies=[Depends(require_api_token), Depends(require_permission("tts.speak"))])
async def synthesize_stream(payload: dict) -> Response:
    """流式合成：分块直通（首块含音频头，边合成边出）。

    配合语音专线逐句播放：首段延迟 = 上游第一块合成时间，而非等整段完成。
    首块到达后按魔数嗅探媒体类型（-sm normal 为 ogg）；首块前失败可返回 503，
    流中途失败落审计。
    """
    from fastapi.responses import StreamingResponse

    await _ensure_chip()
    if not settings.SOVITS_API_URL:
        raise HTTPException(status_code=503, detail="未配置 SOVITS_API_URL，无法合成")
    try:
        upstream = synthesize_speech_stream(payload, settings.SOVITS_API_URL, settings.SOVITS_API_ROUTE)
        first = await upstream.__anext__()
    except StopAsyncIteration:
        first = b""
    except TtsClientError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    media_type = _sniff_media_type(first, "wav")

    async def _stream():
        if first:
            yield first
        try:
            async for chunk in upstream:
                yield chunk
        except TtsClientError as exc:
            # 流中途失败：无法改状态码，落审计并给前端可辨识的错误标记。
            logger.warning("流式合成中断：%s", exc)

    return StreamingResponse(_stream(), media_type=f"audio/{media_type}")


@router.get("/status", dependencies=[Depends(require_api_token)])
async def status() -> dict:
    is_available = await check_upstream_health(settings.SOVITS_API_URL)
    venv_present = _discover_venv_python() is not None
    note = "" if is_available else "运行时未就绪：请先运行 `python plugins/tts_sovits/install.py` 安装依赖。"
    return {
        "available": is_available,
        "upstream_url": settings.SOVITS_API_URL,
        "auto_launch": settings.SOVITS_AUTO_LAUNCH,
        "venv_present": venv_present,
        "note": note,
    }


@router.get("/audio/{filename}", dependencies=[Depends(require_api_token)])
async def serve_audio(filename: str) -> Response:
    # 仅允许纯文件名，杜绝路径穿越读取输出目录之外。
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="非法文件名")
    path = os.path.join(settings.SOVITS_OUTPUT_DIR, filename)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="音频不存在")
    media = "audio/wav"
    if filename.endswith(".ogg"):
        media = "audio/ogg"
    elif filename.endswith(".aac"):
        media = "audio/aac"
    with open(path, "rb") as fh:
        data = fh.read()
    return Response(content=data, media_type=media)


async def _synthesize_via_brick(text: str, text_language: str = "zh", **kwargs) -> bytes:
    payload = {"text": text, "text_language": text_language, **kwargs}
    audio = await synthesize_speech(payload, settings.SOVITS_API_URL, settings.SOVITS_API_ROUTE)
    return _merge_ogg_blocks(audio)


async def _synthesize_stream_via_brick(text: str, text_language: str = "zh", **kwargs):
    """流式合成能力（供 voice 砖/语音专线逐句合成即播）。"""
    payload = {"text": text, "text_language": text_language, **kwargs}
    async for chunk in synthesize_speech_stream(
        payload, settings.SOVITS_API_URL, settings.SOVITS_API_ROUTE
    ):
        yield chunk


@router.post("/launch", dependencies=[Depends(require_api_token), Depends(require_permission("tts.speak"))])
async def launch() -> dict:
    # 供运维显式预热运行时（首次合成请求也会按需拉起，此端点用于提前拉起）。
    # 端口已有外部 GSV / 芯片已激活均视为已在运行。
    if _port_ready_sync():
        return {"launched": True, "already_running": True}
    handle = get_handle("tts_sovits")
    if handle is not None and handle.state == "active":
        return {"launched": True, "already_running": True}
    if _discover_venv_python() is None:
        raise HTTPException(status_code=409, detail="未检测到 .venv-gsv，请先运行 install.py 安装依赖。")
    try:
        await _ensure_chip()
    except (FileNotFoundError, OSError) as exc:
        raise HTTPException(status_code=409, detail=f"拉起失败：{exc}")
    if not settings.SOVITS_API_URL:
        return {"launched": False, "already_running": False}
    is_ready = await check_upstream_health(settings.SOVITS_API_URL)
    return {"launched": is_ready, "already_running": False}


def is_available() -> bool:
    """砖块自身就绪判定：独立 venv 解释器与 GSV 入口(api.py)均就绪才视为可用。

    不抛异常——缺依赖或模型未配置时返回 False，供编排层统一查询与优雅降级。
    """
    if _discover_venv_python() is None:
        return False
    # api.py 是子进程入口，缺失则无法拉起运行时。
    api_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gpt_sovits", "api.py")
    return os.path.isfile(api_py)


async def _is_available_via_brick() -> bool:
    """能力接口：砖就绪状态（与 CosyVoice 对齐，供 CPU 统一查询）。"""
    return is_available()


brick = Brick(
    manifest=BrickManifest(
        name="tts_sovits",
        title="语音合成 (GPT-SoVITS)",
        description="基于 GPT-SoVITS 的语音合成砖块：源码随砖块分发，依赖安装在独立 venv（.venv-gsv），由管理芯片（BrickHandle）托管子进程，提供 HTTP 合成接口与 Agent 工具。",
        is_core=False,
        bus_type="pcie",
        can_accept_files=False,
    ),
    router=router,
    capabilities={
        # 供其他砖块经公共接口调用，不直接 import 内部模块。
        "synthesize_speech": _synthesize_via_brick,
        "synthesize_speech_stream": _synthesize_stream_via_brick,
        "is_tts_available": lambda: check_upstream_health(settings.SOVITS_API_URL),
        # 砖就绪状态：venv 解释器与 GSV 入口齐备即为可用（不连网、不抛异常）。
        "is_available": _is_available_via_brick,
        # 收敛进通用 SubprocessTransport：把「如何拉起/关停 GSV 子进程」作为治理
        # 元数据暴露给 BrickHandle（管理芯片）。cmd_builder 用本模块内置的
        # _build_gsv_cmd（已从 launcher.py 收敛），仅在真正隔离拉起（handle.load /
        # transport.start）时才解析命令，导入期不调用，避免 venv 缺失时抛错阻断降级。
        "subprocess_spec": SubprocessSpec(
            cmd_builder=_build_gsv_cmd,
            port=settings.SOVITS_API_PORT,
            cwd=settings.SOVITS_ROOT,
            health_path="/",
            readiness_timeout=240,
            log_path=os.path.join(fallback_dir(settings.SOVITS_ROOT, __file__, "models"), "gsv_runtime.log"),
        ),
    },
    permissions=[
        PermissionSpec(
            key="tts.speak",
            title="语音合成",
            description="让助手或接口把文字合成为语音（调用本地 GPT-SoVITS 运行时）。",
            risk=RiskLevel.LOW,
            brick="tts_sovits",
        ),
    ],
)

# 经 agent 砖块的 register_tool 能力注册 Agent 工具，避免砖块间直接互调。
_agent_brick = registry.get("agent")
if _agent_brick is not None:
    register_tool = _agent_brick.capabilities.get("register_tool")
    if register_tool is not None:
        register_tool(TtsTool())
    else:
        logger.warning("agent 砖块未暴露 register_tool 能力，TtsTool 未注册。")
else:
    logger.warning("agent 砖块尚未注册，TtsTool 延后不可用；请确认 tts_sovits 在 agent 之后导入。")

registry.register(brick)
"""chat 砖块：流式对话入口。

UI 作为中枢调用本砖块的 /api/chat；自身不持有模型协议，经 models 砖能力 create_stream 取流、
经 usage 砖能力做配额拦截与流末记账。砖块之间仅经注册表 capabilities 交互，互不 import。
"""
from __future__ import annotations

import asyncio
import re
import json
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from palm_sdk.core.logging import get_logger
from palm_sdk.security import require_api_token
from palm_sdk.bricks.base import Brick, BrickManifest, registry
from palm_sdk.bricks._shared import eventbus
from palm_sdk.schemas.chat import ChatMessage, ChatRequest, ProviderRef

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])


def _models_capability(name: str):
    """运行时经 models 砖能力取用模型相关函数（懒加载，避免导入期依赖）。"""
    models_brick = registry.get("models")
    if models_brick:
        return models_brick.capabilities.get(name)
    return None


def _is_model_file_capable(model: str | None) -> bool:
    fn = _models_capability("is_model_file_capable")
    return bool(fn and fn(model))


def _file_handling_mode(model: str | None, has_files: bool) -> str:
    fn = _models_capability("file_handling_mode")
    if fn:
        return fn(model, has_files)
    return "process" if has_files else "none"


def new_chat_id() -> str:
    return uuid.uuid4().hex[:12]


def now() -> int:
    return int(time.time())


def _sse(payload: dict | str) -> str:
    if isinstance(payload, dict):
        payload = json.dumps(payload, ensure_ascii=False)
    return f"data: {payload}\n\n"


@router.get("/chat/file-support", dependencies=[Depends(require_api_token)])
async def chat_file_support(model: str | None = Query(None, description="模型标识，如 gpt-4o / deepseek-chat")):
    """文件处理支持接口（布尔值）。

    返回该模型是否原生支持文件 / 多模态上传：
    - supports_files=true  -> 聊天时跳过解析砖块，直接将文件传给模型（direct）
    - supports_files=false -> 聊天时需先经解析砖块处理成结构化文本（process）

    UI 中枢可据此在「直接传文件」与「先解析再传文本」之间做分支。
    """
    return {
        "model": model or "",
        "supports_files": _is_model_file_capable(model),
        "file_handling": _file_handling_mode(model, True),
    }


def resolve_chat_messages(req: ChatRequest, model: str) -> tuple[list[ChatMessage], str]:
    """按模型能力决定附件处理并注入默认 system。

    返回 (消息列表, 附件说明)。process 模式说明客户端未按约定先解析，
    直接拒绝以守住「砖块互不调用」边界。
    """
    last_user = next((m for m in reversed(req.messages) if m.role == "user"), None)
    attachments = last_user.attachments if last_user else []
    mode = _file_handling_mode(model, bool(attachments))
    if mode == "direct":
        names = ", ".join(a.name for a in attachments)
        attachment_note = f"模型 {model} 支持直接传文件，已跳过解析：{names}"
    elif mode == "process":
        raise HTTPException(
            status_code=400,
            detail="模型不支持文件上传；请先在客户端经 /api/parse 解析为文本后再发送",
        )
    else:
        attachment_note = ""
    has_system = any(m.role == "system" for m in req.messages)
    if has_system:
        return req.messages, attachment_note
    default_system = ChatMessage(
        role="system",
        content="你是一个有用的AI助手，请用简洁清晰的中文回答用户的问题。",
    )
    return [default_system] + list(req.messages), attachment_note


def _check_chat_quota() -> object | None:
    """配额拦截：经 usage 砖能力读取配额，超额抛 429；返回 usage 砖引用供后续记账。"""
    usage_brick = registry.get("usage")
    if not usage_brick:
        return None
    check_quota = usage_brick.capabilities.get("check_quota")
    if check_quota:
        exceeded, quota_msg = check_quota()
        if exceeded:
            raise HTTPException(status_code=429, detail=quota_msg)
    return usage_brick


def _record_stream_usage(chat_id, model, req, messages_for_chat, streamed_text, merged_usage, usage_brick) -> None:
    """流末记账：仅真实用量入台账（用户要求不显示 mock 估算用量）。

    真实 usage 缺失（本地模型）时直接跳过——按字符估算的数字不是真实消耗，
    入台账会污染用量明细与配额统计；有真实消耗才记录并展示。
    """
    prompt = int(merged_usage.get("prompt_tokens") or 0)
    completion = int(merged_usage.get("completion_tokens") or 0)
    total = int(merged_usage.get("total_tokens") or 0)
    if total <= 0:
        return
    record_usage_fn = usage_brick.capabilities.get("record_usage") if usage_brick else None
    if record_usage_fn:
        # provider 优先取请求传来标识；为空时从模型名推断（形如 "openai/gpt-4o"）。
        provider_name = req.provider.provider if req.provider else ""
        if not provider_name and "/" in model:
            provider_name = model.split("/", 1)[0]
        record_usage_fn(
            chat_id=chat_id, model=model, provider=provider_name or "",
            prompt_tokens=prompt, completion_tokens=completion, total_tokens=total,
        )


async def _stream_chat_events(req, model, chat_id, messages_for_chat, attachment_note, usage_brick):
    """SSE 事件生成器：取流、合并增量、流末记账。"""
    yield _sse({"id": chat_id, "model": model, "created": now(), "delta": "", "reasoning": ""})
    merged_usage: dict = {}
    streamed_text = ""
    create_stream = _models_capability("create_stream")
    try:
        async for delta in create_stream(
            messages_for_chat, model=model, note=attachment_note, provider=req.provider,
            temperature=req.temperature, max_tokens=req.max_tokens, thinking=req.thinking,
        ):
            event = {
                "id": chat_id, "model": model, "created": now(),
                "delta": delta.content, "reasoning": delta.reasoning,
            }
            if delta.content:
                streamed_text += delta.content
            if delta.usage:
                merged_usage.update(delta.usage)
                event["usage"] = merged_usage
            yield _sse(event)
            await asyncio.sleep(0)  # yield control to the event loop
    except Exception as exc:
        # 模型流异常（超时/鉴权失败/上游 5xx）不能让生成器抛到 ASGI 层，
        # 否则连接被掐断、前端拿到半截流。改为下发错误事件后正常收尾。
        logger.warning("模型流异常（已转错误事件）: %s", exc)
        yield _sse({
            "id": chat_id, "model": model, "created": now(),
            "type": "error", "delta": f"⚠️ 模型生成失败：{exc}", "error": str(exc),
        })
    else:
        _record_stream_usage(chat_id, model, req, messages_for_chat, streamed_text, merged_usage, usage_brick)
    yield _sse("[DONE]")


@router.post("/chat", dependencies=[Depends(require_api_token)])
async def chat(req: ChatRequest):
    """Server-Sent-Events streaming endpoint.

    每个事件 `data: {...}` 含键 {id, model, created, delta, reasoning, usage}；
    `delta` 为正文增量、`reasoning` 为思维链增量、`usage` 为用量统计；
    末尾 `data: [DONE]` 标识结束。
    """
    chat_id = new_chat_id()
    model = req.model or ""
    logger.info("新对话请求 model=%s", model)
    if not model and not req.provider:
        raise HTTPException(
            status_code=400,
            detail="未配置可用模型：请先在「设置 › 模型 › 添加模型」添加并选择一个模型",
        )
    usage_brick = _check_chat_quota()
    messages_for_chat, attachment_note = resolve_chat_messages(req, model)
    if _models_capability("create_stream") is None:
        raise HTTPException(
            status_code=503,
            detail="模型后端（models 砖）未启用，无法生成回复；请在后端启用 models 砖。",
        )
    return StreamingResponse(
        _stream_chat_events(req, model, chat_id, messages_for_chat, attachment_note, usage_brick),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── 语音输入接线（规格 §12 对接点）──────────────────────────
# STT 砖把 ASR 最终文本发布到 voice.transcript（负载含前端 start 时透传的
# provider/model），本砖订阅后走与 /api/chat 相同的对话链路；LLM 流式正文
# 逐句并行合成语音（经 tts_sovits capability），音频块发布到 voice.tts_audio_chunk，
# 完整回复发布到 voice.reply_ready。无模型配置时优雅跳过，不产生 mock 回复。

_SENTENCE_SPLIT = re.compile(r"[。！？；…]+|[,，]")  # 切句点：整句含尾标点立即并行合成


async def _synthesize_voice_chunk(sentence: str, seq: int) -> None:
    """逐句流式合成语音并发布音频块事件（播放端按 seq 顺序拼接播放）。"""
    tts_brick = registry.get("tts_sovits")
    synth = tts_brick.capabilities.get("synthesize_speech_stream") if tts_brick else None
    if synth is None:
        return
    audio = bytearray()
    try:
        async for chunk in synth(sentence):
            audio.extend(chunk)
    except Exception as exc:  # noqa: BLE001 合成失败只跳过该句，不阻断链路
        logger.warning("语音句合成失败: %s", exc)
        return
    if audio:
        eventbus.emit(eventbus.VOICE_TTS_CHUNK, {
            "seq": seq, "text": sentence, "audio": bytes(audio),
        })


async def _reply_voice_text(voice_text: str, provider: dict | None = None,
                            model: str = "", thinking: dict | None = None) -> None:
    """把语音文本送入对话链路；LLM 流式正文逐句并行合成，回复发布到事件总线。"""
    create_stream = _models_capability("create_stream")
    if create_stream is None:
        logger.warning("语音对话跳过：models 砖未启用")
        return
    if not model or not provider:
        logger.warning("语音对话跳过：缺少模型配置（请通过 /api/stt/start 传入 provider/model）")
        return
    try:
        provider_ref = ProviderRef(**{
            key: provider[key] for key in ("base_url", "api_key", "mode", "provider") if key in provider
        })
    except (TypeError, ValueError) as exc:
        logger.warning("语音对话跳过：模型配置无效: %s", exc)
        return
    if not provider_ref.base_url:
        logger.warning("语音对话跳过：模型配置缺少 base_url")
        return
    messages = [
        ChatMessage(role="system", content="你是一个有用的AI助手，请用简洁清晰的中文回答用户的问题。"),
        ChatMessage(role="user", content=voice_text),
    ]
    reply_text = ""
    buffer = ""  # 攒到完整句再交给 TTS，保证句子边界不破句
    seq = 0
    tasks: list = []
    try:
        async for delta in create_stream(
            messages, model=model, note="语音输入", provider=provider_ref, thinking=thinking,
        ):
            if not delta.content:
                continue
            reply_text += delta.content
            buffer += delta.content
            while True:
                match = _SENTENCE_SPLIT.search(buffer)
                if not match or match.end() >= len(buffer):
                    break
                sentence = buffer[:match.end()].strip()
                buffer = buffer[match.end():]
                if sentence:
                    seq += 1
                    tasks.append(asyncio.create_task(_synthesize_voice_chunk(sentence, seq)))
    except Exception as exc:  # noqa: BLE001 模型流异常类型不定
        logger.warning("语音对话生成失败: %s", exc)
    tail = buffer.strip()
    if tail:
        seq += 1
        tasks.append(asyncio.create_task(_synthesize_voice_chunk(tail, seq)))
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    if reply_text.strip():
        eventbus.emit(eventbus.VOICE_REPLY_READY, {
            "text": reply_text, "voice_text": voice_text, "chunk_count": seq,
        })


def _on_voice_transcript(payload: dict) -> None:
    """voice.transcript 订阅回调（STT 轮询线程触发，需独立事件循环跑对话）。"""
    if not payload or not payload.get("is_final"):
        return
    text = str(payload.get("text") or "").strip()
    if not text:
        return
    asyncio.run(_reply_voice_text(
        text, payload.get("provider"), str(payload.get("model") or ""), payload.get("thinking"),
    ))


brick = Brick(
    manifest=BrickManifest(
        name="chat",
        title="对话",
        description="流式对话入口（/api/chat、/api/chat/file-support）；经 models 砖 create_stream 取流、usage 砖做配额与记账。",
        bus_type="board",
        is_streaming=True,
    ),
    router=router,
)
registry.register(brick)

# 语音识别最终文本 → 自动对话（规格 §12）；事件总线同步回调，零额外依赖。
eventbus.subscribe(eventbus.VOICE_TRANSCRIPT, _on_voice_transcript)
"""对话服务：流式对话链路（收敛自 chat 砖）。

UI 作为中枢调用本模块；自身不持有模型协议——经服务容器取模型适配器
create_stream 取流、经用量服务做配额拦截与流末记账，模块间仅经容器交互。
语音输入接线：语音识别最终文本发布到 voice.transcript，本模块订阅后走
同一对话链路，LLM 流式正文逐句并行合成语音发布到事件总线。
"""
from __future__ import annotations

import asyncio
import json
import re
import time
import uuid

from palm._core.logging import get_logger
from palm._core.container import container
from palm._core.eventbus import emit, subscribe, VOICE_TRANSCRIPT, VOICE_TTS_CHUNK, VOICE_REPLY_READY
from palm._core.schemas.chat import ChatMessage, ChatRequest, ProviderRef
from ..ops.token_usage import QuotaExceededError

logger = get_logger(__name__)


class ChatError(Exception):
    """对话链路业务错误（配额/模型缺失/附件模式不符等）。"""


def _models_capability(name: str):
    """运行时经服务容器取模型适配器能力（懒加载，避免导入期依赖）。"""
    models = container.get("models")
    if models:
        return models.capabilities.get(name)
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


def file_support(model: str | None) -> dict:
    """返回该模型是否原生支持文件 / 多模态上传（direct=直接传文件，process=先解析）。"""
    return {
        "model": model or "",
        "supports_files": _is_model_file_capable(model),
        "file_handling": _file_handling_mode(model, True),
    }


def resolve_chat_messages(req: ChatRequest, model: str) -> tuple[list[ChatMessage], str]:
    """按模型能力决定附件处理并注入默认 system。

    返回 (消息列表, 附件说明)。process 模式说明调用方未按约定先解析，
    直接拒绝以守住模块边界。
    """
    last_user = next((m for m in reversed(req.messages) if m.role == "user"), None)
    attachments = last_user.attachments if last_user else []
    mode = _file_handling_mode(model, bool(attachments))
    if mode == "direct":
        names = ", ".join(a.name for a in attachments)
        attachment_note = f"模型 {model} 支持直接传文件，已跳过解析：{names}"
    elif mode == "process":
        raise ChatError("模型不支持文件上传；请先在客户端经 /api/parse 解析为文本后再发送")
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


def _check_chat_quota():
    """配额拦截：超额抛 QuotaExceededError；返回用量服务句柄供流末记账。"""
    usage = container.get("usage")
    if not usage:
        return None
    check_quota = usage.capabilities.get("check_quota")
    if check_quota:
        exceeded, quota_msg = check_quota()
        if exceeded:
            raise QuotaExceededError(quota_msg)
    return usage


def _record_stream_usage(chat_id, model, req, messages_for_chat, streamed_text, merged_usage, usage) -> None:
    """流末记账：仅真实用量入台账（用户要求不显示 mock 估算用量）。

    真实 usage 缺失（本地模型）时直接跳过——按字符估算的数字不是真实消耗，
    入台账会污染用量明细与配额统计。
    """
    total = int(merged_usage.get("total_tokens") or 0)
    if total <= 0:
        return
    record_usage_fn = usage.capabilities.get("record_usage") if usage else None
    if record_usage_fn:
        provider_name = req.provider.provider if req.provider else ""
        if not provider_name and "/" in model:
            provider_name = model.split("/", 1)[0]
        record_usage_fn(
            chat_id=chat_id, model=model, provider=provider_name or "",
            prompt_tokens=int(merged_usage.get("prompt_tokens") or 0),
            completion_tokens=int(merged_usage.get("completion_tokens") or 0),
            total_tokens=total,
        )


async def _stream_chat_events(req, model, chat_id, messages_for_chat, attachment_note, usage):
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
            await asyncio.sleep(0)
    except Exception as exc:
        # 模型流异常（超时/鉴权失败/上游 5xx）不能让生成器抛到调用层，
        # 否则连接被掐断、调用方拿到半截流。改为下发错误事件后正常收尾。
        logger.warning("模型流异常（已转错误事件）: %s", exc)
        yield _sse({
            "id": chat_id, "model": model, "created": now(),
            "type": "error", "delta": f"⚠️ 模型生成失败：{exc}", "error": str(exc),
        })
    else:
        _record_stream_usage(chat_id, model, req, messages_for_chat, streamed_text, merged_usage, usage)
    yield _sse("[DONE]")


def build_chat_stream(req: ChatRequest):
    """构造流式对话生成器（async iterator），供 HTTP/其他入口直接消费。

    每个事件 `data: {...}` 含键 {id, model, created, delta, reasoning, usage}；
    末尾 `data: [DONE]` 标识结束。
    """
    chat_id = new_chat_id()
    model = req.model or ""
    if not model and not req.provider:
        raise ChatError("未配置可用模型：请先在「设置 › 模型 › 添加模型」添加并选择一个模型")
    usage = _check_chat_quota()
    messages_for_chat, attachment_note = resolve_chat_messages(req, model)
    if _models_capability("create_stream") is None:
        raise ChatError("模型后端（models 适配器）未启用，无法生成回复")
    return _stream_chat_events(req, model, chat_id, messages_for_chat, attachment_note, usage)


# ── 语音输入接线 ─────────────────────────────
_SENTENCE_SPLIT = re.compile(r"[。！？；…]+|[,，]")  # 切句点：整句含尾标点立即并行合成


async def _synthesize_voice_chunk(sentence: str, seq: int) -> None:
    """逐句流式合成语音并发布音频块事件（播放端按 seq 顺序拼接播放）。"""
    tts = container.get("tts_sovits")
    synth = tts.capabilities.get("synthesize_speech_stream") if tts else None
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
        emit(VOICE_TTS_CHUNK, {"seq": seq, "text": sentence, "audio": bytes(audio)})


async def reply_voice_text(voice_text: str, provider: dict | None = None,
                           model: str = "", thinking: dict | None = None) -> None:
    """把语音文本送入对话链路；LLM 流式正文逐句并行合成，回复发布到事件总线。"""
    create_stream = _models_capability("create_stream")
    if create_stream is None:
        logger.warning("语音对话跳过：models 适配器未启用")
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
        emit(VOICE_REPLY_READY, {"text": reply_text, "voice_text": voice_text, "chunk_count": seq})


def _on_voice_transcript(payload: dict) -> None:
    """voice.transcript 订阅回调（STT 轮询线程触发，需独立事件循环跑对话）。"""
    if not payload or not payload.get("is_final"):
        return
    text = str(payload.get("text") or "").strip()
    if not text:
        return
    asyncio.run(reply_voice_text(
        text, payload.get("provider"), str(payload.get("model") or ""), payload.get("thinking"),
    ))


# 语音识别最终文本 → 自动对话；事件总线同步回调，零额外依赖。
subscribe(VOICE_TRANSCRIPT, _on_voice_transcript)

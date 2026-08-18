"""事件总线（南桥）：进程内发布-订阅，广播型交互的解耦通道。

主板隐喻：南桥管「低速广播通知」。与北桥（能力总线，get_facade 点对点调用）
分工：**要结果的走能力总线，不要结果的走事件总线**。

- emit(event_type, payload)：同步分发，单个订阅方异常不影响其余（降级隔离）。
- subscribe(event_type, handler)：返回取消订阅函数；handler 可为同步或 async
  （async 用 asyncio.run 执行，保证同步 emit 语义）。
- 订阅表 + 事件审计（最近 N 条），供 BIOS 健康报告展示。
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections import deque
from typing import Any, Callable

_LOGGER = logging.getLogger(__name__)

# 事件类型常量（§14.3）：集中声明便于消费方引用，避免魔法字符串。
ENTITY_DELETED = "entity.deleted"
AFFINITY_SETTLED = "affinity.settled"
TOOL_REGISTERED = "tool.registered"
TOOL_UNREGISTERED = "tool.unregistered"
VOICE_SESSION_START = "voice.session_start"
VOICE_SESSION_END = "voice.session_end"
# STT 砖新增事件（规格文档 §3.5）：ASR 最终文本 / 中间结果 / VAD 状态 / 打断信号。
VOICE_TRANSCRIPT = "voice.transcript"
VOICE_PARTIAL = "voice.partial"
VOICE_INTERRUPTION = "voice.interruption"
VOICE_VAD_STATE = "voice.vad_state"
# chat 砖对话完成后发布（规格 §12 接线点）：负载含 {text: 回复, voice_text: 原始语音文本}。
VOICE_REPLY_READY = "voice.reply_ready"
# 逐句并行合成的音频块（LLM 流式边生成边合成）：负载含 {seq, text, audio: bytes}，播放端按 seq 排序。
VOICE_TTS_CHUNK = "voice.tts_audio_chunk"
WATCHDOG_TIMEOUT = "watchdog.timeout"
TRUST_BOMB_DETECTED = "trust.bomb_detected"
# 存储砖管理芯片事件（M2-M4）：配额超出 / 清理 / 归档 / 审计。
STORAGE_QUOTA_EXCEEDED = "storage.quota_exceeded"
STORAGE_CLEANUP = "storage.cleanup"
STORAGE_ARCHIVE = "storage.archive"

# 审计保留条数
_AUDIT_MAX = 200

_subscribers: dict[str, list[Callable]] = {}
_audit: deque = deque(maxlen=_AUDIT_MAX)


def subscribe(event_type: str, handler: Callable) -> Callable[[], None]:
    """订阅事件；返回取消订阅函数（幂等）。"""
    _subscribers.setdefault(event_type, []).append(handler)
    return lambda: unsubscribe(event_type, handler)


def unsubscribe(event_type: str, handler: Callable) -> None:
    """取消订阅（幂等，不存在则忽略）。"""
    handlers = _subscribers.get(event_type)
    if not handlers:
        return
    try:
        handlers.remove(handler)
    except ValueError:
        pass


def emit(event_type: str, payload: Any = None) -> list[Any]:
    """广播事件：同步分发到所有订阅方，单个异常隔离（不影响其余与调用方）。

    返回各订阅方结果列表（异常结果记为错误文本）。无订阅方时静默返回空。
    """
    handlers = list(_subscribers.get(event_type, []))
    results: list[Any] = []
    for handler in handlers:
        try:
            result = handler(payload)
            if inspect.iscoroutine(result):
                result = asyncio.run(result)
            results.append(result)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("事件 %s 订阅方异常: %s", event_type, exc)
            results.append(f"error: {exc}")
    _audit.append({"ts": time.time(), "type": event_type, "handlers": len(handlers)})
    return results


def subscriber_count(event_type: str) -> int:
    """某事件的订阅方数量（健康报告用）。"""
    return len(_subscribers.get(event_type, []))


def audit_snapshot() -> list[dict]:
    """事件审计快照（最近 N 条，BIOS 报告用）。"""
    return list(_audit)

"""结构化日志与请求关联 —— 低延迟优先的可观测层。

设计取舍（个人低延迟 ↔ 企业稳定度）
------------------------------------
1. **热路径零阻塞**：日志经 `QueueHandler` 入队，真正的 I/O（写终端/文件）在
   后台线程（`QueueListener`）完成。调用 `log_event` 只做一次入队，绝不因为写日志
   拖慢生成 —— 这是"低延迟"侧的硬要求。
2. **默认安静、按需付出**：未开启对应级别时 `log_event` 只是一次整数比较，
   **无任何 I/O、无线程**。级别由环境变量 `PALM_LLM_LOG` 控制（默认 `WARNING`：
   错误与重试可见，`INFO`/`DEBUG` 需显式打开）—— 与"个人低延迟"一致：想看细节，
   才为它付代价。
3. **一次请求一个 `request_id`**：靠 `contextvars` 跨 `await` 传播，无需逐层传参。
   provider 被直接调用（无服务层）时，`ensure_request_id()` 兜底生成。
4. **绝不记录密钥与正文**：`log_event` 只落显式传入的结构化字段，不自动抓取
   messages —— prompt 正文可能含用户隐私与人设，不进日志是纪律不是偏好。
"""
from __future__ import annotations

import atexit
import contextvars
import logging
import logging.handlers
import os
import queue
import sys
import time
import uuid
from typing import Optional

_LOGGER_NAME = "palm_llm"
_LEVELNO = {"debug": 10, "info": 20, "warning": 30, "error": 40, "critical": 50}

# 进程级默认级别：环境变量覆盖，非法值回落 WARNING（不因配错而丢日志）
_env_level = (os.environ.get("PALM_LLM_LOG") or "WARNING").lower()
_LEVEL = _env_level if _env_level in _LEVELNO else "warning"

_request_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "palm_llm_request_id", default="-")
_configured = False
_listener: Optional[logging.handlers.QueueListener] = None


# ─────────────────────────── request_id ───────────────────────────
def new_request_id() -> str:
    """生成短请求 id（12 位十六进制，够用且不喧宾夺主）。"""
    return uuid.uuid4().hex[:12]


def get_request_id() -> str:
    return _request_id.get()


def set_request_id(rid: Optional[str]) -> contextvars.Token:
    """显式设置本次请求 id（服务层在回合边界调用）；空值则新生成。"""
    return _request_id.set(rid or new_request_id())


def ensure_request_id() -> str:
    """返回本次请求 id；尚未设置时新生成一个（provider 直连场景的兜底）。"""
    rid = _request_id.get()
    if rid == "-":
        rid = new_request_id()
        _request_id.set(rid)
    return rid


# ─────────────────────────── 日志装配 ───────────────────────────
class _RequestFilter(logging.Filter):
    """把当前上下文的 request_id 注入每条记录（格式串才能打出它）。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get()
        return True


class _Formatter(logging.Formatter):
    """单行结构化：`时间 级别 [request_id] 事件 key=value …`。"""

    def format(self, record: logging.LogRecord) -> str:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(record.created))
        line = (f"{stamp}.{int(record.msecs):03d} {record.levelname:<7} "
                f"[{getattr(record, 'request_id', '-')}] {record.getMessage()}")
        ctx = getattr(record, "ctx", None)
        if ctx:
            line += "  " + " ".join(f"{k}={v}" for k, v in ctx.items())
        return line


def configure_logging(level: Optional[str] = None, stream=None) -> logging.Logger:
    """幂等装配：结构化格式 + 队列异步输出。可重复调用以调整级别。

    第一次调用才创建后台线程；此后再调用只改级别，不重复起线程。
    """
    global _configured, _listener
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(_LEVELNO.get((level or _LEVEL).lower(), _LEVELNO["warning"]))
    if _configured:
        return logger
    sink = logging.StreamHandler(stream or sys.stderr)
    sink.setFormatter(_Formatter())
    sink.addFilter(_RequestFilter())
    log_queue: queue.SimpleQueue = queue.SimpleQueue()
    logger.addHandler(logging.handlers.QueueHandler(log_queue))
    logger.propagate = False                      # 不污染 root logger
    _listener = logging.handlers.QueueListener(
        log_queue, sink, respect_handler_level=False)
    _listener.start()
    atexit.register(_listener.stop)
    _configured = True
    return logger


def log_event(event: str, *, level: str = "info", **ctx) -> None:
    """记录一条结构化事件。

    未开启该级别时**零开销**（一次整数比较，不入队、不起线程）。
    """
    lvl = _LEVELNO.get(level.lower(), _LEVELNO["info"])
    if not _configured:
        if lvl < _LEVELNO[_LEVEL]:
            return
        configure_logging(_LEVEL)
    logger = logging.getLogger(_LOGGER_NAME)
    if logger.isEnabledFor(lvl):
        logger.log(lvl, event, extra={"ctx": ctx})


__all__ = [
    "new_request_id",
    "get_request_id",
    "set_request_id",
    "ensure_request_id",
    "configure_logging",
    "log_event",
]

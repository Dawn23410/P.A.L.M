"""后台任务调度器：让 AI 开子进程但必须闭环。

闭环语义（用户诉求）：
- AI 可以用 start_background_task 登记一个长任务（子进程由后端直接派生并脱离沙箱 job，
  不会被对话结束瞬间强杀）。
- 调度器心跳检测任务是否退出/超时；完成后**自动唤醒 AI**，把结果作为新上下文注入同会话，
  让 AI 继续处理或总结——后台任务不会"开了就消失"。
- 每个 task 最多唤醒 1 次；唤醒轮（agent_is_wakeup）内禁止再登记，防无限套娃。
- 前端经 GET /api/agent/events 订阅，未发新消息时也能收到唤醒后的回复。

唤醒回调由 brick 层在启动时注册（set_wakeup_handler），保持本模块与 Agent 解耦。
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Awaitable, Callable

_LOGGER = logging.getLogger(__name__)

# 唤醒回调签名：(conversation_id, model, reminder_text) -> 协程
WakeupHandler = Callable[[str, str, str], Awaitable[None]]


@dataclass
class BackgroundTask:
    task_id: str
    conversation_id: str
    model: str
    command: str
    description: str
    proc: object  # subprocess.Popen
    log_path: str
    timeout: float = 3600.0
    started_at: float = 0.0
    is_done: bool = False
    is_woken_up: bool = False
    output: str = ""
    exit_code: int | None = None


class BackgroundTaskScheduler:
    """单例心跳调度器。"""

    def __init__(self) -> None:
        self._tasks: dict[str, BackgroundTask] = {}
        self._session_queues: dict[str, asyncio.Queue] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wakeup_handler: WakeupHandler | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._heartbeat_interval = 5.0

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def set_wakeup_handler(self, handler: WakeupHandler) -> None:
        self._wakeup_handler = handler

    def register(
        self,
        conversation_id: str,
        model: str,
        command: str,
        description: str,
        proc: object,
        log_path: str,
        timeout: float = 3600.0,
    ) -> str:
        task_id = f"bg_{uuid.uuid4().hex[:8]}"
        bt = BackgroundTask(
            task_id=task_id,
            conversation_id=conversation_id,
            model=model,
            command=command,
            description=description,
            proc=proc,
            log_path=log_path,
            timeout=timeout,
            started_at=time.time(),
        )
        with self._lock:
            self._tasks[task_id] = bt
        self._ensure_thread()
        _LOGGER.info("登记后台任务 %s（会话 %s）：%s", task_id, conversation_id, command)
        return task_id

    def _ensure_thread(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._heartbeat, daemon=True)
            self._thread.start()

    def _read_output(self, bt: BackgroundTask) -> str:
        try:
            with open(bt.log_path, "r", encoding="utf-8", errors="replace") as f:
                return f.read()[:4000]
        except Exception:
            return ""

    def _heartbeat(self) -> None:
        while True:
            time.sleep(self._heartbeat_interval)
            with self._lock:
                items = list(self._tasks.values())
            for bt in items:
                if bt.is_done:
                    continue
                ret = bt.proc.poll()  # type: ignore[attr-defined]
                elapsed = time.time() - bt.started_at
                if ret is None and elapsed <= bt.timeout:
                    continue
                self._finalize_finished_task(bt, ret)

    def _finalize_finished_task(self, bt: BackgroundTask, exit_code: int | None) -> None:
        bt.is_done = True
        bt.exit_code = exit_code
        bt.output = self._read_output(bt)
        if exit_code is None:
            try:
                bt.proc.kill()  # type: ignore[attr-defined]
            except Exception:
                pass
        # 每个任务最多唤醒 1 次，且必须存在唤醒回调与事件循环
        if (
            not bt.is_woken_up
            and self._wakeup_handler is not None
            and self._loop is not None
        ):
            bt.is_woken_up = True
            reminder = self._build_reminder(bt)
            try:
                asyncio.run_coroutine_threadsafe(
                    self._wakeup_handler(bt.conversation_id, bt.model, reminder),
                    self._loop,
                )
            except Exception:
                _LOGGER.exception("唤醒后台任务 %s 失败", bt.task_id)

    @staticmethod
    def _build_reminder(bt: BackgroundTask) -> str:
        if bt.exit_code == 0:
            status = "已完成"
        elif bt.exit_code is None:
            status = "已超时强杀"
        else:
            status = f"已退出（码={bt.exit_code}）"
        lines = [
            f"[系统自动提醒] 后台任务 {bt.task_id} {status}。",
            f"命令：{bt.command}",
            f"说明：{bt.description}",
        ]
        if bt.output.strip():
            lines.append("任务输出（截取）：\n" + bt.output)
        lines.append(
            "请基于以上结果继续完成用户的需求，或给出总结。"
            "本轮为自动唤醒，请勿再次登记后台任务，直接处理或总结即可。"
        )
        return "\n".join(lines)

    # ── SSE 会话事件队列 ─────────────────────────────────────────

    def get_queue(self, conversation_id: str) -> asyncio.Queue:
        q = self._session_queues.get(conversation_id)
        if q is None:
            q = asyncio.Queue()
            self._session_queues[conversation_id] = q
        return q

    def push_event(self, conversation_id: str, sse_line: str) -> None:
        # 无人订阅的会话直接丢弃（避免队列无限增长），结果已留痕于记忆/历史
        q = self._session_queues.get(conversation_id)
        if q is not None:
            try:
                q.put_nowait(sse_line)
            except Exception:
                pass

    def subscribe(self, conversation_id: str) -> asyncio.Queue:
        return self.get_queue(conversation_id)

    def unsubscribe(self, conversation_id: str) -> None:
        self._session_queues.pop(conversation_id, None)


# 全局单例
scheduler = BackgroundTaskScheduler()

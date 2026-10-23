"""Agent 运行轨迹追踪（P5 之「追踪」）。

提供 LangSmith / OpenAI Agents 式的可观测性：记录一次运行的全过程
（思考/工具调用/工具结果/文本增量/终态/时长/错误），落盘 JSONL 供事后排查，
并缓存最近一次轨迹到 agent._last_trace。

设计原则：纯增量、零侵入——仅在 core.run 包裹事件流，任何异常都不影响主流程。
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

from palm._core.paths import brick_local

_LOGGER = logging.getLogger(__name__)

# 轨迹落盘路径：砖内 data/agent_traces/，位置无关、可随意移动；单文件超 5MB 自动轮转
_TRACE_DIR = brick_local(__file__, "data", "agent_traces")
_TRACE_PATH = os.path.join(_TRACE_DIR, "agent_traces.jsonl")
_TRACE_MAX_SIZE = 5 * 1024 * 1024  # 5MB


@dataclass
class RunTrace:
    """单次 Agent 运行的轨迹快照。"""
    run_id: str
    conversation_id: str
    model: str
    tool_mode: str
    start_ts: float = 0.0
    end_ts: float = 0.0
    steps: list[dict] = field(default_factory=list)
    final_text: str = ""
    error: str = ""
    usage: dict[str, int] = field(default_factory=dict)

    @property
    def duration_ms(self) -> float:
        return round((self.end_ts - self.start_ts) * 1000, 1) if self.end_ts else 0.0

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "conversation_id": self.conversation_id,
            "model": self.model,
            "tool_mode": self.tool_mode,
            "start_ts": self.start_ts,
            "end_ts": self.end_ts,
            "duration_ms": self.duration_ms,
            "steps": self.steps,
            "final_text": self.final_text,
            "error": self.error,
            "usage": self.usage,
        }


class RunTracer:
    """累积一次运行的事件为 RunTrace。"""

    def __init__(self) -> None:
        self._trace = RunTrace(
            run_id=f"run_{int(time.time()*1000)}",
            conversation_id="",
            model="",
            tool_mode="",
        )

    def start(self, conversation_id: str, model: str, tool_mode: str) -> None:
        self._trace.conversation_id = conversation_id
        self._trace.model = model
        self._trace.tool_mode = tool_mode
        self._trace.start_ts = time.time()

    def record(self, event: Any) -> None:
        """记录一个 AgentEvent 到轨迹（按类型提取摘要）。"""
        ev_type = getattr(event, "type", "unknown")
        content = getattr(event, "content", "") or ""
        tool_output = getattr(event, "tool_output", "") or ""
        tool_name = getattr(event, "tool_name", "") or ""
        snippet = (content or tool_output or "")[:200]
        self._trace.steps.append({
            "ts": round(time.time(), 3),
            "type": ev_type,
            "name": tool_name or ev_type,
            "snippet": snippet,
        })
        if ev_type == "delta":
            self._trace.final_text += content
        elif ev_type == "error":
            self._trace.error = content
        elif ev_type == "done":
            usage = getattr(event, "usage", None)
            if usage:
                self._trace.usage = dict(usage)

    def finish(self) -> RunTrace:
        self._trace.end_ts = time.time()
        return self._trace

    def to_dict(self) -> dict:
        return self.finish().to_dict()


def persist_trace(trace_dict: dict) -> None:
    """防御性落盘：追加一行 JSON 到 Data/agent_traces.jsonl；任何异常都静默跳过。

    单文件超 5MB 时自动轮转：旧文件加 .1 后缀，新文件从空开始。
    """
    try:
        os.makedirs(_TRACE_DIR, exist_ok=True)
        # 日志轮转：超限时归档旧文件
        if os.path.exists(_TRACE_PATH) and os.path.getsize(_TRACE_PATH) > _TRACE_MAX_SIZE:
            rotated = _TRACE_PATH + ".1"
            try:
                if os.path.exists(rotated):
                    os.remove(rotated)
                os.rename(_TRACE_PATH, rotated)
            except OSError:
                pass  # 轮转失败不阻断写入
        with open(_TRACE_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(trace_dict, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("轨迹落盘失败（跳过）: %s", exc)

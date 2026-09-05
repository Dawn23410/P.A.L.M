"""Worker 轨迹存储（外骨骼版，移植自 palm/services/agent/dual/trace_store.py）。

Worker 执行任务的完整轨迹（思维链 / 工具调用 / 工具结果 / 输出 / 计划 / 干预）逐条写入，
Boss 经摘要/关键词检索按需拉取，而非一次性灌入全部上下文。
线程安全：Worker 后台线程写入、Boss 主线程检索，用 threading.Lock 保护。
与归档差异：移除 palm._core.interop 向量后端依赖（mentalcore 不注册记忆砖），
统一走关键词评分检索（归档降级路径，行为一致）。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

# 轨迹类型枚举（与归档一致）
T_THOUGHT = "thought"          # 思维链 / 推理过程
T_TOOL_CALL = "tool_call"      # 工具调用（名称 + 参数）
T_TOOL_RESULT = "tool_result"  # 工具执行结果
T_OUTPUT = "output"            # 阶段性输出 / 最终回答
T_PLAN = "plan"                # 规划步骤
T_ERROR = "error"              # 错误信息
T_INTERVENTION = "intervention"  # 干预指令（来自 Boss）


@dataclass
class TraceEntry:
    """单条轨迹记录。"""

    step: int
    entry_type: str
    content: str
    timestamp: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "step": self.step,
            "type": self.entry_type,
            "content": self.content[:2000],  # 截断防超长
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }

    def to_text(self) -> str:
        """转为可检索的纯文本（关键词匹配用）。"""
        prefix = f"[步骤{self.step}][{self.entry_type}]"
        if self.entry_type == T_TOOL_CALL:
            tool_name = self.metadata.get("tool_name", "")
            return f"{prefix} 调用工具 {tool_name}: {self.content}"
        if self.entry_type == T_TOOL_RESULT:
            tool_name = self.metadata.get("tool_name", "")
            return f"{prefix} 工具 {tool_name} 返回: {self.content}"
        if self.entry_type == T_PLAN:
            return f"{prefix} 计划: {self.content}"
        if self.entry_type == T_ERROR:
            return f"{prefix} 错误: {self.content}"
        if self.entry_type == T_INTERVENTION:
            return f"{prefix} 干预: {self.content}"
        return f"{prefix} {self.content}"


class TraceStore:
    """Worker 轨迹存储：分片写入 + 关键词检索。

    生命周期：一个 Worker 任务对应一个 TraceStore 实例。
    Boss 通过 Worker 插槽持有引用，在对话中按需检索。
    """

    def __init__(self, task_id: str = "", task_goal: str = "") -> None:
        self._task_id = task_id
        self._task_goal = task_goal
        self._entries: list[TraceEntry] = []
        self._lock = threading.Lock()
        self._step_counter = 0
        self._started_at = time.time()
        self._finished = False
        # (text, entry) 关键词索引
        self._index: list[tuple[str, TraceEntry]] = []

    @property
    def task_goal(self) -> str:
        return self._task_goal

    @property
    def is_finished(self) -> bool:
        return self._finished

    @property
    def entry_count(self) -> int:
        with self._lock:
            return len(self._entries)

    @property
    def last_entry_type(self) -> str:
        with self._lock:
            return self._entries[-1].entry_type if self._entries else ""

    def add(self, entry_type: str, content: str, metadata: dict | None = None) -> TraceEntry:
        """写入一条轨迹，返回创建的 TraceEntry。"""
        with self._lock:
            self._step_counter += 1
            entry = TraceEntry(
                step=self._step_counter,
                entry_type=entry_type,
                content=content,
                metadata=metadata or {},
            )
            self._entries.append(entry)
            self._index.append((entry.to_text(), entry))
        return entry

    def query(self, keyword: str, top_k: int = 5) -> list[TraceEntry]:
        """关键词检索：按评分拉取最相关的 top_k 条轨迹（归档降级路径）。"""
        with self._lock:
            if not self._entries or not keyword:
                return []
            kw = keyword.lower()
            scored: list[tuple[int, TraceEntry]] = []
            for text, entry in self._index:
                score = self._keyword_score(text.lower(), kw)
                if score > 0:
                    scored.append((score, entry))
            scored.sort(key=lambda x: x[0], reverse=True)
            return [e for _, e in scored[:top_k]]

    def get_recent(self, n: int = 10) -> list[TraceEntry]:
        """获取最近 n 条轨迹（按写入顺序倒取）。"""
        with self._lock:
            if len(self._entries) <= n:
                return list(self._entries)
            return list(self._entries[-n:])

    def get_summary(self) -> str:
        """生成轨迹摘要（供 Boss 上下文注入）：任务目标 + 总步数 + 最近 5 条 + 状态。"""
        with self._lock:
            if not self._entries:
                return f"任务「{self._task_goal}」尚未产生轨迹。"
            lines = [f"Worker 任务：{self._task_goal}",
                     f"已执行 {len(self._entries)} 步" +
                     ("（已完成）" if self._finished else "（进行中）")]
            for e in self._entries[-5:]:
                tool_hint = ""
                if e.entry_type in (T_TOOL_CALL, T_TOOL_RESULT):
                    tn = e.metadata.get("tool_name", "")
                    if tn:
                        tool_hint = f"[{tn}] "
                lines.append(f"  步骤{e.step} {tool_hint}{e.content[:120]}")
            return "\n".join(lines)

    def get_full_trace_text(self, max_entries: int = 50) -> str:
        """获取完整轨迹文本（截断防超长）。"""
        with self._lock:
            entries = self._entries if len(self._entries) <= max_entries else self._entries[-max_entries:]
            lines = [e.to_text() for e in entries]
            header = f"任务：{self._task_goal}（共 {len(self._entries)} 步）"
            return header + "\n" + "\n".join(lines)

    def mark_finished(self) -> None:
        with self._lock:
            self._finished = True

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._index.clear()
            self._step_counter = 0
            self._finished = False

    @staticmethod
    def _keyword_score(text: str, keyword: str) -> int:
        """简单关键词评分：完全匹配 > 词组匹配 > 单字匹配。"""
        if not keyword:
            return 0
        score = 0
        if keyword in text:
            score += 10
        for w in keyword.split():
            if len(w) >= 2 and w in text:
                score += 3
        return score

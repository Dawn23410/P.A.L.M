"""Worker 轨迹存储 —— 分片记录 + 语义检索。

Worker（专业 Agent）执行任务时的完整轨迹（思维链 / 工具调用 / 工具结果 / 输出 / 计划）
逐条写入此存储。Boss（主 Agent）通过语义检索按需拉取相关片段，而非一次性灌入全部上下文。

检索策略：
1. 优先借用 memory 砖的 VectorMemory 做语义向量检索（命中率高、token 省）；
2. VectorMemory 不可用时降级为关键词子串匹配（零依赖兜底）。

线程安全：Worker 在后台线程执行，Boss 可能在主线程同时检索，用 threading.Lock 保护。
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

_LOGGER = logging.getLogger(__name__)

# 轨迹类型枚举
T_THOUGHT = "thought"        # 思维链 / 推理过程
T_TOOL_CALL = "tool_call"    # 工具调用（名称 + 参数）
T_TOOL_RESULT = "tool_result"  # 工具执行结果
T_OUTPUT = "output"          # 阶段性输出 / 最终回答
T_PLAN = "plan"              # 规划步骤
T_ERROR = "error"            # 错误信息
T_INTERVENTION = "intervention"  # 干预指令（来自 Boss）


@dataclass
class TraceEntry:
    """单条轨迹记录。"""

    step: int                           # 步骤序号（从 1 开始）
    entry_type: str                     # T_THOUGHT / T_TOOL_CALL / ...
    content: str                        # 文本内容
    timestamp: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)  # 工具名、参数、耗时等额外信息

    def to_dict(self) -> dict:
        return {
            "step": self.step,
            "type": self.entry_type,
            "content": self.content[:2000],  # 截断防超长
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }

    def to_text(self) -> str:
        """转为可检索的纯文本（供向量检索 / 关键词匹配）。"""
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
    """Worker 轨迹存储：分片写入 + 语义检索。

    生命周期：一个 Worker 任务对应一个 TraceStore 实例。
    Boss 通过 coordinator 持有引用，在对话中按需检索。
    """

    def __init__(
        self,
        task_id: str = "",
        task_goal: str = "",
        vector_persist_dir: str | None = None,
    ) -> None:
        self._task_id = task_id
        self._task_goal = task_goal
        self._entries: list[TraceEntry] = []
        self._lock = threading.Lock()
        self._step_counter = 0
        self._started_at = time.time()
        self._finished = False

        # 向量检索后端（可选）：尝试借用 memory 砖的 VectorMemory
        self._vector_store = None
        self._vector_index: list[tuple[str, TraceEntry]] = []  # (text, entry) 降级用
        try:
            from palm._core.interop import get_memory_api
            api = get_memory_api()
            if api is not None and vector_persist_dir:
                self._vector_store = api.VectorMemory(
                    persist_dir=vector_persist_dir,
                    collection=f"trace_{task_id}" if task_id else "trace_default",
                )
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("TraceStore 向量后端不可用，降级关键词检索: %s", exc)
            self._vector_store = None

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
        """最后一条轨迹的类型（供状态查询快速判断 Worker 进度）。"""
        with self._lock:
            return self._entries[-1].entry_type if self._entries else ""

    def add(
        self,
        entry_type: str,
        content: str,
        metadata: dict | None = None,
    ) -> TraceEntry:
        """写入一条轨迹。返回创建的 TraceEntry。"""
        with self._lock:
            self._step_counter += 1
            entry = TraceEntry(
                step=self._step_counter,
                entry_type=entry_type,
                content=content,
                metadata=metadata or {},
            )
            self._entries.append(entry)
            text = entry.to_text()
            self._vector_index.append((text, entry))

            # 向量后端可用时同步写入（轻量文本，不阻塞）
            if self._vector_store is not None:
                try:
                    self._vector_store.add(text, metadata={
                        "step": entry.step,
                        "type": entry.entry_type,
                        "task_id": self._task_id,
                    })
                except Exception as exc:  # noqa: BLE001
                    _LOGGER.debug("向量写入失败（降级关键词可用）: %s", exc)

        return entry

    def query(self, keyword: str, top_k: int = 5) -> list[TraceEntry]:
        """语义检索：按关键词拉取最相关的 top_k 条轨迹。

        优先走向量检索；不可用时降级为关键词子串匹配。
        """
        with self._lock:
            if not self._entries:
                return []

            # 路径 A：向量语义检索
            if self._vector_store is not None:
                try:
                    results = self._vector_store.search(keyword, top_k=top_k)
                    if results:
                        # results 是 [(text, score, metadata), ...]
                        step_map = {e.step: e for e in self._entries}
                        matched = []
                        for r in results:
                            meta = r[2] if len(r) > 2 else {}
                            step = meta.get("step", 0)
                            if step in step_map:
                                matched.append(step_map[step])
                        if matched:
                            return matched[:top_k]
                except Exception as exc:  # noqa: BLE001
                    _LOGGER.debug("向量检索失败，降级关键词: %s", exc)

            # 路径 B：关键词子串匹配（降级兜底）
            kw_lower = keyword.lower()
            scored: list[tuple[int, TraceEntry]] = []
            for text, entry in self._vector_index:
                score = self._keyword_score(text.lower(), kw_lower)
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
        """生成轨迹摘要（供 Boss 上下文注入）。

        结构：任务目标 + 总步数 + 最近 5 条轨迹概述 + 当前状态。
        """
        with self._lock:
            if not self._entries:
                return f"任务「{self._task_goal}」尚未产生轨迹。"

            lines = [f"📋 Worker 任务：{self._task_goal}"]
            lines.append(f"已执行 {len(self._entries)} 步" +
                         ("（已完成）" if self._finished else "（进行中）"))

            # 最近 5 条轨迹概述
            recent = self._entries[-5:]
            for e in recent:
                tag = {
                    T_THOUGHT: "💭",
                    T_TOOL_CALL: "🔧",
                    T_TOOL_RESULT: "📤",
                    T_OUTPUT: "✅",
                    T_PLAN: "📋",
                    T_ERROR: "❌",
                    T_INTERVENTION: "⚡",
                }.get(e.entry_type, "•")
                tool_hint = ""
                if e.entry_type in (T_TOOL_CALL, T_TOOL_RESULT):
                    tn = e.metadata.get("tool_name", "")
                    if tn:
                        tool_hint = f"[{tn}] "
                lines.append(f"  {tag} 步骤{e.step} {tool_hint}{e.content[:120]}")

            return "\n".join(lines)

    def get_full_trace_text(self, max_entries: int = 50) -> str:
        """获取完整轨迹文本（截断防超长）。"""
        with self._lock:
            entries = self._entries if len(self._entries) <= max_entries else self._entries[-max_entries:]
            lines = [e.to_text() for e in entries]
            header = f"任务：{self._task_goal}（共 {len(self._entries)} 步）"
            return header + "\n" + "\n".join(lines)

    def mark_finished(self) -> None:
        """标记 Worker 任务已完成。"""
        with self._lock:
            self._finished = True

    def clear(self) -> None:
        """清空轨迹（供 coordinator 在任务结束后回收）。"""
        with self._lock:
            self._entries.clear()
            self._vector_index.clear()
            self._step_counter = 0
            self._finished = False

    @staticmethod
    def _keyword_score(text: str, keyword: str) -> int:
        """简单关键词评分：完全匹配 > 词组匹配 > 单字匹配。"""
        if not keyword:
            return 0
        score = 0
        # 完全包含
        if keyword in text:
            score += 10
        # 拆词匹配
        words = keyword.split()
        for w in words:
            if len(w) >= 2 and w in text:
                score += 3
        return score
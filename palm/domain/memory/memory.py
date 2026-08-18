"""
记忆层 —— 统一接口，内部集成五子模块 + 短期记忆（语义筛选注入）。

短期记忆策略（近 50 轮对话）：
- 近期 5 轮：压缩提取后**完整注入**（[用户]/[助手] 格式 + 要点提取）
- 5-50 轮：仅注入**语义相关**的内容（关键词重叠 ≥ 15%）
- 超出 50 轮的部分由 ArchivedMemory 处理（幂律衰减 + 预算裁剪）
"""
from __future__ import annotations

import logging
import re
from typing import Any

from .base import Conversation
from .core_memory import CoreMemory
from .archived_memory import ArchivedMemory, DecayCalculator
from .token_budget import TokenBudgetAllocator
from .memory_writer import MemoryWriter
from .vector_memory import VectorMemory
from palm._core.interop import get_roleplay_api
from palm._core.emotion import extract_emotion_vector

_LOGGER = logging.getLogger(__name__)


def _strip_roleplay_tone(text: str) -> str:
    """剥离角色语气（经 roleplay 砖；缺失时原样返回，降级安全）。"""
    api = get_roleplay_api()
    if api is not None:
        return api.strip_roleplay_tone(text)
    return text

# ── 短期记忆配置 ──
_SHORT_TERM_ROUNDS = 50       # 短期记忆覆盖最近 50 轮
_FULL_INJECT_ROUNDS = 3       # 近 3 轮完整注入
_RELEVANCE_THRESHOLD = 0.15   # 语义相关阈值：关键词重叠 ≥ 15%
_MAX_HISTORY_MSGS = _SHORT_TERM_ROUNDS * 2  # 每轮 2 条（user + assistant）

_COMPRESS_PROMPT = """你是一个对话压缩器。请把下面的「历史对话片段」压缩成一段简洁、事实导向的摘要。

必须保留：
- 用户的核心诉求、约束条件与明确表达的偏好
- 助手已完成的操作、关键结果/数据、已得出的结论
- 尚未解决或搁置的事项
可丢弃：寒暄、重复内容、冗长推理过程细节。

用中文、第三人称陈述，控制在 300 字以内。严禁编造未出现的信息。

历史对话片段：
{text}
"""


def _estimate_tokens(text: str) -> int:
    return max(1, int(len(text) / 1.5))


def _extract_keywords(text: str) -> set[str]:
    """从中文文本中提取字级 3-gram 作为语义指纹。

    使用连续汉字 3-gram，比词级分割更能容忍表述差异（如"帮我看看文件"
    与"帮我看看这个文件"共享 '帮我看'/'我看看' 等 gram）。
    """
    # 只保留汉字
    chars = re.findall(r"[\u4e00-\u9fff]", text)
    grams: set[str] = set()
    for i in range(len(chars) - 2):
        grams.add("".join(chars[i:i+3]))
    # 也取英文单词
    for w in re.findall(r"[a-zA-Z]{3,15}", text):
        grams.add(w.lower())
    return grams


def _compute_relevance(current_text: str, history_text: str) -> float:
    """计算当前输入与历史消息的语义相关度（基于关键词重叠率）。

    返回 0~1 的分数。
    """
    cur_keys = _extract_keywords(current_text)
    his_keys = _extract_keywords(history_text)
    if not cur_keys or not his_keys:
        return 0.0
    overlap = cur_keys & his_keys
    # 用当前输入的关键词总数作分母：当前输入中多大比例被历史内容匹配
    return len(overlap) / len(cur_keys)


def _compress_message(role: str, content: str, max_chars: int = 200) -> str:
    """压缩单条消息：保留开头关键信息，超出截断并加省略号。"""
    tag = "用户" if role == "user" else "助手"
    if len(content) <= max_chars:
        return f"[{tag}]{content}"
    return f"[{tag}]{content[:max_chars]}..."


class Memory:
    """统一记忆接口 —— 五子模块 + 短期记忆语义筛选 + 向量记忆。"""

    def __init__(self, max_rounds: int = _SHORT_TERM_ROUNDS, model_window: int = 128000,
                 persist_path: str | None = None, vector_persist_dir: str = "",
                 character_card=None, conversation_id: str = ""):
        # 会话 id 随向量 metadata 落盘，供删除会话时按 conv_id 精确定位清理（A2）。
        self._conversation_id = conversation_id
        # 五子模块
        self.core = CoreMemory(persist_path, character_card=character_card)
        self.archived = ArchivedMemory()
        self.decay = DecayCalculator()
        self.budget = TokenBudgetAllocator(model_window)
        self.writer = MemoryWriter(self.archived)
        # 向量记忆（ChromaDB 语义检索层）
        self.vector = VectorMemory(persist_dir=vector_persist_dir)
        # 短期记忆 —— 对话历史列表（最多 100 条 = 50 轮）
        self._history: list[dict] = []
        self._max_rounds = max_rounds
        # 滚动历史摘要（P4 上下文真压缩产物）：旧轮次经 LLM 摘要后在此累积，
        # 经 inject_system_context 回灌，避免硬性截断丢失长对话上下文。
        self._history_summary: str | None = None

    async def initialize(self) -> None:
        """加载持久化数据（好感度 + 近期对话 + 向量索引），恢复多轮连续性。"""
        await self.core.initialize()
        # 把归档记忆层注入 core，供记忆层幂律复苏（动态机制 resonance 侧）读取。
        self.core._archived = self.archived
        self._history = list(self.core._data.recent_history)
        # 初始化向量记忆（异步初始化，失败不阻塞）
        self.vector.initialize()

    async def shutdown(self) -> None:
        """落盘（好感度 + 近期对话 + 向量索引），按滑动窗口裁剪并清理过期归档。"""
        cap = _MAX_HISTORY_MSGS
        if len(self._history) > cap:
            self._history = self._history[-cap:]
        self.core._data.recent_history = list(self._history)
        try:
            removed = self.archived.prune()
            if removed:
                _LOGGER.info("归档记忆清理 %d 条过期低重要度条目", removed)
        except Exception as exc:
            _LOGGER.warning("归档记忆清理失败: %s", exc)
        # 关闭向量记忆
        self.vector.close()
        await self.core.shutdown()

    def add(self, role: str, content: str, metadata: dict | None = None,
            tool_calls: list | None = None, tool_call_id: str | None = None,
            images: list | None = None, reasoning: str = "") -> None:
        """写入一条对话记录到短期记忆，同时完整归档到长期记忆（保留原文）。

        支持原生工具调用所需的结构化字段：tool_calls（assistant 携带）、
        tool_call_id（tool 结果消息）。tool 角色消息（native 续调用）不参与去重，
        否则同工具结果会因 role+content 相同被吞掉，破坏 tool_call_id 配对。
        """
        msg: dict = {"role": role, "content": content}
        if tool_calls is not None:
            msg["tool_calls"] = tool_calls
        if reasoning:
            msg["reasoning"] = reasoning
        if tool_call_id is not None:
            msg["tool_call_id"] = tool_call_id
        if metadata:
            msg["metadata"] = metadata
        if images:
            msg["images"] = images
        # 去重：仅对普通 user/assistant 消息生效；tool 角色消息不去重。
        if role != "tool" and self._history and \
                self._history[-1].get("role") == role and self._history[-1].get("content") == content:
            return
        self._history.append(msg)
        # 滑动窗口裁剪到 50 轮
        if len(self._history) > _MAX_HISTORY_MSGS:
            self._history = self._history[-_MAX_HISTORY_MSGS:]

        # 完整归档 + 向量化（空 content 的 tool_calls 类消息不入库，避免脏数据）
        if content and content.strip():
            tag = "用户" if role == "user" else "助手"
            # 长期记忆只存事实、不存语气：非用户消息在归档/向量化前剥离角色语气，
            # 杜绝角色语气经长期记忆回灌形成污染闭环（短期历史保留原文以维持对话连贯）。
            clean = content if role == "user" else _strip_roleplay_tone(content)
            # 提取情绪向量（仅用户消息：捕获用户真实情绪状态用于非对称衰减）
            if role == "user":
                try:
                    valence, arousal, confidence = extract_emotion_vector(content)
                except Exception:
                    valence, arousal, confidence = 0.0, 0.0, 0.0
            else:
                valence, arousal, confidence = 0.0, 0.0, 0.0
            try:
                self.archived.add(f"[{tag}]{clean}", importance=4,
                                  valence=valence, arousal=arousal,
                                  emotion_confidence=confidence)
                # 同步写入向量记忆（异步最佳，但首次调用保证阻塞完成）
                if self.vector.is_ready:
                    self.vector.add(
                        f"[{tag}]{clean}",
                        metadata={"role": role, "importance": 4, "conv_id": self._conversation_id},
                    )
            except Exception as exc:
                _LOGGER.warning("记忆归档/向量化写入失败（降级跳过）: %s", exc)

    def get_raw_history(self) -> list[dict]:
        """返回短期记忆原文拷贝（含 tool 角色/tool_calls），供 native 模式原样拼 LLM 消息。"""
        return [dict(m) for m in self._history]

    def get_context(self, max_tokens: int = 4096) -> list[dict]:
        """返回拼入 prompt 的上下文列表（兼容原有接口）。"""
        return list(self._history)

    def clear(self) -> None:
        """清空对话历史（保留归档等持久数据）。"""
        self._history.clear()
        self._history_summary = None

    # ── 短期记忆注入 ─────────────────────────────────────

    def inject_system_context(self, include_short_term: bool = True) -> str:
        """组装完整系统上下文：核心记忆 + 短期记忆（语义筛选）+ 归档记忆（预算裁剪）。

        native 工具调用模式下对话历史以结构化消息（role/tool_calls）原样回灌给模型，
        不再需要把短期对话压缩注入 system，故 include_short_term=False 仅注入核心记忆
        + 归档，避免与 raw history 重复历史内容导致混淆。
        """
        core_ctx = self.core.inject_into_context()
        parts = [core_ctx]
        if self._history_summary:
            # P4：长对话压缩摘要——原生/ReAct 模式均经此回灌，补回被截断的旧上下文
            parts.append(f"[历史对话摘要]\n{self._history_summary}")
        if include_short_term:
            parts.append(self._build_short_term_context())
        archived_ctx = self._inject_archived_within_budget(self.budget.calculate().archived)
        parts.append(archived_ctx)
        return "\n\n".join(p for p in parts if p.strip())

    def _build_short_term_context(self) -> str:
        """按 5/50 策略构建短期记忆上下文。

        - 近 3 轮（最后 6 条消息）：全部压缩后注入
        - 3-50 轮（更早的消息）：仅注入与当前输入语义相关的内容
          （向量检索优先 → 3-gram 关键词兜底）
        """
        if not self._history:
            return ""
        latest_user = self._latest_user_anchor()
        vector_relevant = self._collect_vector_relevant_indices(latest_user)
        lines, recent_count, relevant_count = self._render_recent_lines(latest_user, vector_relevant)
        if not lines:
            return ""
        header = f"[短期记忆] 近{_FULL_INJECT_ROUNDS}轮完整({recent_count}条)"
        if relevant_count:
            header += f" + 相关历史({relevant_count}条)"
        lines.insert(0, header)
        return "\n".join(lines)

    def _latest_user_anchor(self) -> str:
        """取当前最新一条用户消息作为语义锚点。"""
        for msg in reversed(self._history):
            if msg.get("role") == "user":
                return msg.get("content", "")
        return ""

    def _collect_vector_relevant_indices(self, latest_user: str) -> set[int]:
        """向量检索与当前输入相关历史消息的原始下标集合（用于 3-50 轮过滤）。"""
        relevant: set[int] = set()
        if not (latest_user and self.vector.is_ready):
            return relevant
        try:
            results = self.vector.search(latest_user, top_k=20)
            # 用内容 hash 做匹配（避免同一内容被不同表述的 3-gram 漏掉）
            for vr in results:
                content = vr.get("content", "")
                for idx, msg in enumerate(self._history):
                    tag = "用户" if msg.get("role") == "user" else "助手"
                    if f"[{tag}]{msg.get('content', '')}" == content:
                        relevant.add(idx)
        except Exception:
            pass
        return relevant

    def _render_recent_lines(self, latest_user: str, vector_relevant: set[int]) -> tuple[list[str], int, int]:
        """从新到旧遍历历史，按 5/50 策略产出注入行及计数。"""
        lines: list[str] = []
        recent_count = 0
        relevant_count = 0
        for i, msg in enumerate(reversed(self._history)):
            role = msg.get("role", "")
            content = msg.get("content", "")
            if not content.strip():
                continue
            orig_idx = len(self._history) - 1 - i  # 原始下标
            if i < _FULL_INJECT_ROUNDS * 2:
                lines.append(_compress_message(role, content))
                recent_count += 1
            else:
                # 3-50 轮：向量匹配优先，3-gram 兜底
                is_relevant = orig_idx in vector_relevant
                if not is_relevant and latest_user:
                    is_relevant = _compute_relevance(latest_user, content) >= _RELEVANCE_THRESHOLD
                if is_relevant:
                    lines.append(_compress_message(role, content, max_chars=150))
                    relevant_count += 1
        return lines, recent_count, relevant_count

    def _inject_archived_within_budget(self, budget_tokens: int) -> str:
        """在 Token 预算内尽力注入归档记忆，超出则逐步缩减条数。"""
        top_k = self.archived._top_k
        while top_k > 1:
            text = self.archived.inject_into_context(top_k)
            if _estimate_tokens(text) <= budget_tokens:
                return text
            top_k -= 2
        return self.archived.inject_into_context(1)

    # ── 原始接口 ─────────────────────────────────────────

    def record_conversation(self, user_msg: str, agent_msg: str) -> None:
        """记录完整对话+记忆写入决策。"""
        self.add("user", user_msg)
        self.add("assistant", agent_msg)

        items = self.writer.detect_event(user_msg)
        if items:
            _LOGGER.info("记忆写入: %d 条", len(items))

        if "我叫" in user_msg:
            self.core.update_profile(user_msg)

    def search_memory(self, query: str, top_k: int = 5) -> list:
        """混合检索：向量语义优先 + 关键词兜底。"""
        # 1) 向量检索
        if self.vector.is_ready:
            vector_results = self.vector.search(query, top_k=top_k)
            if vector_results:
                _LOGGER.info("向量检索命中 %d 条", len(vector_results))
                return [
                    {"content": r["content"], "score": r["score"]}
                    for r in vector_results
                ]

        # 2) 关键词兜底
        _LOGGER.info("向量检索未命中，回退关键词匹配")
        return self.archived.search(query, top_k)

    def record_failure(self, goal: str, step_desc: str, error: str) -> None:
        text = (
            f"[失败经验] 目标「{goal}」在步骤「{step_desc}」失败：{error}。"
            f"后续应避开该路径或改用其它工具。"
        )
        try:
            self.archived.add(_strip_roleplay_tone(text), importance=6)
        except Exception as exc:
            _LOGGER.warning("记录失败经验失败: %s", exc)

    def get_affinity(self) -> float:
        return self.core.affinity

    def set_affinity(self, value: float) -> None:
        self.core.set_affinity(value + self.core.affinity)

    # ── 上下文真压缩（P4） ─────────────────────────────────

    def get_history_summary(self) -> str | None:
        """返回当前滚动历史摘要（无则 None）。"""
        return self._history_summary

    async def compress_old_turns(self, llm_stream_fn, model: str,
                                 keep_recent_msgs: int = 12) -> bool:
        """上下文真压缩：把超出 Token 预算的旧轮次摘要化，避免硬性截断丢失上下文。

        触发条件：历史 Token 量超过模型窗口 50%。摘要经 LLM 生成并吸收既有摘要，
        旧消息从 _history 移除（保留最近若干轮原文），摘要经 inject_system_context 回灌。
        切分对齐到「用户消息」边界，保证 native 模式的 tool_call_id 配对不被破坏。
        返回是否实际执行了压缩。
        """
        if not self._history:
            return False
        total_tokens = sum(_estimate_tokens(m.get("content", "")) for m in self._history)
        # 仅当历史确实超出预算才压缩；小对话保持原文，零额外 LLM 开销
        if total_tokens <= int(self.budget.model_window * 0.5):
            return False
        # 从末尾向前累计 Token，定位近期原文的切分点（至少保留 keep_recent_msgs 条）
        cut = len(self._history)
        acc = 0
        target = int(self.budget.model_window * 0.5)
        while cut > keep_recent_msgs and acc <= target:
            cut -= 1
            acc += _estimate_tokens(self._history[cut].get("content", ""))
        # 对齐到用户消息边界：保证切分后 recent 以用户消息开头，旧片段内部 tool 配对完整
        while cut > 0 and self._history[cut].get("role") != "user":
            cut -= 1
        old = self._history[:cut]
        recent = self._history[cut:]
        if not old:
            return False
        # 渲染旧片段（既有摘要一并喂入，滚动吸收避免丢失）
        lines: list[str] = []
        if self._history_summary:
            lines.append(f"[既有摘要]{self._history_summary}")
        tag_map = {"user": "用户", "assistant": "助手", "tool": "工具", "system": "系统"}
        for m in old:
            content = (m.get("content", "") or "")[:600]
            if not content.strip():
                continue
            lines.append(f"[{tag_map.get(m.get('role', ''), m.get('role', ''))}]{content}")
        prompt = _COMPRESS_PROMPT.format(text="\n".join(lines))
        messages = [
            {"role": "system", "content": "你是对话压缩器，只输出摘要文本。"},
            {"role": "user", "content": prompt},
        ]
        summary = await self._stream_llm_text(llm_stream_fn, model, messages)
        if not summary.strip():
            return False
        self._history_summary = summary.strip()
        self._history = recent
        return True

    async def _stream_llm_text(self, llm_stream_fn, model: str, messages: list[dict]) -> str:
        """无工具地调用 LLM 取纯文本（供压缩等内部判断），累积流式输出。"""
        collected = ""
        try:
            async for chunk in llm_stream_fn(messages, model):
                if isinstance(chunk, dict):
                    content = chunk.get("content") or ""
                else:
                    content = getattr(chunk, "content", None) or getattr(chunk, "delta", "") or ""
                if content:
                    collected += content
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("压缩 LLM 调用异常（降级跳过）: %s", exc)
        return collected


def create_memory(memory_type: str = "buffer", **kwargs) -> Memory:
    return Memory(**kwargs)
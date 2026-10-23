"""语义工具匹配器（移植自 palm/services/agent/tool_matcher.py，适配 ToolSpec）。

不用外部向量库/嵌入模型：仅关键词 + 描述词频评分，零外部依赖下达到够用的
语义相关性排序——按用户输入筛出 Top-K 工具，缩小注入模型的工具暴露面
（安全 + 省 token），对齐归档 ToolMatcher 行为。
"""
from __future__ import annotations

import re
from typing import Any

# 常见停用词（中文+英文），避免噪声干扰评分
_STOP_WORDS = {
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人",
    "都", "一", "一个", "上", "也", "很", "到", "说", "要", "去",
    "你", "会", "着", "没有", "看", "好", "自己", "这",
    "the", "a", "an", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "can", "could", "should", "with", "for", "and", "or",
}


def _tokenize(text: str) -> set[str]:
    """将文本拆为 token 集合（中文单字 + 双字组合 + 英文单词）。"""
    low = (text or "").lower()
    tokens: set[str] = set()
    for c in low:
        if "\u4e00" <= c <= "\u9fff" and c not in _STOP_WORDS:
            tokens.add(c)
    chars = [c for c in low if "\u4e00" <= c <= "\u9fff"]
    for i in range(len(chars) - 1):
        bigram = chars[i] + chars[i + 1]
        if bigram not in _STOP_WORDS:
            tokens.add(bigram)
    for w in re.findall(r"[a-z]\w+", low):
        if w not in _STOP_WORDS:
            tokens.add(w)
    return tokens


class ToolMatcher:
    """工具-查询相关性评分器（build_index 后 rank 出 Top-K）。"""

    def __init__(self):
        self._index: dict[str, dict] = {}

    def build_index(self, tools: list[Any]) -> None:
        """从 ToolSpec 列表构建检索索引（name + description 作语料）。"""
        self._index = {}
        for spec in tools:
            name = getattr(spec, "name", spec)
            desc = getattr(spec, "description", "") or ""
            corpus = f"{name} {desc}"
            self._index[name] = {
                "tokens": _tokenize(corpus),
                "keywords": _tokenize(desc),
                "desc": desc,
            }

    def rank(self, query: str, top_k: int = 8) -> list[tuple[str, float, str]]:
        """对查询评分，返回 (工具名, 评分, 描述) 降序列表。

        评分：工具名完全匹配 +5 / 部分匹配 +3 / 描述关键词命中 +1 次 / 一般 token +0.5 次。
        """
        if not self._index or not query:
            return []
        query_tokens = _tokenize(query)
        query_lower = query.lower()
        scored: list[tuple[str, float, str]] = []
        for name, entry in self._index.items():
            score = 0.0
            if name in query_lower:
                score += 5.0
            elif any(q in name for q in query_tokens if len(q) >= 3):
                score += 3.0
            score += len(query_tokens & entry["keywords"]) * 1.0
            score += len(query_tokens & entry["tokens"]) * 0.5
            if score > 0:
                scored.append((name, score, entry["desc"]))
        scored.sort(key=lambda x: -x[1])
        return scored[:top_k]

    def top_names(self, query: str, top_k: int = 8) -> list[str]:
        """仅返回 Top-K 工具名（供 ToolCube 筛选用）。"""
        return [name for name, _, _ in self.rank(query, top_k)]

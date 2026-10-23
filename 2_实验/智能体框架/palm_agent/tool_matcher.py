"""语义工具匹配器 —— 根据用户输入自动筛选相关工具。

不使用外部向量数据库/嵌入模型，仅靠关键词+描述词频评分，
在零外部依赖条件下达到够用的语义相关性排序。
"""
from __future__ import annotations

import logging
import re
from typing import Any

_LOGGER = logging.getLogger(__name__)

# 常见停用词（中文+英文），避免噪声干扰评分
_STOP_WORDS = {
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人",
    "都", "一", "一个", "上", "也", "很", "到", "说", "要", "去",
    "你", "会", "着", "没有", "看", "好", "自己", "这",
    "the", "a", "an", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "can", "shall",
    "to", "of", "in", "for", "on", "with", "at", "by", "from",
    "as", "into", "through", "during", "before", "after", "above",
    "below", "between", "out", "off", "over", "under", "again",
    "further", "then", "once", "here", "there", "when", "where",
    "why", "how", "all", "each", "every", "both", "few", "more",
    "most", "other", "some", "such", "no", "nor", "not", "only",
    "own", "same", "so", "than", "too", "very", "get", "got",
    "use", "used", "using", "make", "made", "let", "like", "just",
}


def _tokenize(text: str) -> set[str]:
    """将文本拆分为 token 集合（中文保留单字，英文拆词）。"""
    tokens = set()
    # 中文单字（每个汉字都是一个独立语义单元）
    for c in text.lower():
        if '\u4e00' <= c <= '\u9fff' and c not in _STOP_WORDS:
            tokens.add(c)
    # 中文双字组合（提高短语匹配精度）
    chars = [c for c in text.lower() if '\u4e00' <= c <= '\u9fff']
    for i in range(len(chars) - 1):
        bigram = chars[i] + chars[i + 1]
        if bigram not in _STOP_WORDS:
            tokens.add(bigram)
    # 英文单词
    for w in re.findall(r"[a-z]\w+", text.lower()):
        if w not in _STOP_WORDS:
            tokens.add(w)
    return tokens


def _extract_keywords(desc: str) -> set[str]:
    """从工具描述中提取核心关键词。"""
    return _tokenize(desc)


class ToolMatcher:
    """工具-查询相关性评分器。"""

    def __init__(self):
        self._index: dict[str, dict] = {}  # tool_name → {tokens, keywords, desc}

    def build_index(self, tools: list[Any]) -> None:
        """从工具列表构建检索索引。"""
        self._index = {}
        for tool in tools:
            spec = tool.spec
            # 合并 name + description 作为语料
            corpus = f"{spec.name} {spec.description}"
            tokens = _tokenize(corpus)
            keywords = _extract_keywords(spec.description)
            self._index[spec.name] = {
                "tokens": tokens,
                "keywords": keywords,
                "desc": spec.description,
            }
        _LOGGER.info("已构建 %d 个工具的检索索引", len(self._index))

    def rank(self, query: str, top_k: int = 20) -> list[tuple[str, float, str]]:
        """对查询进行评分，返回 (工具名, 评分, 描述) 列表。

        评分策略：
          - 查询词完全匹配工具名 → +5.0
          - 查询词部分匹配工具名 → +3.0
          - 查询 token 命中描述 keyword → +1.0/次
          - 查询 token 命中一般 token → +0.5/次
        """
        if not self._index:
            return []

        query_tokens = _tokenize(query)
        query_lower = query.lower()

        scored: list[tuple[str, float, str]] = []
        for name, entry in self._index.items():
            score = 0.0

            # 工具名完全匹配
            if name in query_lower:
                score += 5.0
            # 工具名部分匹配（如 query 含 "file" → "delete_file" 部分匹配）
            elif any(q in name for q in query_tokens if len(q) >= 3):
                score += 3.0

            # 查询 token vs 描述关键词
            hit_keywords = query_tokens & entry["keywords"]
            score += len(hit_keywords) * 1.0

            # 查询 token vs 一般 token
            hit_tokens = query_tokens & entry["tokens"]
            score += len(hit_tokens) * 0.5

            if score > 0:
                scored.append((name, score, entry["desc"]))

        # 按评分降序
        scored.sort(key=lambda x: -x[1])
        return scored[:top_k]

    def search(self, query: str) -> list[tuple[str, str]]:
        """搜索全部工具，返回 (工具名, 描述) 列表——供 Agent 的 search_tools 调用。"""
        if not self._index:
            return []
        ranked = self.rank(query, top_k=999)
        return [(r[0], r[2]) for r in ranked][:30]


# 全局实例
_matcher: ToolMatcher | None = None


def get_matcher() -> ToolMatcher:
    global _matcher
    if _matcher is None:
        _matcher = ToolMatcher()
    return _matcher


def rebuild_index(tools: list[Any]) -> None:
    """重建全局检索索引。"""
    get_matcher().build_index(tools)

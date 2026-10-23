"""完成判定门（移植自 palm/services/agent/completion_gate.py，去截图/GUI 专属规则）。

识别确定性工具结果：工具输出已直接回答请求时，直接构造最终结果，避免模型
目标已达成还继续空转。支持 register_rule() 注册自定义规则（后注册优先）。
"""
from __future__ import annotations

import re
from typing import Callable, Optional

# 规则签名：fn(request: str, tool_name: str, tool_output: str) -> Optional[str]
# 返回非 None = 目标已达成，返回内容即最终结果；None = 继续。
CompletionRuleFn = Callable[[str, str, str], Optional[str]]


def _first_non_empty_line(text: str) -> str:
    for line in (text or "").splitlines():
        if line.strip():
            return line.rstrip("\r\n")
    return ""


def _extract_title_like_text(text: str) -> str:
    text = (text or "").strip()
    html_title = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
    if html_title:
        return re.sub(r"\s+", " ", html_title.group(1)).strip()
    labeled = re.search(r"(?:title|标题)\s*[:：]\s*(.+)", text, re.I)
    if labeled:
        return labeled.group(1).strip().splitlines()[0][:120]
    return _first_non_empty_line(text)[:120]


# ── 内置默认规则 ──────────────────────────────────────────────
def _rule_read_file_first_line(request: str, tool_name: str, tool_output: str) -> Optional[str]:
    if tool_name == "read_file" and "第一行" in request and "字符数" in request:
        first = _first_non_empty_line(tool_output)
        if first:
            return f"第一行={first}；字符数={len(first)}"
    return None


def _rule_web_fetch_title(request: str, tool_name: str, tool_output: str) -> Optional[str]:
    if tool_name == "web_fetch" and ("页面标题" in request or "标题" in request):
        title = _extract_title_like_text(tool_output)
        if title:
            return f"页面标题={title}"
    return None


def _rule_read_file_confirmed(request: str, tool_name: str, tool_output: str) -> Optional[str]:
    if tool_name == "read_file" and any(
            k in request for k in ("确认内容", "确认包含", "是否包含", "核实")):
        cleaned = re.sub(r"\s+", "", tool_output or "")
        if cleaned:
            return f"已确认：文件内容包含如下文本——{cleaned[:200]}"
    return None


def _rule_pytest_passed(request: str, tool_name: str, tool_output: str) -> Optional[str]:
    if tool_name == "run_code" and "pytest" in request:
        if "passed" in (tool_output or "").lower():
            return "测试结果：全部通过（pytest passed）"
    return None


class CompletionGate:
    """完成判定门：按注册顺序逆序匹配（后注册优先）。"""

    def __init__(self) -> None:
        self._rules: list[CompletionRuleFn] = []
        for rule in (_rule_read_file_first_line, _rule_web_fetch_title,
                     _rule_read_file_confirmed, _rule_pytest_passed):
            self.register_rule(rule)

    def register_rule(self, rule: CompletionRuleFn) -> None:
        self._rules.insert(0, rule)

    def check(self, request: str, tool_name: str, tool_output: str) -> Optional[str]:
        """请求已被工具输出直接回答则返回最终结果，否则 None。"""
        for rule in self._rules:
            result = rule(request, tool_name, tool_output)
            if result is not None:
                return result
        return None

    def rule_count(self) -> int:
        return len(self._rules)

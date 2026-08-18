"""提示注入短语剥离（自包含副本，避免跨砖 import）。

与 agent 砖 _native_execution._strip_prompt_injection 同思路：仅移除已知高信号
注入短语，不删整句，避免误删合法内容。这是 Gate 的浅层防注入，非主防线。
"""
from __future__ import annotations

import re

_INJECTION_RE = re.compile(
    r"(?i)"
    r"(忽略(之前的|前述|以上|所有|上面)?(指令|提示|规则|系统提示|设定))"
    r"|(忘记(之前|前述|以上|上面)的(指令|提示|对话|设定))"
    r"|(disregard.{0,30}(previous|prior|above|all).{0,30}(instructions?|prompt|rules?|system))"
    r"|(ignore.{0,30}(previous|prior|above|all).{0,30}(instructions?|prompt|rules?|system))"
    r"|(system\s*prompt)"
    r"|(你(现在)?(必须|应该|需要)?(扮演|成为|模拟|假装))"
)


def strip_prompt_injection(text: str) -> str:
    """移除文本中的常见提示注入短语，返回净化后的文本。"""
    if not text:
        return text
    return _INJECTION_RE.sub("", text)

"""动态 prompt 注入中间件（设计 §6.9 / §7.10）。

固定内容在上（可缓存前缀），动态内容在下；模块化组合；
不可用即不注入；注入清单留痕（开发者功能）。
"""
from dataclasses import dataclass


@dataclass
class InjectionModule:
    """注入模块：各面产出，经中间件组合成一条 prompt。"""

    source: str       # 面标识
    content: str      # 注入文本
    fixed: bool = False       # 是否固定（在上，可缓存）
    priority: int = 0         # 排序
    token_budget: int = 0     # 预算
    available: bool = True    # 是否可用（不可用即不注入）


def estimate_tokens(text: str) -> int:
    """粗略 token 估算（中文约 2 字 1 token）。"""
    return max(1, len(text) // 2)


class PromptAssembler:
    """组合器：固定在上、动态在下；并留痕注入清单。"""

    def __init__(self):
        self.last_manifest: list = []

    def assemble(self, modules) -> str:
        usable = [m for m in modules if m.available and m.content.strip()]
        fixed = sorted([m for m in usable if m.fixed], key=lambda m: m.priority)
        dynamic = sorted([m for m in usable if not m.fixed], key=lambda m: m.priority)
        ordered = fixed + dynamic
        self.last_manifest = [
            {"source": m.source, "fixed": m.fixed,
             "tokens": estimate_tokens(m.content)}
            for m in ordered
        ]
        return "\n\n".join(m.content for m in ordered)

    def manifest(self):
        return self.last_manifest

"""工具魔方（微内核之一）：工具注册表 + 执行编排。

权限判定已下沉到安全魔方（SecurityCube）——工具魔方负责注册与「注册表查询」，
decide() 委托安全魔方做权限闸门（越权即拒绝，fail-closed）。
"""
from dataclasses import dataclass
from typing import Callable

from security.security_cube import SecurityCube


@dataclass
class ToolSpec:
    """工具定义：名称、描述、所需权限、是否需沙箱隔离、执行函数、参数 schema（对齐归档）。

    安全元数据（对齐归档 tool_base）：
    - requires_grounding：防幻觉门——要求先经搜索/溯源核验（需 verification_id）
    - requires_confirmation：高危确认门——需显式 confirmed=true
    """
    name: str
    description: str
    requires: list           # 权限标签，如 ["shell"] / ["fs_read"]
    run_in_sandbox: bool = False
    fn: Callable[[dict], str] = None   # args -> 观测结果文本
    parameters: dict = None            # OpenAI 参数 schema（缺省空对象）
    requires_grounding: bool = False   # 防幻觉门（归档 verification_gate）
    requires_confirmation: bool = False  # 高危确认门（归档 requires_confirmation）


@dataclass
class ToolDecision:
    """权限判定结果。"""
    allowed: bool
    reason: str
    spec: ToolSpec | None = None


class ToolCube:
    """工具魔方：注册工具；权限闸门委托安全魔方；语义筛选缩小暴露面。"""

    def __init__(self, allowed_permissions: list | None = None,
                 security: SecurityCube | None = None):
        self._tools: dict[str, ToolSpec] = {}
        self.security = security or SecurityCube(allowed_permissions)
        self._matcher = None  # 语义匹配索引（惰性构建）

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec
        self._matcher = None  # 索引失效，下次惰性重建

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def list_tools(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def grant(self, permission: str) -> None:
        """显式授权一个权限标签（如 shell），委托安全魔方。"""
        self.security.grant(permission)

    def _ensure_matcher(self):
        """惰性构建语义匹配索引（归档 tool_matcher 移植）。"""
        if self._matcher is None:
            from .tool_matcher import ToolMatcher
            self._matcher = ToolMatcher()
            self._matcher.build_index(self.list_tools())
        return self._matcher

    def _relevant(self, query: str, top_k: int = 8) -> set[str]:
        """按输入筛出相关工具名集合；query 空则全量（不筛选）。"""
        if not query:
            return set(self._tools)
        names = self._ensure_matcher().top_names(query, top_k)
        return set(names) or set(self._tools)

    def decide(self, name: str, args: dict) -> ToolDecision:
        """执行前权限闸门（委托安全魔方）：工具是否在册、所需权限是否放行。"""
        spec = self.get(name)
        if spec is None:
            return ToolDecision(False, f"未知工具：{name}", None)
        allowed, reason = self.security.check_permission(name, spec.requires)
        return ToolDecision(allowed, reason, spec)

    def describe_for_prompt(self, query: str = "") -> str:
        """生成注入 Worker 提示的工具说明书；带 query 时按语义筛 Top-K（缩小暴露面）。"""
        relevant = self._relevant(query)
        lines = []
        for spec in self._tools.values():
            if spec.name not in relevant:
                continue
            tag = "（沙箱隔离）" if spec.run_in_sandbox else ""
            lines.append(f"- {spec.name}：{spec.description}{tag}")
        if query and len(lines) < len(self._tools):
            hidden = len(self._tools) - len(lines)
            lines.append(f"（另有 {hidden} 个工具与本任务无关，已隐藏——需要时可直接点名调用）")
        return "\n".join(lines) or "（无可用工具）"

    def schemas(self) -> list[dict]:
        """兼容旧名：产出 OpenAI function calling 工具描述。"""
        return self.to_openai_tool()

    def to_openai_tool(self, query: str = "") -> list[dict]:
        """产出 OpenAI function calling 工具描述；带 query 时按语义筛 Top-K。"""
        relevant = self._relevant(query)
        return [
            {"type": "function",
             "function": {
                 "name": spec.name,
                 "description": spec.description,
                 "parameters": spec.parameters or {"type": "object", "properties": {}},
             }}
            for spec in self._tools.values() if spec.name in relevant
        ]

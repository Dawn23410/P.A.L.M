"""工具层薄壳（向后兼容）。

真正的基类定义已下沉到主板 backend/app/bricks/_shared/tooling.py（零互导契约）。
本文件保留 agent 专属的注册装配逻辑（register_builtin_tools / SearchToolsTool），
二者依赖 app.bricks.agent.tools 子包（相对导入），故留在 agent 砖内。
同时重新导出基类符号，使 agent 内部 `from .tool_base import X` 调用方零改动。
"""
from __future__ import annotations

from palm_sdk.bricks._shared.tooling import (  
    Tool, ToolSpec, SimpleTool, tool, ToolRegistry,
    get_registry, reset_registry, get_decorator_tools,
    validate_tool_args, execute_tool_with_safety,
    agent_conversation_id, agent_model, agent_character_id,
    agent_provider, agent_is_wakeup,
)


def register_builtin_tools() -> None:
    """注册全部内置工具。"""
    reg = get_registry()
    from .tools.file_tools import FILE_TOOLS
    from .tools.web_tools import WEB_TOOLS
    from .tools.life_tools import PROD_TOOLS
    from .tools.window_tools import WINDOW_TOOLS
    from .tools.sandbox_tools import SANDBOX_TOOLS
    from .tools.ask_tool import ASK_TOOLS
    from .tools.scheduler_tools import SCHEDULER_TOOLS

    # 注意：GUI 自动化入口由 automation 砖注册（工具名 automate），此处不再注册，避免重复。
    # 原 DESKTOP_TOOLS 等四组精细工具列表已从 tools/gui 移除（从未被消费）。
    all_groups = [FILE_TOOLS, WEB_TOOLS, PROD_TOOLS,
                  WINDOW_TOOLS, SANDBOX_TOOLS,
                  ASK_TOOLS, SCHEDULER_TOOLS]
    for group in all_groups:
        for tool_cls in group:
            reg.register(tool_cls())
    # 装饰器工具
    for t in get_decorator_tools():
        reg.register(t)

    # search_tools：检索全部工具的入口
    reg.register(SearchToolsTool())


class SearchToolsTool(Tool):
    """搜索全部可用工具，根据关键词查找匹配的工具名和描述。"""
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="search_tools",
            description="搜索全部可用工具。当推荐工具不满足需求时，使用此工具按关键词查找其他工具。",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词，如「文件」「网络」「图片」「计算」等",
                    },
                },
                "required": ["query"],
            },
        )

    async def execute(self, query: str = "") -> str:
        from .tool_matcher import get_matcher
        matcher = get_matcher()
        results = matcher.search(query)
        if not results:
            total = len(get_registry().list_tools())
            return f"未找到匹配「{query}」的工具（共 {total} 个工具可用）"
        lines = [f"🔍 搜索「{query}」结果（{len(results)} 个匹配）:",
                 "=" * 40]
        for name, desc in results:
            lines.append(f"  {name}: {desc}")
        lines.append(f"\n💡 使用 Action: 工具名 + ActionInput 调用")
        return "\n".join(lines)
# 工具基类（与砖块内 Tool/ToolSpec 对齐）。
#
# 直接复用主板 _shared 完整实现（含 event_type / permission / requires_grounding 等字段，
# 以及基于抽象 execute 的 Tool 基类），避免独立态出现缺字段的旧基类导致
# ToolSpec(..., event_type=...) 构造失败。Agent 框架自身 tool_base 亦由此再导出。
from palm_sdk.bricks._shared.tooling import (  # noqa: F401
    Tool,
    ToolSpec,
    SimpleTool,
    ToolRegistry,
    tool,
    get_registry,
    reset_registry,
    get_decorator_tools,
    validate_tool_args,
    execute_tool_with_safety,
    agent_conversation_id,
    agent_model,
    agent_character_id,
    agent_provider,
    agent_is_wakeup,
)

"""Agent 数据模型。"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class AgentRunRequest(BaseModel):
    """运行 Agent 的请求体。"""
    conversation_id: str
    message: str
    model: str
    # 记忆层类型：当前仅支持 buffer（summary 模式未实现，已移除）
    memory_type: Literal["buffer"] = "buffer"
    # 最大迭代步数（防止无限循环）
    max_iterations: int = Field(default=10, ge=1, le=50)
    # 自主规划引擎开关（默认开启：先制定计划再分步执行，失败自动重规划）
    use_planning: bool = True
    # 计划最大步数（防止计划爆炸）
    max_plan_steps: int = Field(default=8, ge=1, le=20)
    # 自定义 LLM 供应商（如 Ollama），不传则使用 Mock 回显
    provider: Any = None
    # 角色扮演：内置角色 id（优先于 persona_text）
    character_id: str = ""
    # 角色扮演：直接传入的人设文本（无 character_id 时生效）
    persona_text: str = ""
    # 工具调用架构：native=原生结构化(function calling) / react=文本式 ReAct 兜底。
    # 缺省 None 表示使用全局默认（当前 native）；Anthropic 供应商会被强制回落 react。
    tool_mode: Literal["native", "react"] | None = None
    # P5 结构化输出：可选 JSON Schema；提供时要求模型以单个 ```json 代码块输出，
    # 收尾抽取并校验必填键后写入 done 事件的 structured_output 字段。
    structured_output: dict | None = None
    # 可选工具白名单：用于基准测试或高风险场景，把模型可见、可调用工具限制在指定名称内。
    allowed_tools: list[str] | None = None


class AgentEvent(BaseModel):
    """SSE 流事件。"""
    type: Literal[
        "thought",          # Agent 思考过程
        "tool_call",        # 调用工具
        "tool_result",      # 工具执行结果
        "plan",             # 自主规划：完整计划（plan 字段为步骤列表）
        "plan_step",        # 计划单步状态更新（plan_step 字段为单步）
        "delta",            # 文本增量
        "error",            # 错误
        "done",             # 完成
        "ask_user",         # 向用户提问（人机交互卡片，等待回答期间阻塞）
    ]
    content: str = ""
    # tool_call / tool_result 专用字段
    tool_name: str = ""
    tool_input: dict[str, Any] = Field(default_factory=dict)
    tool_output: str = ""
    # ask_user 专用字段：问题规格 {id,title,content,qtype,options}
    question: dict[str, Any] = Field(default_factory=dict)
    # 规划引擎专用字段
    plan: list[dict] = Field(default_factory=list)
    plan_step: dict = Field(default_factory=dict)
    # 裁决引擎拦截信息
    adjudicated: bool = False
    adjudicated_reason: str = ""
    # 工具产物（如代码生成的图片），形如 {"type","name","mime","data"(base64)}
    artifacts: list[dict] = Field(default_factory=list)
    # Token 用量（仅 done 事件携带，含真实或估算的 prompt/completion/total tokens）
    usage: dict[str, int] = Field(default_factory=dict)
    # 角色扮演：当前好感度（仅 done 事件携带）
    affinity: float = 0.0
    # 角色扮演：好感度结算后的完整状态（base/dynamics/bond 等），
    # 仅供后端结算经验与记情感事件使用；前端是否展示仍由 display_allowed 控制。
    affinity_state: dict | None = None
    # P5 结构化输出：当请求带 structured_output schema 时，最终答案解析出的 JSON 对象
    structured_output: dict = Field(default_factory=dict)

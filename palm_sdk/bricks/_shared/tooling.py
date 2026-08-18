"""主板工具抽象层（_shared/tooling）—— palm_sdk 独立态完整实现。

原位于 agent 砖内（agent/tool_base.py），因 Tool/ToolSpec/ToolRegistry 等基类被
17 个文件（含 memory/self_evolution/automation/stitching/backend.tools 等跨砖引用）共用，
按「零互导」契约下沉到主板。本模块零业务砖依赖，仅延迟 import palm_sdk.permission。
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable

_LOGGER = logging.getLogger(__name__)

# 工具执行真实异常的有界重试：仅重试 tool.execute 抛出的瞬时异常（不含首次共 2 次），
# 线性退避。权限/裁决拦截在重试前已 return，不会被重试。
_TOOL_MAX_RETRIES = 2
_TOOL_RETRY_BACKOFF = 0.3

# 当前 Agent 运行上下文（供工具在不改签名的前提下读取会话信息）。
# 由 Agent.run 在每次运行时写入，工具执行处于同一协程内可见。
agent_conversation_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "agent_conversation_id", default=""
)
agent_model: contextvars.ContextVar[str] = contextvars.ContextVar(
    "agent_model", default=""
)
# 当前角色 id：供提醒/定时等工具读取，使主动推送能以角色人设撰写内容。
agent_character_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "agent_character_id", default=""
)
# 当前供应商配置（dict / ProviderRef 序列化）：供 automation 砖 worker 读取，
# 使其自带 LLM 能复用与对话相同的模型供应商，无需工具调用方显式透传。
agent_provider: contextvars.ContextVar[object] = contextvars.ContextVar(
    "agent_provider", default=None
)
# 标记本轮是否为「后台任务完成自动唤醒」轮：唤醒轮禁止再登记后台任务，防套娃。
agent_is_wakeup: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "agent_is_wakeup", default=False
)


# ── 工具规格（纯数据） ──────────────────────────────────────────

@dataclass
class ToolSpec:
    """工具规格定义 —— 携带工具的所有元信息。

    这是 Tool 与外部世界交互的唯一数据契约：
    - name:       蛇形命名，唯一标识（如 read_file）
    - description:LLM 理解用途的自然语言描述
    - parameters: JSON Schema 格式的参数定义
    - event_type: 触发裁决引擎的事件类型（空串=不触发安全审查）
    """
    name: str
    description: str
    parameters: dict = field(default_factory=lambda: {"type": "object", "properties": {}, "required": []})
    event_type: str = ""
    permission: str = ""  # 所需用户授权键；空串=豁免（fail-open）
    # 硬约束前置校验（源自自主进化架构决策4）：删除/外发等高风险操作必须
    # 先经搜索/溯源核验并附带 verification_id，否则执行前直接拦截，不依赖 AI 自觉。
    requires_grounding: bool = False
    requires_confirmation: bool = False


# ── 工具抽象基类（最小接口） ────────────────────────────────────

class Tool(ABC):
    """工具抽象基类。

    三选一定义方式（优先级: spec > 旧属性）：
    1. 新风格：覆写 spec（推荐）
    2. 旧风格：覆写 name + description + parameters + event_type
    3. SimpleTool / @tool 装饰器
    """

    @abstractmethod
    async def execute(self, **kwargs) -> str:
        """执行工具逻辑，返回文本结果。"""

    # ── spec 主入口 ──────────────────────────────────────

    @property
    def spec(self) -> ToolSpec:
        """由子类覆盖提供，或回退到旧属性构造。"""
        return ToolSpec(
            name=self._resolve_name(),
            description=self._resolve_description(),
            parameters=self._resolve_parameters(),
            event_type=self._resolve_event_type(),
            permission=self._resolve_permission(),
            requires_grounding=self._resolve_requires_grounding(),
            requires_confirmation=self._resolve_requires_confirmation(),
        )

    # ── 旧风格兼容属性（子类可覆写） ───────────────────────

    @property
    def tool_permission(self) -> str:
        """所需用户授权键；子类覆盖提供，空串=豁免。"""
        return ""

    @property
    def tool_name(self) -> str:
        raise NotImplementedError(f"{type(self).__name__}: 请定义 spec.name 或 tool_name")
    @property
    def tool_description(self) -> str:
        raise NotImplementedError(f"{type(self).__name__}: 请定义 spec.description 或 tool_description")
    @property
    def tool_parameters(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}
    @property
    def tool_event_type(self) -> str:
        return ""

    # ── 解析器（避免循环依赖） ─────────────────────────────

    def _resolve_name(self) -> str:
        if 'tool_name' in type(self).__dict__:
            return self.tool_name
        if 'name' in type(self).__dict__ or 'name' in self.__class__.__mro__[1].__dict__:
            return self.name  # only safe if subclass defined name properly
        raise NotImplementedError(f"{type(self).__name__}: 必须定义 spec 或 tool_name 或 name")

    def _resolve_description(self) -> str:
        if 'tool_description' in type(self).__dict__:
            return self.tool_description
        if 'description' in type(self).__dict__:
            return self.description
        raise NotImplementedError(f"{type(self).__name__}: 必须定义 spec 或 tool_description 或 description")

    def _resolve_parameters(self) -> dict:
        if 'tool_parameters' in type(self).__dict__:
            return self.tool_parameters
        if 'parameters' in type(self).__dict__:
            return self.parameters
        return {"type": "object", "properties": {}, "required": []}

    def _resolve_event_type(self) -> str:
        if 'tool_event_type' in type(self).__dict__:
            return self.tool_event_type
        return ""

    def _resolve_permission(self) -> str:
        if 'tool_permission' in type(self).__dict__:
            return self.tool_permission
        if 'permission' in type(self).__dict__:
            return self.permission
        return ""

    def _resolve_requires_grounding(self) -> bool:
        if 'requires_grounding' in type(self).__dict__:
            return bool(self.requires_grounding)
        return False

    def _resolve_requires_confirmation(self) -> bool:
        if 'requires_confirmation' in type(self).__dict__:
            return bool(self.requires_confirmation)
        return False

    # ── 别名（旧工具兼容） ──────────────────────────────

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def description(self) -> str:
        return self.spec.description

    @property
    def parameters(self) -> dict:
        return self.spec.parameters

    @property
    def event_type(self) -> str:
        return self.spec.event_type

    # ── 序列化 ──────────────────────────────────────────

    def to_openai_tool(self) -> dict:
        return {"type": "function", "function": {
            "name": self.spec.name, "description": self.spec.description,
            "parameters": self.spec.parameters,
        }}

    def to_react_prompt(self) -> str:
        import json
        return f"  - {self.spec.name}: {self.spec.description}\n    参数: {json.dumps(self.spec.parameters, ensure_ascii=False)}"


# ── 简化工具（传参即用，无需写类） ─────────────────────────────

class SimpleTool(Tool):
    """最简单的方式定义一个工具 —— 传入 spec + 执行函数。

    用法:
        tool = SimpleTool(
            ToolSpec(name="ping", description="检查网站可达性",
                     parameters={...}),
            execute_fn=lambda **kw: f"pong: {kw}",
        )
    """

    def __init__(self, spec: ToolSpec, execute_fn: Callable[..., Any]) -> None:
        self._spec = spec
        self._fn = execute_fn

    @property
    def spec(self) -> ToolSpec:
        return self._spec

    async def execute(self, **kwargs) -> str:
        exec_result = self._fn(**kwargs)
        if hasattr(exec_result, "__await__"):
            return await exec_result
        return str(exec_result)


# ── 装饰器：函数即工具 ─────────────────────────────────────────

_TOOL_DECORATOR_REGISTRY: list[Tool] = []


def tool(
    name: str,
    description: str,
    parameters: dict | None = None,
    event_type: str = "",
    permission: str = "",
) -> Callable:
    """装饰器：将一个 async 函数标记为工具并自动注册。

    用法:
        @tool(name="hello", description="打招呼")
        async def hello_tool(name: str = "世界"):
            return f"你好，{name}！"
    """
    def decorator(func: Callable) -> Callable:
        spec = ToolSpec(
            name=name,
            description=description,
            parameters=parameters or _infer_parameters(func),
            event_type=event_type,
            permission=permission,
        )
        simple = SimpleTool(spec=spec, execute_fn=func)
        _TOOL_DECORATOR_REGISTRY.append(simple)
        return func
    return decorator


def _infer_parameters(func: Callable) -> dict:
    """从函数签名推断参数 Schema（简易版）。"""
    import inspect
    sig = inspect.signature(func)
    properties = {}
    required = []
    for p_name, p_param in sig.parameters.items():
        if p_name in ("self", "cls", "kwargs", "args"):
            continue
        # 类型推断
        type_map = {str: "string", int: "integer", float: "number", bool: "boolean",
                    list: "array", dict: "object"}
        p_type = type_map.get(p_param.annotation, "string") if p_param.annotation is not inspect.Parameter.empty else "string"
        properties[p_name] = {"type": p_type, "description": f"参数 {p_name}"}
        if p_param.default is inspect.Parameter.empty:
            required.append(p_name)
    return {"type": "object", "properties": properties, "required": required}


def get_decorator_tools() -> list[Tool]:
    """获取所有通过 @tool 装饰器定义的函数工具。"""
    return list(_TOOL_DECORATOR_REGISTRY)


# ── 工具注册表 ──────────────────────────────────────────────────

class ToolRegistry:
    """工具注册表（单例）。"""

    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            _LOGGER.warning("工具 %s 已注册，覆盖", tool.name)
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def unregister(self, name: str) -> None:
        """移除已注册工具（按名称）。self_evolution 砖经 capability 注销禁用工具。"""
        self._tools.pop(name, None)

    def list_tools(self) -> list[Tool]:
        return list(self._tools.values())

    def to_react_prompt(self) -> str:
        lines = ["可用工具："]
        for t in self._tools.values():
            lines.append(t.to_react_prompt())
        lines.append(
            "调用格式：\n"
            "Action: <工具名>\n"
            "ActionInput: <JSON 参数字典>\n"
            "当不需要调用工具时，直接回复用户。"
        )
        return "\n".join(lines)


# ── 全局注册表 ──────────────────────────────────────────────────

_registry: ToolRegistry | None = None


def get_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry


def reset_registry() -> None:
    global _registry
    _registry = None


# ── 参数校验（P2a：结构化自愈） ──────────────────────────────

# JSON Schema 标量类型 → Python isinstance 判定。bool 是 int 子类，单独处理避免 integer 误收 bool。
_TYPE_CHECKERS: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "number": (int, float),
    "array": (list, tuple),
    "object": (dict,),
}


def _value_matches_type(declared: str, value: object) -> bool:
    """宽松类型判定：bool 不算 integer/number；int/float 互不严格区分（LLM 常传 3.0）。"""
    if declared == "boolean":
        return isinstance(value, bool)
    if declared == "integer":
        if isinstance(value, bool):
            return False
        if isinstance(value, int):
            return True
        return isinstance(value, float) and value.is_integer()
    checker = _TYPE_CHECKERS.get(declared)
    if checker is None:
        return True
    if declared in ("number",) and isinstance(value, bool):
        return False
    return isinstance(value, checker)


def validate_tool_args(spec: object, args: dict) -> str | None:
    """轻量校验工具入参（JSON Schema 子集）。

    仅检查：① 必填字段缺失 ② 已提供字段的类型明显不符。
    未声明字段不强制；数值不强区分整数/浮点（LLM 常传 3.0 当整数）。
    返回 None 表示通过；否则返回结构化错误文本（供回灌模型自愈重试）。
    """
    params = getattr(spec, "parameters", None)
    if isinstance(spec, dict):
        params = spec.get("parameters", {})
    if not isinstance(params, dict):
        return None
    properties = params.get("properties", {}) or {}
    required = params.get("required", []) or []
    name = getattr(spec, "name", "工具") if not isinstance(spec, dict) else spec.get("name", "工具")
    missing = [r for r in required if r not in args or args.get(r) is None]
    if missing:
        return (
            f"参数校验失败：工具「{name}」缺少必填参数 {missing}。"
            f"请补全后重试（可用参数：{sorted(properties.keys())}）。"
        )
    for key, value in args.items():
        if key not in properties or value is None:
            continue
        declared = properties[key].get("type")
        if not declared:
            continue
        if not _value_matches_type(declared, value):
            return (
                f"参数校验失败：工具「{name}」的参数「{key}」应为 {declared} 类型，"
                f"实际收到 {type(value).__name__}（值：{value!r}）。请修正参数类型后重试。"
            )
    return None


# ── 工具执行包装（裁决引擎整合） ──────────────────────────────

def _resolve_default_guardrail_cap():
    """惰性解析统一护栏能力；任一环节失败则回退为 None（保持旧行为，不阻断）。"""
    try:
        from palm_sdk.guardrail.engine import get_guardrail_capability
        return get_guardrail_capability()
    except Exception:
        return None


async def execute_tool_with_safety(
    tool: Tool,
    tool_input: dict[str, Any],
    adjudicator_cap: object | None = None,
) -> tuple[bool, str]:
    """执行工具，前置权限引擎（用户授权）与裁决引擎安全校验。

    Returns:
        (allowed, result_text)
        - (True, result)  → 成功执行
        - (False, msg)    → 被权限引擎或裁决引擎拦截
    """
    # 硬约束前置校验（verification_gate）：高风险操作必须先经溯源核验/显式确认。
    if tool.spec.requires_grounding and not tool_input.get("verification_id"):
        return False, (
            "【前置校验失败】该操作要求先经搜索/溯源核验并附带 verification_id，"
            "未提供则禁止执行（防幻觉误删/误发）。"
        )
    if tool.spec.requires_confirmation and not tool_input.get("confirmed"):
        return False, "【需确认】该操作风险较高，请在参数中显式传入 confirmed=true 后再执行。"

    # 权限引擎（用户授权）为最外层闸门：未授权直接返回结构化提示，不执行、不崩。
    perm = tool.spec.permission
    if perm:
        from palm_sdk.permission import get_engine, denial_message
        if not get_engine().is_granted(perm):
            return False, denial_message(perm)

    # 未显式传入裁决能力时，惰性回退到统一护栏（palm_sdk.guardrail）作为全链路安全兜底。
    if adjudicator_cap is None and tool.event_type:
        adjudicator_cap = _resolve_default_guardrail_cap()
    if adjudicator_cap and tool.event_type:
        ctx = {"count": 1, "tool": tool.name, **tool_input}
        try:
            adjudication_result = adjudicator_cap(tool.event_type, ctx)
            if adjudication_result.blocked:
                if adjudication_result.action_type == "ask":
                    # ask 需用户确认，但当前流式架构未实现 SSE 确认协议：
                    # 工具不执行（保持安全），改为提示 Agent 用自然语言征求用户同意
                    prompt = adjudication_result.ask_message or adjudication_result.reason
                    return False, f"【需用户确认】{prompt}（请先用自然语言向用户确认，不要直接执行）"
                return False, f"【安全拦截】{adjudication_result.reason}"
        except Exception as exc:
            _LOGGER.error("裁决引擎检查异常（降级阻断，请排查规则配置）: %s", exc)
            return False, f"【安全拦截】裁决引擎检查异常：{type(exc).__name__}: {exc}"

    last_exc: Exception | None = None
    for attempt in range(_TOOL_MAX_RETRIES + 1):
        try:
            tool_output = await tool.execute(**tool_input)
            # 透传工具原始输出，不包裹 emoji/状态装饰：既避免把失败的 shell 命令误标为"成功"，
            # 也不污染 AI 看到的原始内容。工具结果是"assistant"角色记忆，AI 不会误当用户消息。
            return True, tool_output
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < _TOOL_MAX_RETRIES:
                _LOGGER.warning("工具 %s 执行异常，第 %d 次重试: %s", tool.name, attempt + 1, exc)
                await asyncio.sleep(_TOOL_RETRY_BACKOFF * (attempt + 1))
    return False, f"工具执行错误: {type(last_exc).__name__}: {last_exc}"

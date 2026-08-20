"""外骨骼（work 大魔方）包入口。

心智魔方的「一个 tool」：经 ||EXO|| 文本协议接入，后台拉起 Worker。
Worker = WorkCore（归档式原生工具循环 + 反思 + 规划）+ 5 小魔方；模型解耦。
除心智魔方（Boss）外，Work 侧全部采用 palm 归档双 Agent 设计（已测试可用）：
IntentRouter / ProfessionalMemory / TraceStore / Planner+PlanEngine / 反思自检 / 协调器。
"""
from .core import WorkCore, WorkCube, ExoSlotPort, build_ask_bridge
from .model import ExoLLM, ExoMockLLM
from .protocol import TaskGoal, parse_worker_output, extract_exo
from .intent_router import IntentRouter, IntentResult
from .trace_store import TraceStore, TraceEntry
from .planner import Planner, Plan, PlanStep
from .plan_engine import PlanEngine
from .runner import reflect_once, _sanitize_tool_text
from .prompt import build_worker_prompt
from .dual_parse import _normalize_native_chunk, _should_reflect
from .coordinator import ExoCoordinator
from .archived_tools import register_archived_tools
from .extended_tools import register_extended_tools
from .tool_matcher import ToolMatcher
from .completion_gate import CompletionGate
from .expansion import ExpansionBoard, Extension
from .evolution import EvolutionGate, SkillRegistry, Skill
from .token_ledger import TokenLedger
from .cron import Cron, CRON_ALIASES
from .cubes import (
    ToolSpec, ToolCube, SandboxCube, PlanCube, CommCube,
    ProfessionalMemory, ProfessionalMemoryRecord, SecurityCube,
)

# Worker 默认放行权限（danger 恒不在内 → 危险操作必被权限闸门拒绝）
_DEFAULT_PERMISSIONS = [
    "fs_read", "fs_write", "web_read", "compute", "summarize", "shell", "ask",
    "gui",
]

# 默认工具参数 schema（对齐归档 ToolSpec.parameters，供原生 function calling 声明入参）
_RUN_SHELL_PARAMS = {
    "type": "object",
    "properties": {"cmd": {"type": "string", "description": "要执行的命令"}},
    "required": ["cmd"],
}


def _register_board_tools(tool_cube: ToolCube, board: ExpansionBoard) -> None:
    """PCB 扩展板 AI 接口：AI 可经工具自注册技能/查板/拔扩展（进化门把关）。"""
    from .cubes.tool_cube import ToolSpec

    def _register_skill(args):
        return board.register_skill(
            args.get("name", ""), args.get("description", ""),
            args.get("guidance", ""))

    def _list_extensions(args):
        exts = board.list_extensions()
        if not exts:
            return "扩展板为空（0 个扩展）"
        lines = [f"扩展板 {len(exts)}/{board.max_slots} 槽："]
        for e in exts:
            lines.append(f"- [{e['kind']}] {e['name']}：{e['description']}")
        return "\n".join(lines)

    def _unregister_extension(args):
        ok, msg = board.unplug(args.get("name", ""))
        return msg

    tool_cube.register(ToolSpec(
        "register_skill",
        "向扩展板注册一条技能（AI 自学习/自扩展）：提供名称、说明与执行指导，"
        "注册后未来类似任务会自动注入该指导。进化门会校验内容安全性。",
        ["compute"], False, _register_skill,
        {"type": "object", "properties": {
            "name": {"type": "string", "description": "技能名"},
            "description": {"type": "string", "description": "技能说明"},
            "guidance": {"type": "string", "description": "执行指导（怎么做）"}},
         "required": ["name", "description", "guidance"]}))
    tool_cube.register(ToolSpec(
        "list_extensions", "查看扩展板上已注册的技能/扩展",
        ["compute"], False, _list_extensions,
        {"type": "object", "properties": {}}))
    tool_cube.register(ToolSpec(
        "unregister_extension", "从扩展板拔出（停用）一个扩展",
        ["compute"], False, _unregister_extension,
        {"type": "object", "properties": {"name": {"type": "string"}},
         "required": ["name"]}))


def build_exo(config, *, exo_config=None, allowed_permissions=None, sandbox_dir=None,
              memory_db=None, enable_reflect: bool | None = None,
              ask_bridge=None, sandbox_exec_mode: str = "legacy",
              board_max_slots: int = 8, token_budget: float | None = None) -> WorkCube:
    """按配置装配外骨骼 WorkCube（一键产出可注入 MentalCore.exo_broker 的实体）。

    exo_config 缺省回退到主 config；传入独立 Config（如 MENTALCORE_EXO_*）即可
    让 Worker 与 Boss 使用不同模型——模型层解耦。
    sandbox_exec_mode：legacy（默认，黑名单纵深）| restricted（受限 Token，
    非管理员 fail-closed）| deny（禁用 shell 执行）。
    board_max_slots：PCB 扩展板插槽数（AI 自注册技能上限）。
    token_budget：Token 预算（元，None=不限）。
    """
    from .cubes.tool_cube import ToolSpec

    exo_cfg = exo_config or config
    permissions = allowed_permissions or _DEFAULT_PERMISSIONS
    security_cube = SecurityCube(
        permissions,
        profile=getattr(exo_cfg, "exo_profile", "strict"),
        rules_yaml=getattr(exo_cfg, "exo_rules_yaml", "") or None,
    )
    tool_cube = ToolCube(security=security_cube)
    sandbox_cube = SandboxCube(sandbox_dir, security=security_cube,
                               exec_mode=sandbox_exec_mode)
    plan_cube = PlanCube()
    comm_cube = CommCube()
    memory_cube = ProfessionalMemory(memory_db)

    # 基础工具：run_shell（沙箱隔离）/ summarize（纯函数）/ danger_reset（权限拒绝演示）
    tool_cube.register(ToolSpec(
        name="run_shell", description="在沙箱内执行命令",
        requires=["shell"], run_in_sandbox=True,
        parameters=_RUN_SHELL_PARAMS))
    tool_cube.register(ToolSpec(
        name="summarize", description="对文本做简要摘要",
        requires=["summarize"], run_in_sandbox=False,
        parameters={"type": "object",
                    "properties": {"text": {"type": "string", "description": "待摘要文本"}},
                    "required": ["text"]},
        fn=lambda a: f"摘要：{(a.get('text') or '')[:120]}"))
    tool_cube.register(ToolSpec(
        name="danger_reset", description="危险操作（默认无权限）",
        requires=["danger"], run_in_sandbox=False,
        fn=lambda a: "不应执行"))
    # 归档工具组：文件 10 + 网络 2 + run_code + ask_user（心智魔方中转）
    register_archived_tools(tool_cube, sandbox_cube=sandbox_cube,
                            ask_bridge=ask_bridge)
    # 扩展工具组：prod 4 + scheduler 2 + 沙箱快照/后台任务 3（提醒经心智魔方传达）
    register_extended_tools(tool_cube)
    # PCB 扩展板：AI 自注册技能/扩展的插槽（进化门校验 + 提示注入）
    board = ExpansionBoard(max_slots=board_max_slots)
    _register_board_tools(tool_cube, board)

    if getattr(exo_cfg, "mode", "mock") == "mock":
        exo_llm = ExoMockLLM()
        demo_tool = ("run_shell", {"cmd": "echo exo_sandbox_ok"}) \
            if "shell" in permissions else ("summarize", {"text": "委派任务"})
        exo_llm.demo_tool = demo_tool
    else:
        exo_llm = ExoLLM(
            exo_cfg.provider_ref(), exo_cfg.model,
            exo_cfg.temperature, exo_cfg.max_tokens)

    reflect = (exo_cfg.mode == "live") if enable_reflect is None else enable_reflect
    core = WorkCore(exo_llm, tool_cube, sandbox_cube,
                    plan_cube, comm_cube, memory_cube,
                    enable_reflect=reflect, security_cube=security_cube,
                    ask_bridge=ask_bridge,
                    ask_timeout=getattr(exo_cfg, "exo_ask_timeout", 60.0),
                    board=board,
                    token_budget=token_budget)
    return WorkCube(core)


def build_coordinator(boss_core, cube: WorkCube) -> ExoCoordinator:
    """装配归档式双 Agent 协调器（Boss=心智魔方，Worker=外骨骼）。"""
    return ExoCoordinator(boss_core, cube)


__all__ = [
    "WorkCore", "WorkCube", "ExoSlotPort", "build_ask_bridge",
    "ExoLLM", "ExoMockLLM",
    "TaskGoal", "parse_worker_output", "extract_exo",
    "IntentRouter", "IntentResult",
    "TraceStore", "TraceEntry",
    "Planner", "Plan", "PlanStep", "PlanEngine",
    "reflect_once", "_sanitize_tool_text",
    "build_worker_prompt",
    "_normalize_native_chunk", "_should_reflect",
    "ExoCoordinator",
    "register_archived_tools", "register_extended_tools",
    "ToolMatcher", "CompletionGate",
    "ToolSpec", "ToolCube", "SandboxCube", "PlanCube", "CommCube",
    "SecurityCube",
    "ProfessionalMemory", "ProfessionalMemoryRecord",
    "build_exo", "build_coordinator",
]

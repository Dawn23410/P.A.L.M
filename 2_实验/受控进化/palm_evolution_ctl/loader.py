"""PatchlessLoader：把已批准的侧车工具载入 agent 工具注册表，并经沙箱执行。"""
from __future__ import annotations

import json

from palm._core.tooling import Tool, ToolSpec
from . import registry as se_registry


def _agent_register():
    """取 agent 砖经 capability 暴露的 register_tool（砖间零互导）。"""
    from palm._core.container import registry as brick_registry
    agent_brick = brick_registry.get("agent")
    if agent_brick is None:
        return None
    return agent_brick.capabilities.get("register_tool")


def _sandbox_run_code():
    """取沙箱砖经 capability 暴露的隔离执行入口（缺失返回 None，铁律降级）。"""
    from palm._core.container import registry as brick_registry
    sandbox_brick = brick_registry.get("sandbox")
    if sandbox_brick is None:
        return None
    cap_fn = sandbox_brick.capabilities.get("run_code_isolated")
    return cap_fn() if cap_fn else None


def _agent_unregister():
    from palm._core.container import registry as brick_registry
    agent_brick = brick_registry.get("agent")
    if agent_brick is None:
        return None
    return agent_brick.capabilities.get("unregister_tool")


def _build_runner_code(tool_dir: str, kwargs: dict) -> str:
    """生成在隔离沙箱内执行侧车 entry 的源码（仅传工具目录与参数 JSON）。"""
    args_json = json.dumps(kwargs, ensure_ascii=False)
    return (
        "import sys, json\n"
        f"sys.path.insert(0, {tool_dir!r})\n"
        "import tool as _m\n"
        f"_args = json.loads({args_json!r})\n"
        "_result = _m.entry(**_args)\n"
        "print(json.dumps({'result': _result}, ensure_ascii=False))\n"
    )


class SelfEvoTool(Tool):
    """自注册工具的运行时包装：execute 在隔离沙箱内执行侧车 entry。"""

    def __init__(self, manifest: dict) -> None:
        self._manifest = manifest

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self._manifest["id"],
            description=f"{self._manifest['name']}：{self._manifest.get('description', '')}",
            parameters=self._manifest.get(
                "params_schema", {"type": "object", "properties": {}, "required": []}
            ),
            event_type="self_evo.tool",
            permission=self._manifest.get("requires_permission", ""),
        )

    async def execute(self, **kwargs) -> str:
        tool_dir = se_registry._tool_dir(self._manifest["id"])
        code = _build_runner_code(tool_dir, kwargs)
        run_fn = _sandbox_run_code()
        if run_fn is None:
            return "工具执行不可用：沙箱砖未注册（隔离执行不可用）。"
        result = run_fn("python", code, timeout=10, work_dir=tool_dir)
        if result.get("missing"):
            return f"工具执行不可用：{result.get('error', '解释器缺失')}"
        if result.get("error"):
            return f"工具执行出错：{result.get('error')}"
        output = result.get("output", "").strip()
        try:
            parsed = json.loads(output)
            return str(parsed.get("result", output))
        except (json.JSONDecodeError, ValueError):
            return output or "（无输出）"


def register_into_agent(manifest: dict) -> bool:
    register = _agent_register()
    if register is None:
        return False
    register(SelfEvoTool(manifest))
    return True


def unregister_from_agent(tool_id: str) -> bool:
    unregister = _agent_unregister()
    if unregister is None:
        return False
    unregister(tool_id)
    return True


def load_enabled_on_startup() -> int:
    """启动时载入所有已批准且启用的工具，返回成功注册数量。"""
    count = 0
    for manifest in se_registry.list_all():
        if manifest.get("enabled") and manifest.get("approved"):
            if register_into_agent(manifest):
                count += 1
    return count
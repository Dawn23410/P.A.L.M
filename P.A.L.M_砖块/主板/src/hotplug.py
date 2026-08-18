"""热插拔 / 版本回滚 / MCP 兼容层（L5 自治控制平面）。

把主板从「静态焊接」升级为「可插拔总线」：
- VersionLedger：每块砖加载时记一笔版本历史（砖名/版本/端点/时间戳），供回滚追溯。
- plug / unplug：运行时插拔砖（注册+包芯片 / 释放芯片+停用），配合 watchdog 存活重探。
- rollback：子进程砖 = 重启运行时进程（真实回滚到加载时点）；进程内砖 = 重激活芯片。
- McpAdapter：把砖能力映射为 MCP tools/list + tools/call（兼容 Anthropic MCP 工具协议），
  让外部 MCP 客户端无需重写砖即可消费 P.A.L.M 能力。

全部加性：内置/插件砖的既有加载路径不变，本层只在之上叠加治理动作。
"""
from __future__ import annotations

import inspect
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from palm_sdk.bricks.base import Brick, registry
from palm_sdk.security import require_api_token
from .arbitration import _arbiter
from .handle import all_controllers, get_handle, wrap_brick

_LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


# ── 版本台账 ──────────────────────────────────────────────
class VersionLedger:
    """每块砖的版本加载历史（闭环追溯，支撑回滚）。"""

    def __init__(self) -> None:
        self._history: dict[str, list[dict]] = {}

    def record(self, name: str, version: str, endpoint: str) -> None:
        entry = {"version": version, "endpoint": endpoint, "ts": time.time()}
        self._history.setdefault(name, []).append(entry)

    def history(self, name: str) -> list[dict]:
        return list(self._history.get(name, []))

    def last_known_good(self, name: str) -> dict | None:
        hist = self._history.get(name)
        return hist[-1] if hist else None


_ledger = VersionLedger()


def record_loaded_versions() -> None:
    """遍历已包芯片，把当前版本记入台账（_wrap_all_bricks 之后调用一次）。"""
    for ctrl in all_controllers():
        for h in ctrl.handlers():
            _ledger.record(h.name, h.manifest.version, h.endpoint)


def version_history(name: str) -> list[dict]:
    return _ledger.history(name)


# ── 热插拔 ────────────────────────────────────────────────
async def plug(brick: Brick):
    """运行时插入砖：注册 + 包芯片 + 记版本。已包则跳过（幂等）。"""
    registry.register(brick)
    if get_handle(brick.manifest.name) is None:
        wrap_brick(brick)
    handle = get_handle(brick.manifest.name)
    if handle is not None:
        brick.enable()
        _ledger.record(brick.manifest.name, brick.manifest.version, handle.endpoint)
    return handle


async def unplug(name: str) -> bool:
    """运行时拔出砖：释放芯片资源 + 从总线注销 + 停用（保留 registry 以便重插）。"""
    handle = get_handle(name)
    if handle is None:
        return False
    await handle.dispose()
    ctrl = handle.bus
    if ctrl is not None:
        ctrl._handles.pop(name, None)  # noqa: SLF001  同包内部聚合访问
    brick = registry.get(name)
    if brick is not None:
        brick.disable()
    _LOGGER.info("砖 %s 已热拔出（芯片释放 + 停用）", name)
    return True


async def rollback(name: str) -> dict:
    """回滚到加载时点：子进程砖 = 重启运行时进程；进程内砖 = 重激活芯片。

    进程内砖无法真正重载 Python 模块（风险高），故为 best-effort 重激活；
    子进程砖（ipc://）则可真实杀死并重拉，等价于运行时回滚。
    """
    handle = get_handle(name)
    if handle is None:
        return {"ok": False, "reason": "not_found"}
    # 先释放旧资源，再重激活（子进程会被真正重启）。
    await handle.dispose()
    await handle.load()
    _ledger.record(name, handle.manifest.version, handle.endpoint)
    return {
        "ok": True,
        "name": name,
        "transport": type(handle.transport).__name__,
        "restarted": type(handle.transport).__name__ == "SubprocessTransport",
    }


# ── MCP 兼容适配 ──────────────────────────────────────────
class _McpAdapter:
    """把砖的 capability 暴露为 MCP 工具协议（tools/list + tools/call）。"""

    def tools_list(self) -> list[dict]:
        tools: list[dict] = []
        for ctrl in all_controllers():
            for h in ctrl.handlers():
                brick = h.brick
                # 砖可显式声明 mcp_tools（[{name,description,input_schema}]）；
                # 否则从 capabilities 中挑可调用键自动暴露。
                declared = getattr(brick.manifest, "mcp_tools", None)
                if declared:
                    for t in declared:
                        tools.append({
                            "name": f"{brick.manifest.name}/{t['name']}",
                            "description": t.get("description", brick.manifest.title),
                            "inputSchema": t.get("input_schema", {"type": "object", "properties": {}}),
                        })
                    continue
                for key, val in brick.capabilities.items():
                    if key.startswith("_") or not callable(val) or inspect.isclass(val):
                        continue
                    tools.append({
                        "name": f"{brick.manifest.name}/{key}",
                        "description": f"{brick.manifest.title} :: {key}",
                        "inputSchema": {"type": "object", "properties": {}},
                    })
        return tools

    async def tools_call(self, tool_name: str, arguments: dict) -> Any:
        if "/" not in tool_name:
            raise ValueError(f"工具名须为 <砖名>/<能力>，收到 {tool_name}")
        brick_name, cap_key = tool_name.split("/", 1)
        brick = registry.get(brick_name)
        if brick is None:
            raise ValueError(f"砖 {brick_name} 不存在")
        fn = brick.capabilities.get(cap_key)
        if not callable(fn) or inspect.isclass(fn):
            raise ValueError(f"{tool_name} 不是可调用的能力")
        result = await _arbiter.invoke_async(brick_name, fn, (), arguments or {})
        # MCP 要求 JSON 可序列化；bytes 是音频等二进制常见返回，降级为长度标注。
        if isinstance(result, bytes):
            return {"__bytes_len__": len(result), "note": "二进制结果不通过 MCP 透传"}
        return result


_mcp = _McpAdapter()


class _McpCallBody(BaseModel):
    tool: str
    arguments: dict = {}


@router.get("/tools", dependencies=[Depends(require_api_token)])
async def mcp_tools() -> dict:
    """MCP tools/list：列出全部可经 MCP 消费的砖能力。"""
    return {"tools": _mcp.tools_list()}


@router.post("/call", dependencies=[Depends(require_api_token)])
async def mcp_call(body: _McpCallBody) -> dict:
    """MCP tools/call：调用指定砖能力，结果经仲裁层（遥测/健康）。"""
    try:
        result = await _mcp.tools_call(body.tool, body.arguments)
    except ValueError as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(exc))
    return {"tool": body.tool, "result": result}


@router.get("/status", dependencies=[Depends(require_api_token)])
async def mcp_status() -> dict:
    """MCP 兼容层自检：已暴露工具数 + 各砖版本历史条数。"""
    return {
        "tools": len(_mcp.tools_list()),
        "version_history": {name: len(v) for name, v in _ledger._history.items()},  # noqa: SLF001
    }
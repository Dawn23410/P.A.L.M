"""monitor 砖：运行态监控（游戏检测 + 模式解析）。

作为「core 砖」构想的真实落点（项目无 core 砖，app.core 仅含 config/logging）。
经 capabilities 暴露 is_game_running / resolve_effective_mode / get_run_mode_config，
供 agent 砖读取，严格守砖块契约——零跨砖 import。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from palm_sdk.security import require_api_token
from palm_sdk.bricks.base import Brick, BrickManifest, registry
from .game_detector import is_game_running
from .mode_resolver import get_run_mode_config, resolve_effective_mode

router = APIRouter(prefix="/api/monitor", tags=["monitor"])


@router.get("/game-running", dependencies=[Depends(require_api_token)])
def api_game_running():
    # 前端/agent 查询当前是否处于游戏态（联动模式指示）。
    return {"running": is_game_running()}


@router.get("/effective-mode", dependencies=[Depends(require_api_token)])
def api_effective_mode():
    # 返回当前有效运行模式（max/eco），含 auto 经游戏态解析后的结果。
    mode, locked = get_run_mode_config()
    return {"effective_mode": resolve_effective_mode(mode, locked)}


brick = Brick(
    manifest=BrickManifest(
        name="monitor",
        title="运行监控",
        description="游戏进程检测与 Max/Eco 模式解析，经 capabilities 供 agent 读取，不直连 import。",
        bus_type="ram",
    ),
    router=router,
    capabilities={
        "is_game_running": is_game_running,
        "resolve_effective_mode": resolve_effective_mode,
        "get_run_mode_config": get_run_mode_config,
    },
)
registry.register(brick)
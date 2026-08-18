"""运行模式解析：用户设定(max/eco/auto) + 游戏态 + 锁定 → 有效模式。

auto 且检测到游戏且未锁定 → eco（保护游戏帧率，小模型轻量推理）；
否则用用户显选，或回退 max。模式只影响主动/闲时层，实时对话始终走 LLM。
"""
from __future__ import annotations

from ._settings import load_settings
from .game_detector import is_game_running


def get_run_mode_config() -> tuple[str, bool]:
    # 返回 (run_mode, run_mode_locked)；缺省 auto / 未锁定。
    s = load_settings()
    return s.get("runMode", "auto"), bool(s.get("runModeLocked", False))


def resolve_effective_mode(
    run_mode: str | None = None,
    locked: bool | None = None,
    is_game: bool | None = None,
) -> str:
    # 解析有效模式：max/eco 显选直接用；auto 结合游戏态与锁定决定。
    if run_mode is None or locked is None:
        run_mode, locked = get_run_mode_config()
    if run_mode in ("max", "eco"):
        return run_mode
    game = is_game if is_game is not None else is_game_running()
    if game and not locked:
        return "eco"
    return "max"

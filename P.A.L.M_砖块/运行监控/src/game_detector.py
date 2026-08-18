"""游戏进程检测：后端 Python 进程经 psutil 扫描运行中的进程名判定游戏态。

按设计前端不跑常驻监听（React 生命周期内跑不了后台进程监控），检测放后端，
按需查询（不拉线程、不缓存），命中游戏清单即视为游戏态。游戏态用于联动 Max/Eco 切换。
"""
from __future__ import annotations

from ._settings import load_settings

# 默认游戏进程清单；用户可在设置 game_process_list 覆盖。
_DEFAULT_GAMES = ["LeagueOfLegends.exe", "Steam.exe", "GameExecutable.exe"]


def get_game_process_list() -> list[str]:
    # 用户可在设置 game_process_list 覆盖默认清单；缺省用内置列表。
    return list(load_settings().get("game_process_list", _DEFAULT_GAMES))


def is_game_running(process_names: list[str] | None = None) -> bool:
    # 按需扫描进程名（不缓存、不拉线程）；命中清单即 True。process_names 供测试注入。
    try:
        import psutil
    except ImportError:
        # 未装 psutil 时降级为「非游戏态」，不阻断主流程。
        return False
    targets = {g.lower() for g in (process_names or get_game_process_list())}
    if not targets:
        return False
    for proc in psutil.process_iter(["name"]):
        try:
            name = (proc.info.get("name") or "").lower()
        except Exception:
            continue
        if name in targets:
            return True
    return False

"""Token 用量服务：配额拦截（收敛自 usage 砖 brick）。

记账与查询已由同目录 token_ledger（SQLite 持久化）承担；本模块只负责
「每日/每月配额 → 是否超额」的判定，供对话链路在取流前拦截。
配额单向依赖应用设置服务（经服务容器取），不跨模块直接 import。
"""
from __future__ import annotations

from palm._core.container import container
from .token_ledger import current_usage


def _token_limits() -> tuple[int, int]:
    """返回 (每日上限 token, 每月上限 token)，0 表示不限制。

    经服务容器读应用设置（每日/每月限额以千为单位存储，转回原始 token 数）。
    """
    settings_brick = container.get("settings")
    cfg: dict = {}
    if settings_brick:
        loader = settings_brick.capabilities.get("load_app_settings")
        if loader:
            try:
                cfg = loader() or {}
            except Exception:  # noqa: BLE001
                cfg = {}
    daily_k = int(cfg.get("dailyTokenLimit") or 0)
    monthly_k = int(cfg.get("monthlyTokenLimit") or 0)
    return daily_k * 10, monthly_k * 1000


def check_quota() -> tuple[bool, str | None]:
    """返回 (是否超额, 超额时的友好中文提示)；未设限或未达上限则放行。"""
    daily_limit, monthly_limit = _token_limits()
    if daily_limit <= 0 and monthly_limit <= 0:
        return (False, None)
    used_daily, used_monthly = current_usage()
    if daily_limit > 0 and used_daily >= daily_limit:
        return (
            True,
            f"每日 Token 限额已用尽（今日已用 {used_daily:,} / 上限 {daily_limit:,}）。"
            f"请于明日 0 点后重置，或在「设置 › Token限制」中调高额度。",
        )
    if monthly_limit > 0 and used_monthly >= monthly_limit:
        return (
            True,
            f"每月 Token 限额已用尽（本月已用 {used_monthly:,} / 上限 {monthly_limit:,}）。"
            f"请于下月 1 日重置，或在「设置 › Token限制」中调高额度。",
        )
    return (False, None)


def assert_quota() -> None:
    """超额即抛 QuotaExceededError（由调用方决定展示方式）。"""
    exceeded, quota_msg = check_quota()
    if exceeded:
        raise QuotaExceededError(quota_msg)


class QuotaExceededError(Exception):
    """Token 配额耗尽。"""

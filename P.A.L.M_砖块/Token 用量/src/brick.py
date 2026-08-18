"""usage 砖块：Token 用量台账与配额拦截。

承载「Token 用量」这一独立功能：落盘逐请求明细（Data/.token_usage.json）、
提供查询端点 /api/token-usage，并经 settings 砖能力读取每日 / 每月配额做拦截。
配额逻辑单向依赖 settings 砖；记账由 chat 砖（llm）在流末经本砖能力调用，不跨砖直接 import。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query

from palm_sdk.bricks.base import Brick, BrickManifest, registry
from palm_sdk.security import require_api_token
from .token_ledger import current_usage, query_records, record_request

router = APIRouter(prefix="/api", tags=["usage"])


def _token_limits() -> tuple[int, int]:
    """返回 (每日上限 token, 每月上限 token)，0 表示不限制。

    经 settings 砖的 capabilities 读取应用设置，避免跨砖 import；读不到时回退为不限制。
    """
    settings_brick = registry.get("settings")
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
    """返回 (是否超额, 超额时的友好中文提示)。

    读设置中的每日 / 每月配额，与当前已用量比较；未设限或用量未达上限则放行。
    """
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


def record_usage(
    chat_id: str,
    model: str,
    provider: str,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
) -> None:
    """记录一次对话的 Token 用量明细（供 chat 砖流末调用）。"""
    try:
        record_request(
            chat_id=chat_id,
            model=model,
            provider=provider,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
    except Exception:  # noqa: BLE001
        logging.getLogger("usage").exception("写入 Token 用量明细失败")


@router.get("/token-usage", dependencies=[Depends(require_api_token)])
async def get_token_usage(
    start_date: str | None = Query(None, description="起始日期 YYYY-MM-DD"),
    end_date: str | None = Query(None, description="结束日期 YYYY-MM-DD"),
    model: str | None = Query(None, description="模型名模糊匹配"),
    provider: str | None = Query(None, description="供应商精确匹配"),
    limit: int = Query(200, ge=1, le=1000, description="最大返回条数"),
):
    """查询逐请求 Token 用量明细，按时间倒序返回（最新在前）。"""
    records = query_records(
        start_date=start_date,
        end_date=end_date,
        model=model,
        provider=provider,
        limit=limit,
    )
    return {"records": records}


brick = Brick(
    manifest=BrickManifest(
        name="usage",
        title="Token 用量",
        description="Token 用量明细台账、配额读取与超额拦截（数据落盘，依赖 settings 砖读配额）。",
        bus_type="ram",
    ),
    router=router,
    capabilities={
        # 经注册表暴露能力，供 chat 砖（llm）在入口拦截、流末记账时调用，不跨砖 import。
        "check_quota": check_quota,
        "record_usage": record_usage,
    },
)
registry.register(brick)
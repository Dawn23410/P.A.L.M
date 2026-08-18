"""游戏全局状态落盘（Data/game_state.json，原子写）。

仅存全局用户级状态：累计经验、连续登录天数、上次结算日期、今日任务进度、
今日聊天计数、今日规划计数。其余（角色好感度、特殊任务明细）不在此文件。
特殊任务经验由调用方直接累加 total_exp，状态层不关心其来源。
"""
from __future__ import annotations

import json
import os
from datetime import date

from palm_sdk.core.config import settings
from palm_sdk.bricks._shared.paths import fallback_dir, resolve_storage

_STATE_PATH = resolve_storage("game_state.json", brick_file=__file__)

TODAY = date.today().isoformat


def load_state() -> dict:
    """读取游戏状态；缺失/损坏返回全新空状态。"""
    if not os.path.isfile(_STATE_PATH):
        return _fresh_state()
    try:
        with open(_STATE_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return _fresh_state()
    if not isinstance(data, dict):
        return _fresh_state()
    # 合并默认值，兼容旧结构缺字段。
    base = _fresh_state()
    base.update(data)
    return base


def save_state(state: dict) -> None:
    """原子写状态：先落临时文件再 replace，避免半写损坏。"""
    os.makedirs(os.path.dirname(_STATE_PATH), exist_ok=True)
    tmp = _STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, _STATE_PATH)


def _fresh_state() -> dict:
    return {
        "total_exp": 0,
        "streak_days": 0,
        "last_checkin_date": "",
        "last_reset_date": "",
        "daily_chat_count": 0,
        "daily_plan_count": 0,
        "daily_tasks_done": [],  # 今日已完成任务 key 列表
        "daily_task_exp_earned": 0,  # 今日已发放的日常任务经验（封顶 DAILY_TASK_EXP_CAP）
        "unlocked_items": [],  # 已解锁道具 key 列表（如 affinity_display 开启好感度显示）
        "currency": 0,  # 当前星砂余额（跨天保留，仅商城消费扣减）
        "currency_earned_total": 0,  # 累计获得星砂（统计用，不参与消费）
        "daily_currency_earned": 0,  # 今日已发放的日常任务星砂（封顶 DAILY_CURRENCY_CAP）
        "purchase_history": [],  # 消费台账 [{item, cost, ts}]
    }


def rollover_if_new_day(state: dict) -> dict:
    """跨天时重置每日计数与任务（保留连续登录天数与累计经验）。

    连续登录判定：last_checkin_date 为昨日 → streak+1；更早或为空 → streak=1。
    返回是否发生了跨天重置（供调用方决定是否触发 login 任务）。
    """
    today = TODAY()
    if state.get("last_reset_date") == today:
        return state  # 当天已结算过每日数据

    last_checkin = state.get("last_checkin_date", "")
    yesterday = date.fromisoformat(today)
    yesterday = (yesterday.toordinal() - 1)
    yesterday = date.fromordinal(yesterday).isoformat()

    new_streak = 1
    if last_checkin == yesterday:
        new_streak = int(state.get("streak_days", 0)) + 1
    elif last_checkin == today:
        new_streak = int(state.get("streak_days", 0)) or 1

    state["streak_days"] = new_streak
    state["last_reset_date"] = today
    state["daily_chat_count"] = 0
    state["daily_plan_count"] = 0
    state["daily_tasks_done"] = []
    state["daily_task_exp_earned"] = 0
    state["daily_currency_earned"] = 0  # 每日货币上限跨天重置（余额不清）
    return state


def is_daily_task_done(state: dict, key: str) -> bool:
    return key in (state.get("daily_tasks_done") or [])


def mark_daily_task(state: dict, key: str) -> bool:
    """标记每日任务完成；返回是否首次完成（首完成才奖励）。"""
    done = state.setdefault("daily_tasks_done", [])
    if key in done:
        return False
    done.append(key)
    return True


def grant_daily_task_exp(state: dict, amount: int) -> int:
    """发放日常任务经验并受每日总额约束（DAILY_TASK_EXP_CAP 来自 xp.py）。

    返回实际发放额（被剩余额度截断）。调用方需先 mark_daily_task 确认是首完成。
    """
    from .xp import DAILY_TASK_EXP_CAP

    if amount <= 0:
        return 0
    earned = int(state.get("daily_task_exp_earned", 0))
    remaining = max(DAILY_TASK_EXP_CAP - earned, 0)
    granted = min(amount, remaining)
    state["daily_task_exp_earned"] = earned + granted
    return granted


def grant_daily_currency(state: dict, amount: int) -> int:
    """发放日常任务星砂并受每日总额约束（DAILY_CURRENCY_CAP 来自 xp.py）。

    与经验上限相互独立：经验来自 token+任务，星砂仅来自任务与游戏。
    返回实际发放额（被剩余额度截断）。调用方需先 mark_daily_task 确认是首完成。
    """
    from .xp import DAILY_CURRENCY_CAP

    if amount <= 0:
        return 0
    earned = int(state.get("daily_currency_earned", 0))
    remaining = max(DAILY_CURRENCY_CAP - earned, 0)
    granted = min(amount, remaining)
    state["daily_currency_earned"] = earned + granted
    return granted


def add_currency(state: dict, amount: int) -> None:
    """累加星砂余额与累计获得（不校验上限，调用方负责上限/扣减）。"""
    amount = int(amount)
    if amount <= 0:
        return
    state["currency"] = int(state.get("currency", 0)) + amount
    state["currency_earned_total"] = int(state.get("currency_earned_total", 0)) + amount
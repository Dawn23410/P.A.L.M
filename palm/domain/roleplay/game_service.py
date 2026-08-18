"""游戏生态服务：经验结算 / 每日任务 / 星砂货币 / 商城（收敛自 game 砖）。

经验/等级/系数纯逻辑在同目录 xp.py；状态落盘在同目录 state.py。
对外经服务容器暴露 award_chat_xp / award_plan_xp / has_item / unlock_item /
purchase_item，供对话与角色链路调用，不跨模块直接 import。
"""
from __future__ import annotations

from datetime import date, datetime

from .state import (
    add_currency,
    grant_daily_currency,
    grant_daily_task_exp,
    is_daily_task_done,
    load_state,
    mark_daily_task,
    rollover_if_new_day,
    save_state,
)
from .xp import (
    DAILY_TASK_CURRENCY,
    DAILY_TASK_LABELS,
    DAILY_TASK_REWARD,
    DAILY_TASKS,
    LEVELS_PER_STAGE,
    STAGE_COUNT,
    chat_xp,
    daily_task_currency,
    derive_level,
    login_currency,
)

# 商城商品目录：强化（永久解锁）/ 道具（一次性消耗）；购买即解锁对应能力。
SHOP_CATALOG: dict[str, dict] = {
    "affinity_display": {
        "name": "好感度显示",
        "price": 200,
        "desc": "解锁好感度数值与关系阶段的显示（默认对所有前台隐藏）。",
        "category": "强化",
    },
}
KNOWN_ITEMS = set(SHOP_CATALOG.keys())


def _build_public_state() -> dict:
    """读取状态→跨天结算→推导等级，返回前端所需全部字段。"""
    state = load_state()
    rollover_if_new_day(state)
    save_state(state)
    level = derive_level(state["total_exp"])
    return {
        "total_exp": level.total_exp,
        "stage": level.stage,
        "level": level.level,
        "total_level_index": level.total_level_index,
        "stage_count": STAGE_COUNT,
        "levels_per_stage": LEVELS_PER_STAGE,
        "exp_in_stage": level.exp_in_stage,
        "exp_for_level": level.exp_for_level,
        "exp_to_next_level": level.exp_to_next_level,
        "progress_pct": level.progress_pct,
        "streak_days": state["streak_days"],
        "currency": int(state.get("currency", 0)),
        "currency_earned_total": int(state.get("currency_earned_total", 0)),
        "daily_chat_count": state["daily_chat_count"],
        "daily_plan_count": state["daily_plan_count"],
        "daily_tasks": [
            {
                "key": k,
                "label": DAILY_TASK_LABELS.get(k, k),
                "done": is_daily_task_done(state, k),
                "reward": DAILY_TASK_REWARD,
            }
            for k in DAILY_TASKS
        ],
        "last_checkin_date": state["last_checkin_date"],
    }


def _apply_award(
    state: dict,
    kind: str,
    token_count: int,
    raw_exp: int,
    affinity: float,
    currency: int = 0,
    dynamics: float = 0.0,
) -> tuple[int, int] | None:
    """在给定 state 上结算一次经验与星砂，返回 (获得经验, 获得星砂) 或 None（未知 kind）。

    经验走 token/任务，星砂仅走任务与游戏（不随每条消息 token 发放）；
    日常任务星砂受每日上限约束，游戏货币弹性发放、不计入每日上限。
    """
    chat_gain = 0
    task_gain = 0
    task_cur = 0

    if kind == "chat":
        chat_gain += chat_xp(token_count, affinity, state["streak_days"], dynamics)
        state["daily_chat_count"] += 1
        if mark_daily_task(state, "chat_once"):
            task_gain += DAILY_TASK_REWARD
            task_cur += daily_task_currency("chat_once")
        if state["daily_chat_count"] >= 10 and mark_daily_task(state, "chat_ten"):
            task_gain += DAILY_TASK_REWARD
            task_cur += daily_task_currency("chat_ten")
    elif kind == "plan":
        if mark_daily_task(state, "plan_once"):
            task_gain += DAILY_TASK_REWARD
            task_cur += daily_task_currency("plan_once")
    elif kind == "special":
        state["total_exp"] += max(raw_exp, 0)
        granted = max(int(currency), 0)
        add_currency(state, granted)
        return max(raw_exp, 0), granted
    else:
        return None

    granted_task = grant_daily_task_exp(state, task_gain)
    gained = chat_gain + granted_task
    state["total_exp"] += gained
    granted_cur = grant_daily_currency(state, task_cur)
    add_currency(state, granted_cur)
    return gained, granted_cur


def award_chat_xp(token_count: int, affinity: float = 0.0, dynamics: float = 0.0) -> int:
    """结算一次聊天的经验（含每日任务与星砂）。返回获得经验。"""
    state = load_state()
    rollover_if_new_day(state)
    result = _apply_award(state, "chat", token_count, 0, affinity, 0, dynamics)
    save_state(state)
    return result[0] if result else 0


def award_plan_xp() -> int:
    """自动规划结束后结算 plan_once 每日任务（含星砂）。返回获得经验。"""
    state = load_state()
    rollover_if_new_day(state)
    result = _apply_award(state, "plan", 0, 0, 0.0, 0, 0.0)
    save_state(state)
    return result[0] if result else 0


def checkin() -> dict:
    """每日登录打卡：跨天结算 + 触发 login 任务（受每日任务经验总额约束）。"""
    state = load_state()
    rollover_if_new_day(state)
    today = date.today().isoformat()
    gained_cur = 0
    # 登录星砂：基础 + 连续登录奖励，与任务星砂独立、不计入每日任务上限。
    login_cur = login_currency(state["streak_days"])
    if login_cur > 0:
        add_currency(state, login_cur)
        gained_cur += login_cur
    state["last_checkin_date"] = today
    gained = 0
    if mark_daily_task(state, "login"):
        gained += grant_daily_task_exp(state, DAILY_TASK_REWARD)
    state["total_exp"] += gained
    save_state(state)
    return {"gained_exp": gained, "gained_currency": gained_cur, "state": _build_public_state()}


def unlock_item(item_key: str) -> dict:
    """解锁一个道具（幂等）。返回最新解锁列表。"""
    if item_key not in KNOWN_ITEMS:
        return {"error": f"未知道具：{item_key}"}
    state = load_state()
    rollover_if_new_day(state)
    items = state.setdefault("unlocked_items", [])
    if item_key not in items:
        items.append(item_key)
    save_state(state)
    return {"unlocked_items": list(items)}


def has_item(item_key: str) -> bool:
    """供其它模块查询某道具是否已解锁（缺失降级 False）。"""
    try:
        state = load_state()
        return item_key in (state.get("unlocked_items") or [])
    except Exception:
        return False


def purchase_item(key: str) -> dict:
    """购买道具：校验余额→扣减→解锁→记台账（同一次 state、单次 save，原子）。"""
    if key not in SHOP_CATALOG:
        return {"error": f"未知商品：{key}"}
    state = load_state()
    rollover_if_new_day(state)
    price = SHOP_CATALOG[key]["price"]
    balance = int(state.get("currency", 0))
    if balance < price:
        return {"error": "星砂不足", "currency": balance, "price": price}
    if key in (state.get("unlocked_items") or []):
        return {"error": "已拥有", "currency": balance}
    state["currency"] = balance - price
    items = state.setdefault("unlocked_items", [])
    if key not in items:
        items.append(key)
    state.setdefault("purchase_history", []).append(
        {"item": key, "cost": price, "ts": datetime.now().isoformat(timespec="seconds")}
    )
    save_state(state)
    return {"ok": True, "item": key, "currency": state["currency"], "state": _build_public_state()}

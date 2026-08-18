"""game 砖块：游戏性生态（当前落地「经验系统」）。

提供：全局用户级经验状态查询、每日登录打卡、聊天/特殊任务经验结算、等级推导。
经验/等级/系数纯逻辑在 xp.py；状态落盘在 state.py。好感度系数经 affection 砖
capabilities 取（缺失降级 1.0），不直接 import 角色卡/记忆层。
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends

from palm_sdk.bricks.base import Brick, BrickManifest, registry
from palm_sdk.security import require_api_token
from .state import (
    load_state,
    save_state,
    rollover_if_new_day,
    is_daily_task_done,
    mark_daily_task,
    grant_daily_task_exp,
    grant_daily_currency,
    add_currency,
)
from .xp import (
    derive_level,
    chat_xp,
    DAILY_TASKS,
    DAILY_TASK_LABELS,
    DAILY_TASK_REWARD,
    STAGE_COUNT,
    LEVELS_PER_STAGE,
    DAILY_TASK_CURRENCY,
    DAILY_CURRENCY_CAP,
    login_currency,
    daily_task_currency,
)

router = APIRouter(prefix="/api/game", tags=["game"])


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


@router.get("/status", dependencies=[Depends(require_api_token)])
async def get_game_status():
    """系统探测：砖已挂载且经验系统已落地。"""
    return {"registered": True, "implemented": True, "module": "game"}


@router.get("/state", dependencies=[Depends(require_api_token)])
async def get_game_state():
    """查询全局经验状态、等级、每日任务与连续登录天数。"""
    return _build_public_state()


@router.post("/checkin", dependencies=[Depends(require_api_token)])
async def post_checkin():
    """每日登录打卡：跨天结算 + 触发 login 任务（受每日任务经验总额约束）。"""
    from datetime import date

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
    public = _build_public_state()
    return {"gained_exp": gained, "gained_currency": gained_cur, "state": public}


@router.post("/award", dependencies=[Depends(require_api_token)])
async def post_award(
    payload: dict = Body(default={}),
):
    """经验结算入口（聊天 / 特殊任务）。

    body 支持：
      - kind: "chat" 聊天 → 需 token_count（本次对话真实消耗 token）；按 token 法累加经验 + 推进 chat_once/chat_ten 任务
      - kind: "plan" 自动规划 → 推进 plan_once 任务
      - kind: "special" 特殊任务（如下棋）→ 需 raw_exp 原始经验，不限、不计入每日任务
    返回本次获得经验与最新状态。
    """
    state = load_state()
    rollover_if_new_day(state)

    kind = payload.get("kind", "chat")
    token_count = int(payload.get("token_count", 0) or 0)
    raw_exp = int(payload.get("raw_exp", 0) or 0)
    affinity = float(payload.get("affinity", 0.0) or 0.0)
    currency = int(payload.get("currency", 0) or 0)

    result = _apply_award(state, kind, token_count, raw_exp, affinity, currency)
    if result is None:
        return {"error": f"未知 kind: {kind}"}

    gained, gained_cur = result
    save_state(state)
    public = _build_public_state()
    return {"gained_exp": gained, "gained_currency": gained_cur, "state": public}


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

    经验与星砂同源但解耦：经验走 token/任务，星砂仅走任务与游戏（不随每条消息 token 发放）。
    日常任务星砂受 daily_currency_earned 每日上限约束；游戏(特殊任务)货币经 currency 参数弹性发放、不计入每日上限。
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
        # 游戏货币弹性发放（调用方给 currency），不计入每日任务上限。
        granted = max(int(currency), 0)
        add_currency(state, granted)
        return max(raw_exp, 0), granted
    else:
        return None

    # 日常任务经验统一经 grant_daily_task_exp 受每日总额约束（封顶 DAILY_TASK_EXP_CAP）。
    granted_task = grant_daily_task_exp(state, task_gain)
    gained = chat_gain + granted_task
    state["total_exp"] += gained
    # 任务星砂受每日上限约束（封顶 DAILY_CURRENCY_CAP）。
    granted_cur = grant_daily_currency(state, task_cur)
    add_currency(state, granted_cur)
    return gained, granted_cur


# 经注册表暴露能力，供其它砖（如 agent 结算聊天经验）调用，不跨砖 import。
def award_chat_xp(token_count: int, affinity: float = 0.0, dynamics: float = 0.0) -> int:
    """供其它砖调用：结算一次聊天的经验（含每日任务与星砂）。返回获得经验。

    内部一并发放星砂（经 _apply_award）；dynamics 为当下心情线，仅微调系数。
    """
    state = load_state()
    rollover_if_new_day(state)
    result = _apply_award(state, "chat", token_count, 0, affinity, 0, dynamics)
    save_state(state)
    return result[0] if result else 0


def award_plan_xp() -> int:
    """供 agent 砖在自动规划结束后结算 plan_once 每日任务（含星砂）。返回获得经验。"""
    state = load_state()
    rollover_if_new_day(state)
    result = _apply_award(state, "plan", 0, 0, 0.0, 0, 0.0)
    save_state(state)
    return result[0] if result else 0


# ── 商城与道具（星砂消费唯一出口） ──

# 商城商品目录：key → {name, price, desc, category}。
# category: 强化(永久解锁，一次购得永久生效) / 道具(一次性消耗，用完即止)。
# 仅「一次性消耗」才算道具，永久内容归类为强化。购买即解锁对应能力（复用 unlocked_items）。
SHOP_CATALOG: dict[str, dict] = {
    "affinity_display": {
        "name": "好感度显示",
        "price": 200,
        "desc": "解锁好感度数值与关系阶段的显示（默认对所有前台隐藏）。",
        "category": "强化",
    },
}
KNOWN_ITEMS = set(SHOP_CATALOG.keys())  # 解锁/购买校验仍用 key 集合


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
    """供其它砖查询某道具是否已解锁（缺失降级 False）。"""
    try:
        state = load_state()
        return item_key in (state.get("unlocked_items") or [])
    except Exception:
        return False


def _do_purchase(key: str) -> dict:
    """购买道具：校验余额→扣减→解锁→记台账（同一次 state、单次 save，原子）。"""
    from datetime import datetime

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
    # 先扣币，再写入解锁与台账，整体一次性 save；任一处不落盘即不生效。
    state["currency"] = balance - price
    items = state.setdefault("unlocked_items", [])
    if key not in items:
        items.append(key)
    state.setdefault("purchase_history", []).append(
        {"item": key, "cost": price, "ts": datetime.now().isoformat(timespec="seconds")}
    )
    save_state(state)
    public = _build_public_state()
    return {"ok": True, "item": key, "currency": state["currency"], "state": public}


@router.post("/unlock-item", dependencies=[Depends(require_api_token)])
async def post_unlock_item(payload: dict = Body(default={})):
    """解锁道具（如 affinity_display 开启好感度显示）。"""
    key = payload.get("item") or payload.get("key") or ""
    return unlock_item(key)


@router.get("/items", dependencies=[Depends(require_api_token)])
async def get_items():
    """列出已解锁道具与全部商品说明。"""
    state = load_state()
    return {
        "unlocked_items": state.get("unlocked_items", []),
        "known_items": {k: v["desc"] for k, v in SHOP_CATALOG.items()},
    }


@router.get("/shop", dependencies=[Depends(require_api_token)])
async def get_shop():
    """列出商城商品（含是否已拥有、当前余额是否够买）。"""
    state = load_state()
    balance = int(state.get("currency", 0))
    owned = set(state.get("unlocked_items", []))
    items = [
        {
            "key": key,
            "name": meta["name"],
            "price": meta["price"],
            "desc": meta["desc"],
            "category": meta["category"],
            "owned": key in owned,
            "affordable": balance >= meta["price"],
        }
        for key, meta in SHOP_CATALOG.items()
    ]
    return {"currency": balance, "items": items}


@router.post("/purchase", dependencies=[Depends(require_api_token)])
async def post_purchase(payload: dict = Body(default={})):
    """购买道具：消耗星砂解锁对应隐藏能力。"""
    key = payload.get("item") or payload.get("key") or ""
    return _do_purchase(key)


brick = Brick(
    manifest=BrickManifest(
        name="game",
        title="游戏生态",
        description="游戏性生态：经验系统（10阶×100级全局用户级、每日任务、好感度/累登系数、特殊任务）+ 星砂货币体系（登录/任务/游戏获取，商城购买道具消费）。",
        bus_type="ram",
    ),
    router=router,
    capabilities={
        # 经注册表暴露能力，供 agent 砖在对话结束时结算聊天经验时调用，不跨砖 import。
        "award_chat_xp": award_chat_xp,
        "award_plan_xp": award_plan_xp,
        # 道具查询：好感度显示等隐藏能力是否解锁，由 agent 砖经注册表查询，不跨砖 import。
        "has_item": has_item,
        "unlock_item": unlock_item,
        # 程序化购买（如达成条件自动赠送），与 /api/game/purchase 同源。
        "purchase_item": _do_purchase,
    },
)
registry.register(brick)
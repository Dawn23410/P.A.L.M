"""经验系统纯逻辑（与落盘、HTTP 解耦，便于复用与测试）。

等级拓扑（用户拍板，2026-08-03）：
- 全局用户级，共 10 阶（0~9），每阶 100 级（0~99），合计 1000 级。
- 0 阶每级需 1000 Exp；第 n 阶每级需 1000 × (n+1) Exp（等阶递增、同阶难度一致）。
- 各阶满容量 = 100 级 × 每级所需 = 100 × 1000 × (n+1)。

系数：
- 双线好感度系数（替代原占位标量公式）：
  · base(地基·信任，-50~100)：主系数，base 满 100 增幅 70%（上限 1.7）。
  · dynamics(温度计·当下心情，-50~50)：微调，满 50 额外 +0.1（总封顶 1.8）。
  · 负向不降（下限 1.0）；只随关系升温放大经验，绝不惩罚。
- 累登系数：连续登录天数 streak。初始（第 1 天）=1，之后每天增加 0.05，上限增幅 50%
  （系数封顶 1.5，第 11 天起满）。断登（last_checkin 早于昨日）由 state 层将 streak 重置为 1。

聊天经验（最终选定「token」方案，按本次对话真实消耗 token 计）：
- xp = round(token_count / 5000 × 好感度系数 × 累登系数)。
- 5000 为用户拍板的分隔值（早前 token 法备选为 ÷10000，已改为 ÷5000）。

每日任务（固定内容，每项首次完成 +1000 Exp，每日清零，总额封顶 2000）：
- login（每日登录）/ chat_once（当日聊满 1 次）/ chat_ten（当日聊满 10 次）/
  plan_once（当日触发一次自动规划）。
特殊任务（如与角色下棋）经验不限、不计入每日任务，按分数与难度原始累加。
"""
from __future__ import annotations

from dataclasses import dataclass

STAGE_COUNT = 10          # 阶数（0~9）
LEVELS_PER_STAGE = 100    # 每阶级数（0~99）
BASE_EXP_PER_LEVEL = 1000  # 0 阶每级基础经验


def exp_per_level(stage: int) -> int:
    """第 stage 阶每级所需经验：1000 × (stage+1)。"""
    if stage < 0:
        stage = 0
    if stage >= STAGE_COUNT:
        stage = STAGE_COUNT - 1
    return BASE_EXP_PER_LEVEL * (stage + 1)


def stage_capacity(stage: int) -> int:
    """第 stage 阶满级所需累计经验（100 级 × 每级所需）。"""
    return LEVELS_PER_STAGE * exp_per_level(stage)


@dataclass
class LevelInfo:
    stage: int              # 当前阶（0~9）
    level: int              # 当前阶内级（0~99）
    total_level_index: int  # 全局级序号（0~999）
    exp_in_stage: int       # 当前阶已积累经验
    exp_for_level: int      # 当前阶每级所需经验
    exp_to_next_level: int  # 升级还需经验
    progress_pct: float     # 当前级进度（0~100）
    total_exp: int          # 累计总经验


def derive_level(total_exp: int) -> LevelInfo:
    """由累计总经验推导阶段 / 级数 / 进度。"""
    remaining = max(int(total_exp), 0)
    stage = 0
    while stage < STAGE_COUNT - 1:
        cap = stage_capacity(stage)
        if remaining < cap:
            break
        remaining -= cap
        stage += 1
    per = exp_per_level(stage)
    level = min(remaining // per, LEVELS_PER_STAGE - 1)
    exp_in_stage = remaining
    exp_to_next = per - (remaining % per) if level < LEVELS_PER_STAGE - 1 else 0
    progress = (remaining % per) / per * 100 if per else 0.0
    total_level_index = stage * LEVELS_PER_STAGE + level
    return LevelInfo(
        stage=stage,
        level=level,
        total_level_index=total_level_index,
        exp_in_stage=exp_in_stage,
        exp_for_level=per,
        exp_to_next_level=exp_to_next,
        progress_pct=round(progress, 1),
        total_exp=max(int(total_exp), 0),
    )


def affinity_coefficient(base: float, dynamics: float = 0.0) -> float:
    """双线好感度系数（替代原占位标量公式）。

    base(地基·信任，-50~100) 为主系数，满 100 增幅 70%（上限 1.7）；
    dynamics(温度计·当下心情，-50~50) 微调，满 50 额外 +0.1（总封顶 1.8）。
    负向不降（下限 1.0）；只随关系升温放大经验，绝不惩罚。
    """
    base_coef = 1.0 + max(0.0, float(base)) / 100.0 * 0.7
    dyn_coef = max(0.0, float(dynamics)) / 50.0 * 0.1
    return max(1.0, min(1.8, base_coef + dyn_coef))


def streak_coefficient(streak: int) -> float:
    """累登系数：第 1 天=1，之后每天 +0.05，上限增幅 50%（封顶 1.5，第 11 天满）。断登重置由 state 层处理。"""
    return 1.0 + min(max(int(streak) - 1, 0), 10) * 0.05


def chat_xp(token_count: int, affinity: float, streak: int, dynamics: float = 0.0) -> int:
    """聊天经验（token 法）：round(token数/5000 × 双线好感度系数 × 累登系数)。"""
    base = max(int(token_count), 0) / 5000.0
    return round(base * affinity_coefficient(affinity, dynamics) * streak_coefficient(streak))


# 每日任务清单（每项首次完成固定 +1000 Exp，但每日任务经验总和封顶）。
DAILY_TASKS: list[str] = ["login", "chat_once", "chat_ten", "plan_once"]
DAILY_TASK_LABELS: dict[str, str] = {
    "login": "每日登录",
    "chat_once": "当日聊满 1 次",
    "chat_ten": "当日聊满 10 次",
    "plan_once": "触发一次自动规划",
}
DAILY_TASK_REWARD = 1000
# 每日任务经验总和上限（不含聊天字数经验、不含特殊任务）。
DAILY_TASK_EXP_CAP = 2000

# ── 星砂（货币）获取配置 ──
# 原则：星砂只来自「每日任务」与「游戏(特殊任务)」，不随每条消息 token 发放，
# 与经验(EXP) 同源但解耦——EXP 是成长荣誉，星砂是可消费资源。
LOGIN_CURRENCY_BASE = 10  # 每日登录基础星砂
STREAK_CURRENCY_BONUS_PER_WEEK = 5  # 连续登录每满 7 天额外星砂
STREAK_CURRENCY_BONUS_CAP = 20  # 连续登录奖励封顶（避免长期用户爆仓）
# 每日任务星砂（与 EXP 任务并行，但独立数值；login 由 checkin 单独发放，不在此列）。
DAILY_TASK_CURRENCY: dict[str, int] = {
    "chat_once": 5,
    "chat_ten": 20,
    "plan_once": 15,
}
# 每日任务星砂总和上限（不含登录基础、不含游戏特殊任务）。
DAILY_CURRENCY_CAP = 80


def login_currency(streak: int) -> int:
    """每日登录星砂：基础 + 连续登录奖励（每满 7 天 +5，封顶 +20）。"""
    bonus = min(int(streak) // 7 * STREAK_CURRENCY_BONUS_PER_WEEK, STREAK_CURRENCY_BONUS_CAP)
    return LOGIN_CURRENCY_BASE + bonus


def daily_task_currency(key: str) -> int:
    """每日任务星砂：按任务 key 取固定额（未知任务返回 0）。"""
    return DAILY_TASK_CURRENCY.get(key, 0)

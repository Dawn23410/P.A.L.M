"""轻量 cron 调度（移植自 palm services/ops/cron 语义，零依赖 5 字段解析）。

支持标准 5 字段 cron（分 时 日 月 周）：next_time(now) 计算下次触发时刻，
供 schedule_task 的 cron/rrule 类型落地（进程内调度线程每分钟轮询）。
不支持秒级/特殊串（@daily 等按 daily 常量映射）。
"""
from __future__ import annotations

from datetime import datetime, timedelta

# 字段索引与取值范围
_FIELDS = ("minute", "hour", "day", "month", "weekday")
_RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 6))


def _parse_field(expr: str, lo: int, hi: int) -> set[int] | None:
    """解析单字段：* / a-b / a,b,c；非法返回 None。"""
    if expr == "*":
        return set(range(lo, hi + 1))
    values: set[int] = set()
    for part in expr.split(","):
        part = part.strip()
        if "-" in part:
            a, _, b = part.partition("-")
            try:
                a, b = int(a), int(b)
            except ValueError:
                return None
            values.update(range(a, b + 1))
        elif part:
            try:
                values.add(int(part))
            except ValueError:
                return None
    return values if all(lo <= v <= hi for v in values) else None


class Cron:
    """5 字段 cron 表达式；invalid=True 表示解析失败。"""

    def __init__(self, expr: str):
        parts = (expr or "").split()
        self.invalid = len(parts) != 5
        self._sets: dict[str, set[int]] = {}
        if not self.invalid:
            for field, part, (lo, hi) in zip(_FIELDS, parts, _RANGES):
                parsed = _parse_field(part, lo, hi)
                if parsed is None:
                    self.invalid = True
                    break
                self._sets[field] = parsed

    def _matches(self, dt: datetime) -> bool:
        return (dt.minute in self._sets["minute"]
                and dt.hour in self._sets["hour"]
                and dt.day in self._sets["day"]
                and dt.month in self._sets["month"]
                and dt.weekday() in self._sets["weekday"])

    def next_time(self, now: datetime | None = None) -> datetime | None:
        """自 now 起 24h 内最近的下次触发时刻；找不到返回 None（近似，够用）。"""
        if self.invalid:
            return None
        now = now or datetime.now()
        cursor = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
        for _ in range(24 * 60):
            if self._matches(cursor):
                return cursor
            cursor += timedelta(minutes=1)
        return None

    def describe(self) -> str:
        return "无效 cron" if self.invalid else "cron（分 时 日 月 周）"


CRON_ALIASES = {"daily": "0 9 * * *", "weekly": "0 9 * * 1", "monthly": "0 9 1 * *"}

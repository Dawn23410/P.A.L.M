"""调度周期解析：计算任务的「下一次触发时间」。

支持四种周期类型：
- once:    schedule_value = ISO 时间（如 2026-08-05T09:00），到点即触发一次。
- interval:schedule_value = 秒数（如 3600），从上次触发起每 N 秒重复。
- cron:    schedule_value = 标准 5 字段（分 时 日 月 周），自研轻量解析。
- rrule:   schedule_value = RFC5545 RRULE 串（如 FREQ=DAILY;BYHOUR=9），委托 dateutil。

返回 float 时间戳；一次性任务已过期返回 None。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable

_CRON_LIMIT = timedelta(days=366 * 5)  # 5 年扫描上限（覆盖闰日边界）


def _parse_field(field: str, low: int, high: int) -> set[int]:
    """把 cron 单字段解析为允许的整数集合（支持 , - * /）。"""
    result: set[int] = set()
    if field == "*":
        return set(range(low, high + 1))
    for part in field.split(","):
        step = 1
        if "/" in part:
            range_part, step_part = part.split("/")
            step = int(step_part)
        else:
            range_part = part
        if range_part == "*":
            values: Iterable[int] = range(low, high + 1)
        elif "-" in range_part:
            start, end = range_part.split("-")
            values = range(int(start), int(end) + 1)
        else:
            values = [int(range_part)]
        for value in values:
            # 步长只保留「相对下界对齐」的取值，符合 */n 与 a-b/n 语义。
            if (value - low) % step == 0:
                result.add(value)
    return result


def _first_of_next_month(dt: datetime) -> datetime:
    if dt.month == 12:
        return dt.replace(year=dt.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    return dt.replace(month=dt.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)


def _next_hour(dt: datetime, hour_set: set[int]) -> datetime:
    """跳到 dt 之后（含当日）的第一个合法小时 00 分；当日无则进下一日首小时。"""
    later = [h for h in hour_set if h > dt.hour]
    if later:
        return dt.replace(hour=min(later), minute=0, second=0, microsecond=0)
    first = min(hour_set)
    nxt = dt + timedelta(days=1)
    return nxt.replace(hour=first, minute=0, second=0, microsecond=0)


def _next_cron(after_dt: datetime, fields: list[str]) -> datetime | None:
    """从 after_dt 起寻找下一个匹配 5 字段的本地时间。"""
    minute_set = _parse_field(fields[0], 0, 59)
    hour_set = _parse_field(fields[1], 0, 23)
    dom_set = _parse_field(fields[2], 1, 31)
    mon_set = _parse_field(fields[3], 1, 12)
    dow_raw = _parse_field(fields[4], 0, 7)
    # cron 周几：0/7=周日；换算为 Python weekday()（周一=0..周日=6）。
    py_dow: set[int] = {(d - 1) % 7 for d in dow_raw}
    dom_restricted = dom_set != set(range(1, 32))
    dow_restricted = dow_raw != set(range(0, 8))

    candidate = after_dt.replace(second=0, microsecond=0)
    if candidate < after_dt:
        candidate += timedelta(minutes=1)
    limit = candidate + _CRON_LIMIT
    while candidate <= limit:
        if candidate.month not in mon_set:
            candidate = _first_of_next_month(candidate)
            continue
        if dom_restricted and dow_restricted:
            day_ok = candidate.day in dom_set or candidate.weekday() in py_dow
        elif dom_restricted:
            day_ok = candidate.day in dom_set
        elif dow_restricted:
            day_ok = candidate.weekday() in py_dow
        else:
            day_ok = True
        if not day_ok:
            candidate = (candidate + timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            continue
        if candidate.hour not in hour_set:
            candidate = _next_hour(candidate, hour_set)
            continue
        if candidate.minute not in minute_set:
            candidate += timedelta(minutes=1)
            continue
        return candidate
    return None


def _parse_iso(value: str) -> datetime:
    text = value.strip().replace("Z", "")
    return datetime.fromisoformat(text)


def _next_interval(after_ts: float, last_run: float | None, seconds: float) -> float:
    """每隔 seconds 重复，跳过停机期间积压的多次触发，直接对齐到 after 之后。"""
    base = last_run if last_run else after_ts
    nxt = base + seconds
    guard = 0
    while nxt <= after_ts and guard < 1000:
        nxt += seconds
        guard += 1
    if nxt <= after_ts:
        nxt = after_ts + seconds
    return nxt


def _next_rrule(after_dt: datetime, body: str) -> datetime | None:
    from dateutil.rrule import rrulestr

    rule_body = body[6:] if body.upper().startswith("RRULE:") else body
    dtstart = after_dt.strftime("%Y%m%dT%H%M%S")
    rule = rrulestr(f"DTSTART:{dtstart}\nRRULE:{rule_body}")
    return rule.after(after_dt, inc=False)


def compute_next_fire(schedule_type: str, schedule_value: str,
                      after_ts: float, last_run: float | None = None) -> float | None:
    """计算下一次触发时间戳；一次性且已过期返回 None。"""
    after_dt = datetime.fromtimestamp(after_ts)
    if schedule_type == "once":
        try:
            target = _parse_iso(schedule_value)
        except Exception:
            return None
        return target.timestamp() if target > after_dt else None
    if schedule_type == "interval":
        try:
            seconds = float(schedule_value)
        except Exception:
            return None
        if seconds <= 0:
            return None
        return _next_interval(after_ts, last_run, seconds)
    if schedule_type == "cron":
        fields = schedule_value.strip().split()
        if len(fields) != 5:
            return None
        nxt = _next_cron(after_dt, fields)
        return nxt.timestamp() if nxt else None
    if schedule_type == "rrule":
        try:
            nxt = _next_rrule(after_dt, schedule_value)
        except Exception:
            return None
        return nxt.timestamp() if nxt else None
    return None

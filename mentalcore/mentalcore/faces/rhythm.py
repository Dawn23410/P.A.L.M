"""律动面：人格引擎的动态扩展（设计 §6.13）。

为人格引擎服务的运行时动态：时间感知 + 日程切片 + 生日触发。
dynamic_updates_enabled 关闭时整面不注入。
"""
from .base import BaseFace, FaceContext
from ..middleware.inject import InjectionModule

WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"]


class RhythmFace(BaseFace):
    name = "rhythm"

    def produce_module(self, ctx: FaceContext) -> InjectionModule:
        if not ctx.persona.dynamic_updates_enabled:
            return InjectionModule(source=self.name, content="", available=False)
        now = ctx.now
        lines = [f"【此刻】{now.strftime('%Y-%m-%d')} 星期"
                 f"{WEEKDAYS[now.weekday()]} {now.strftime('%H:%M')}。"]
        lines.extend(self._schedule_slice(ctx))
        if self._is_birthday(ctx):
            lines.append("今天是你的生日，可流露被记挂的暖意。")
        return InjectionModule(
            source=self.name, content="\n".join(lines),
            fixed=False, priority=50,
        )

    def _schedule_slice(self, ctx: FaceContext) -> list:
        hour = ctx.now.hour
        for period, thing in ctx.persona.schedule:
            if self._in_period(period, hour):
                return [f"当前日程：{thing}"]
        return []

    @staticmethod
    def _in_period(period: str, hour: int) -> bool:
        if "-" in period:
            try:
                start, end = period.split("-")
                return int(start) <= hour < int(end)
            except ValueError:
                return False
        return period == str(hour)

    def _is_birthday(self, ctx: FaceContext) -> bool:
        b = ctx.persona.birthday
        return bool(b) and ctx.now.strftime("%m-%d") == b

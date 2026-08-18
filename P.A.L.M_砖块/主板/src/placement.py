"""放置调度器（S2 自治控制平面的起点）：按资源/隔离画像给每块砖选最便宜可行的 endpoint。

这是「终极主板」自治能力的第一块智能——把「该隔离还是该进程内」的默认决策
从写死的 _BUS_DEFAULT_ENDPOINT 字典，升级为可扩展的策略链：

- 砖显式 manifest.endpoint 非空 → 覆盖一切（owner 说了算）。
- 否则委托 PlacementScheduler：跑注册的策略链，第一个非空结果即默认 endpoint。
- 默认内置策略：`default_strategy` 依据 总线类型 + 是否自带 subprocess_spec
  （重/不安全运行时）→ 重计算/隔离候选倾向 ipc://，其余 inproc://。
  handle 在 ipc 缺 subprocess_spec 时安全退化为 inproc，绝不因缺配置启动失败。

位置：介于 BusController（per 总线默认）与 BrickHandle（具体芯片）之间，是
「默认 endpoint 决策器」。纯加性，不改动既有 wrap 链路；热重载重算接口预留
（`recompute`），但默认不强制重连（避免破坏运行期连接）。
"""
from __future__ import annotations

import logging
from typing import Callable

from palm_sdk.bricks.base import Brick, BusType

_LOGGER = logging.getLogger(__name__)

# 策略签名：输入 Brick，返回 endpoint 字符串或 None（None = 让下一条策略决定）。
StrategyFn = Callable[[Brick], str | None]


def default_strategy(brick: Brick) -> str | None:
    """内置默认策略：重计算/隔离候选 → ipc，其余 → inproc。

    - 自带 subprocess_spec（重 ML / 不安全运行时）→ ipc://（允许隔离子进程）。
    - PCIE 总线（媒体/重计算）→ ipc://（缺 spec 时 handle 自动退化 inproc，安全）。
    - 其余总线 → inproc://（零开销）。
    """
    caps = brick.capabilities
    if "subprocess_spec" in caps:
        return "ipc://"
    if brick.manifest.bus_type == BusType.PCIE:
        return "ipc://"
    return "inproc://"


class PlacementScheduler:
    """放置调度器：可扩展的策略链，决定每块砖的默认 endpoint。

    设计为单例友好的无状态调度器——策略列表可运行时追加（如按隐私画像、
    按实时负载、按电量档位插拔策略），无需改动 Brick/MS 内核。
    """

    def __init__(self, strategies: list[StrategyFn] | None = None) -> None:
        # 用户策略在前（优先），内置默认策略兜底。
        self._strategies: list[StrategyFn] = list(strategies or [])
        self._strategies.append(default_strategy)

    def register_strategy(self, fn: StrategyFn) -> None:
        """追加一条放置策略（插到内置默认之前）。"""
        self._strategies.insert(len(self._strategies) - 1, fn)

    def recommend(self, brick: Brick) -> str | None:
        """跑策略链，返回第一条非空决策；全空返回 None。"""
        for fn in self._strategies:
            try:
                result = fn(brick)
            except Exception as exc:  # noqa: BLE001  单条策略异常不应阻断放置
                _LOGGER.warning("放置策略 %s 异常: %s", getattr(fn, "__name__", fn), exc)
                continue
            if result:
                return result
        return None

    def policy_hint(self, brick: Brick) -> dict:
        """供前端/调试：砖的资源画像摘要（不泄露实现，只给决策依据）。"""
        return {
            "bus": brick.manifest.bus_type.value,
            "has_subprocess_spec": "subprocess_spec" in brick.capabilities,
            "recommended": self.recommend(brick),
            "manifest_endpoint": brick.manifest.endpoint or None,
            "effective": brick.manifest.endpoint or self.recommend(brick),
        }


# 进程级单例（策略可全局注册一次，所有砖共享）。
_SCHEDULER = PlacementScheduler()


def get_scheduler() -> PlacementScheduler:
    return _SCHEDULER


def recommend_endpoint(brick: Brick) -> str | None:
    """便捷函数：返回砖的默认 endpoint（manifest 覆盖由调用方处理）。"""
    return _SCHEDULER.recommend(brick)
"""零信任 facade 仲裁代理层（L4 闭环）：跨砖能力取用强制经管理芯片路由。

主板隐喻的「北桥仲裁」：砖间严格零互导，只能经 registry capabilities 通信；
此前 get_facade(name) 直接返回裸门面对象，调用方拿去就调，绕过了管理芯片
（BrickHandle）的遥测/健康观测——等于信任边界上有个无人值守的口子。

本层在 get_facade 与消费方之间插一道 FacadeProxy：拦截「方法调用」并改经由
Arbiter.invoke() 落地——记录遥测（延迟/成败）、读取芯片健康态。类/常量属性
原样透传（isinstance / 常量比对不受影响），仅函数/方法被包裹。一切加性，
既有调用点零改动即可被芯片观测。
"""
from __future__ import annotations

import functools
import inspect
import logging
import time
from typing import Any

from .handle import get_handle

_LOGGER = logging.getLogger(__name__)


class _Arbiter:
    """跨砖能力调用的统一仲裁器（轻量、非阻塞）。

    职责边界：只做「观测闭环」——把每次跨砖调用喂给对应 BrickHandle 的遥测汇聚器，
    并读取芯片健康态用于日志/告警。不在此处做权限拦截（权限在 HTTP 边界
    require_permission 已生效）、也不阻断 degraded（熔断在 CapabilitySlot 层）。
    """

    def _record(self, brick_name: str, *, ok: bool, latency_ms: float,
                error: str | None) -> None:
        try:
            from . import telemetry
            telemetry.get_sink().record(brick_name, ok=ok, error=error, latency=latency_ms)
        except Exception:  # noqa: BLE001  遥测失败绝不应影响主链路
            pass

    def invoke(self, brick_name: str, fn: Any, args: tuple, kwargs: dict) -> Any:
        """执行同步 fn 并落遥测。"""
        start = time.perf_counter()
        ok = True
        err: str | None = None
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            ok = False
            err = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            self._record(brick_name, ok=ok, latency_ms=(time.perf_counter() - start) * 1000.0, error=err)

    async def invoke_async(self, brick_name: str, fn: Any, args: tuple, kwargs: dict) -> Any:
        """执行协程 fn 并落遥测。"""
        start = time.perf_counter()
        ok = True
        err: str | None = None
        try:
            result = fn(*args, **kwargs)
            if inspect.iscoroutine(result):
                return await result
            return result
        except Exception as exc:  # noqa: BLE001
            ok = False
            err = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            self._record(brick_name, ok=ok, latency_ms=(time.perf_counter() - start) * 1000.0, error=err)


_arbiter = _Arbiter()


class FacadeProxy:
    """门面代理：包裹砖暴露的 capability 对象，拦截调用改经 Arbiter。

    行为：
    - 类（inspect.isclass）→ 原样返回（保障 isinstance / 子类化）。
    - 其它可调用（函数/方法/协程函数）→ 包裹为同步或异步包装器，经 Arbiter 落遥测。
    - 非可调用（常量/模块/数据）→ 原样返回。
    所有属性访问对消费方透明；不持有目标对象外的可变状态。
    """

    def __init__(self, brick_name: str, target: Any) -> None:
        object.__setattr__(self, "_brick_name", brick_name)
        object.__setattr__(self, "_target", target)

    def __getattr__(self, name: str) -> Any:
        target = object.__getattribute__(self, "_target")
        attr = getattr(target, name)
        if inspect.isclass(attr):
            return attr  # 类原样透传，保障 isinstance / 继承
        if callable(attr):
            if inspect.iscoroutinefunction(attr):
                return self._wrap_async(attr)
            return self._wrap_sync(attr)
        return attr

    def _wrap_sync(self, fn: Any) -> Any:
        brick = object.__getattribute__(self, "_brick_name")

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            return _arbiter.invoke(brick, fn, args, kwargs)
        return wrapper

    def _wrap_async(self, fn: Any) -> Any:
        brick = object.__getattribute__(self, "_brick_name")

        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            return await _arbiter.invoke_async(brick, fn, args, kwargs)
        return wrapper

    def __repr__(self) -> str:
        target = object.__getattribute__(self, "_target")
        return f"<FacadeProxy {object.__getattribute__(self, '_brick_name')} of {target!r}>"


def proxy_facade(brick_name: str, target: Any) -> Any:
    """把裸门面包成代理；target 为 None 时原样返回（砖缺失降级语义不变）。"""
    if target is None:
        return None
    return FacadeProxy(brick_name, target)

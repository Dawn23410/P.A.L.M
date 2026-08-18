"""管理芯片（BrickHandle）与总线控制器（BusController）。

把「每块砖一个管理芯片 + 可自定义请求地址」落成代码层的运行时治理：

- BrickHandle：挂在每块砖外面的管理芯片，持有 endpoint（请求地址）/ Transport
  （信道）/ 生命周期（load→active→dispose）/ 健康探针 / 遥测。内核只跟 handle
  对话，砖逻辑经 Transport 隔离——地址即隔离边界。
- BusController：per 总线一个（CPU/SATA/PCIE/RAM/BOARD/CHIP），定默认 endpoint
  策略并聚合该总线所有砖的 handle；每砖 manifest.endpoint 可覆盖总线默认。

与既有架构的关系：BusController 的默认策略 = 我此前建议的「per-bus 治理」；
每砖 endpoint 覆盖 = 用户提议的「per-brick 芯片 + 自定义地址」。两者是
default + override，不再矛盾。新增层完全加性，不改动既有运行链路。
"""
from __future__ import annotations

import logging
from typing import Any

from palm_sdk.bricks.base import Brick, BusType
from . import telemetry
from .placement import recommend_endpoint
from .quota import BusCap, QuotaValidator
from .transport import (
    InProcTransport,
    RemoteTransport,
    SubprocessSpec,
    SubprocessTransport,
    Transport,
    transport_for,
)

_LOGGER = logging.getLogger(__name__)


def _bus_str(bus) -> str:
    """总线类型归一为字符串：兼容 BusType 枚举（单体）与独立态的纯字符串。"""
    return bus.value if isinstance(bus, BusType) else bus

# 总线默认 endpoint 策略：PCIE 承载重计算/媒体（tts/gui/automation）→ 默认隔离子进程；
# 其余总线默认进程内零开销。每砖 manifest.endpoint 显式赋值即覆盖。
_BUS_DEFAULT_ENDPOINT = {
    BusType.PCIE: "ipc://",
    BusType.CPU: "inproc://",
    BusType.SATA: "inproc://",
    BusType.RAM: "inproc://",
    BusType.BOARD: "inproc://",
    BusType.CHIP: "inproc://",
}


def _build_transport(brick: Brick, endpoint: str) -> Transport:
    """按 endpoint 与砖是否提供 subprocess_spec 选择信道。

    仅当砖显式暴露 subprocess_spec（SubprocessSpec）能力时才建子进程信道，
    否则 ipc/tcp 未配齐时安全退化为进程内，绝不因缺配置而启动失败。
    """
    spec_cap = brick.capabilities.get("subprocess_spec")
    if endpoint.startswith("tcp://") or endpoint.startswith("ws://"):
        return RemoteTransport(endpoint)
    if endpoint.startswith("ipc://"):
        if isinstance(spec_cap, SubprocessSpec):
            return SubprocessTransport(endpoint, spec_cap)
        _LOGGER.info("砖 %s endpoint=%s 但未提供 subprocess_spec，退化为进程内",
                     brick.manifest.name, endpoint)
        return InProcTransport(endpoint)
    return InProcTransport(endpoint)


class BrickHandle:
    """每块砖外的管理芯片：endpoint + 信道 + 生命周期 + 健康 + 遥测。"""

    def __init__(self, brick: Brick, bus: "BusController | None" = None) -> None:
        self.brick = brick
        self.manifest = brick.manifest
        self.bus = bus
        # 决策优先级：owner 显式 manifest.endpoint → 放置调度器推荐 →
        # 总线简化默认 → 进程内兜底。manifest 覆盖一切（用户自定义请求地址）。
        self.endpoint = (
            self.manifest.endpoint
            or recommend_endpoint(brick)
            or (bus.default_endpoint_for(self.manifest.bus_type) if bus else None)
            or "inproc://"
        )
        self.transport = _build_transport(brick, self.endpoint)
        self.state = "registered"   # registered | active | disposed

    @property
    def name(self) -> str:
        return self.manifest.name

    async def load(self) -> None:
        """激活芯片：拉起信道（子进程/连接）。进程内为 no-op。"""
        if self.state == "active":
            return
        await self.transport.start()
        self.state = "active"

    async def health(self) -> bool:
        """健康探针：记录遥测后返回连通性。"""
        try:
            ok = bool(await self.transport.health())
        except Exception as exc:  # noqa: BLE001
            ok = False
            err = str(exc)
        else:
            err = None
        telemetry.get_sink().record(self.name, ok=ok, error=err)
        return ok

    async def dispose(self) -> None:
        """释放资源：关信道、清临时句柄（顺带收敛 world_model 截图堆积等问题）。"""
        if self.state == "disposed":
            return
        try:
            await self.transport.dispose()
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("砖 %s dispose 异常: %s", self.name, exc)
        self.state = "disposed"

    def snapshot(self) -> dict[str, Any]:
        """BIOS / 前端主板图数据源：芯片运行态摘要。"""
        # 真实用量（仅隔离子进程可读）；进程内砖共享主进程 → None。
        usage = None
        try:
            raw = self.transport.usage()
        except Exception:  # noqa: BLE001
            raw = None
        if raw is not None:
            usage = {
                "cpu_pct": getattr(raw, "cpu_pct", None),
                "rss_mb": getattr(raw, "rss_mb", None),
                "measured": getattr(raw, "measured", False),
            }
        return {
            "name": self.name,
            "bus": _bus_str(self.manifest.bus_type),
            "endpoint": self.endpoint,
            "transport": type(self.transport).__name__,
            "isolation": self.manifest.isolation,
            "version": self.manifest.version,
            "state": self.state,
            "enabled": self.manifest.is_enabled,
            "telemetry": telemetry.get_sink().get(self.name),
            # 资源配额画像（声明）与真实用量（best-effort）
            "quota": {
                "cpu_cores": self.manifest.resources.cpu_cores,
                "mem_mb": self.manifest.resources.mem_mb,
                "io_weight": self.manifest.resources.io_weight,
            },
            "usage": usage,
            # 存储策略（主+分 IC）
            "storage": _storage_policy(self.name),
        }


def _storage_policy(name: str) -> dict:
    try:
        from .storage import storage_policy_of
        return storage_policy_of(name)
    except Exception:  # noqa: BLE001
        return {"namespace": name, "isolated": True, "quota_mb": None, "path": None}


class BusController:
    """per 总线控制器：默认 endpoint 策略 + 该总线所有砖 handle 的聚合治理。"""

    def __init__(self, bus_type: BusType) -> None:
        # 独立态 BrickManifest.bus_type 为纯字符串，统一归一为 BusType 枚举，
        # 保证 _BUS_DEFAULT_ENDPOINT 按枚举键命中与 .value 取值一致。
        self.bus_type = bus_type if isinstance(bus_type, BusType) else BusType(bus_type)
        self._handles: dict[str, BrickHandle] = {}
        self._cap: BusCap | None = None
        self._validator = QuotaValidator(None)

    def default_endpoint_for(self, bus: BusType) -> str:
        key = bus if isinstance(bus, BusType) else BusType(bus)
        return _BUS_DEFAULT_ENDPOINT.get(key, "inproc://")

    def set_bus_cap(self, cap: BusCap) -> None:
        """设定该总线资源总帽并启用声明额度校验。"""
        self._cap = cap
        self._validator = QuotaValidator(cap)

    def quota_violations(self) -> list[str]:
        """聚合本总线所有砖的声明配额，对照总线总帽返回超限告警。"""
        declared = [h.manifest.resources for h in self._handles.values()]
        return self._validator.validate(declared)

    def register(self, handle: BrickHandle) -> None:
        handle.bus = self
        self._handles[handle.name] = handle

    def handlers(self) -> list[BrickHandle]:
        return list(self._handles.values())

    async def dispose_all(self) -> None:
        """总线停机：逐个释放下属砖的芯片资源。"""
        for handle in self._handles.values():
            await handle.dispose()

    def snapshot(self) -> dict[str, Any]:
        return {
            "bus": _bus_str(self.bus_type),
            "default_endpoint": self.default_endpoint_for(self.bus_type),
            "quota_cap": {
                "cpu_cores": self._cap.cpu_cores if self._cap else 0,
                "mem_mb": self._cap.mem_mb if self._cap else 0,
                "io_total": self._cap.io_total if self._cap else 0,
            } if self._cap else None,
            "quota_violations": self.quota_violations(),
            "bricks": [h.snapshot() for h in self._handles.values()],
        }


# 全局总线控制器注册表：BusType -> BusController（懒建）。
_CONTROLLERS: dict[BusType, BusController] = {}


def get_bus_controller(bus_type: BusType) -> BusController:
    ctrl = _CONTROLLERS.get(bus_type)
    if ctrl is None:
        ctrl = BusController(bus_type)
        _CONTROLLERS[bus_type] = ctrl
    return ctrl


def wrap_brick(brick: Brick) -> BrickHandle:
    """把已注册的砖包成管理芯片，并按总线挂到对应 BusController。"""
    bus = get_bus_controller(brick.manifest.bus_type)
    handle = BrickHandle(brick, bus)
    bus.register(handle)
    return handle


def all_controllers() -> list[BusController]:
    return list(_CONTROLLERS.values())


def get_handle(name: str) -> "BrickHandle | None":
    """按砖名查其管理芯片（跨总线）。热插拔/仲裁/tts 托管均经此取芯片。"""
    for ctrl in _CONTROLLERS.values():
        h = ctrl._handles.get(name)  # noqa: SLF001  同包内部聚合访问
        if h is not None:
            return h
    return None


def apply_default_bus_caps() -> None:
    """按系统资源给各总线设宽松总帽（避免误报），并启用声明额度校验。

    总帽取系统真实资源的合理比例：CPU = 逻辑核数；内存 = 系统总量一半；
    IO 总量 = 各总线砖数 * 50（权重和上限）。声明超额才告警，正常不触发。
    """
    import os
    cpu = float(os.cpu_count() or 4)
    mem_total = 0
    try:
        import psutil  # type: ignore
        mem_total = int(psutil.virtual_memory().total / (1024 * 1024))
    except Exception:  # noqa: BLE001
        mem_total = 4096
    for bus_type, ctrl in _CONTROLLERS.items():
        n = len(ctrl._handles)
        ctrl.set_bus_cap(BusCap(
            cpu_cores=cpu,                       # 总线共享全机 CPU
            mem_mb=max(mem_total // 2, 1024),    # 内存半量上限
            io_total=max(n * 50, 100),           # IO 权重和上限
        ))


def masterboard_snapshot() -> dict[str, Any]:
    """完整主板运行态快照（BIOS / 前端主板图）。"""
    return {_bus_str(ctrl.bus_type): ctrl.snapshot() for ctrl in _CONTROLLERS.values()}
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional


class BusType(str, Enum):
    CPU = "cpu"
    SATA = "sata"
    PCIE = "pcie"
    RAM = "ram"
    BOARD = "board"
    CHIP = "chip"


@dataclass
class ResourceQuota:
    # 字段名对齐主板治理层（quota.py / handle.py 取自单体）：cpu_cores/mem_mb/io_weight。
    # 默认 0（非 None），使总线配额求和校验无需判空即成立。
    cpu_cores: Optional[float] = 0.0
    mem_mb: Optional[int] = 0
    io_weight: Optional[int] = 0


@dataclass
class StoragePolicy:
    scope: str = "local"
    quota_mb: Optional[int] = None


@dataclass
class BrickManifest:
    name: str
    title: str = ""
    description: str = ""
    is_core: bool = False
    can_accept_files: bool = False
    is_streaming: bool = False
    is_enabled: bool = True
    bus_type: str = "board"
    endpoint: str = ""
    isolation: str = "inproc"
    version: str = "0.1.0"
    resources: ResourceQuota = field(default_factory=ResourceQuota)
    storage: StoragePolicy = field(default_factory=StoragePolicy)


class CapabilitySlot:
    """能力槽：砖对外暴露的可调用能力。"""

    def __init__(self, name: str, handler: Callable, description: str = ""):
        self.name = name
        self.handler = handler
        self.description = description

    def __call__(self, *args, **kwargs):
        return self.handler(*args, **kwargs)


@dataclass
class Brick:
    manifest: BrickManifest
    router: Any = None
    capabilities: dict = field(default_factory=dict)
    permissions: list = field(default_factory=list)
    perf: Any = None  # 自动挂载的性能开销芯片（见 _attach_perf），导入失败则为 None
    control: Any = None  # 自动挂载的通用控制芯片（见 _attach_control），导入失败则为 None

    def capability(self, name: str):
        return self.capabilities.get(name)


def _attach_perf(brick: "Brick") -> None:
    """给砖自动挂一枚性能开销芯片（绑当前进程）。

    psutil 缺失或任意异常均吞掉，仅置 None，绝不让砖注册失败。
    """
    try:
        from palm_sdk.bricks.perf_chip import PerfChip
        brick.perf = PerfChip(name=brick.manifest.name)
    except Exception:  # noqa: BLE001  软依赖，缺失即跳过
        brick.perf = None


def _attach_control(brick: "Brick") -> None:
    """给砖自动挂一枚通用控制芯片（与 perf 同构，业务零改）。

    host 设为砖自身：构造时 adopt 扫描砖上的 @control_code_route 装饰方法并注册；
    没有装饰则仅暴露 8 个标准码。砖可经 host 钩子（on_loaded / on_release_perf /
    on_shutdown）接管真实生命周期（如重型砖关停子进程）。导入失败仅置 None。
    """
    try:
        from palm_sdk.bricks.control_chip import ControlChip
        brick.control = ControlChip(
            host=brick, name=brick.manifest.name, bus=brick.manifest.bus_type)
    except Exception:  # noqa: BLE001  控制芯片为纯标准库，失败即置 None
        brick.control = None


class _Registry:
    def __init__(self):
        self.bricks: dict[str, Brick] = {}

    def register(self, brick: Brick) -> None:
        self.bricks[brick.manifest.name] = brick
        _attach_perf(brick)
        _attach_control(brick)

    def get(self, name: str):
        return self.bricks.get(name)

    def all(self) -> list:
        """返回全部已注册砖（独立态对齐单体 registry.all() 接口）。"""
        return list(self.bricks.values())

    @property
    def _bricks(self) -> dict:
        # 兼容单体 registry 的私有属性名；独立态下与公共 bricks 同义。
        return self.bricks

    def group_by_bus(self) -> dict:
        out: dict[str, list] = {}
        for b in self.bricks.values():
            out.setdefault(b.manifest.bus_type, []).append(b.manifest.name)
        return out


registry = _Registry()

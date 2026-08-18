"""库内服务容器：bootstrap 装配的唯一出口（收敛自旧 palm_sdk.bricks.base 的 registry）。

用户决策（2026-08-18）：放弃传统主板架构——Brick/BrickManifest/BusType 等
主板隐喻类不再存在；模块按名注册/取用，ServiceHandle.capability 对齐旧
`registry.get(name).capabilities[key]` 语义，业务代码无需改动取用方式。
"""

from typing import Any, Callable


class ServiceHandle:
    """服务句柄：对齐旧 Brick.capability 语义，业务零改。"""

    def __init__(self, name: str, impl: Any, capabilities: dict[str, Callable] | None = None):
        self._name = name
        self._impl = impl
        self._capabilities = capabilities or {}

    @property
    def name(self) -> str:
        return self._name

    @property
    def impl(self) -> Any:
        return self._impl

    @property
    def capabilities(self) -> dict:
        """显式注册的能力 + 实现对象的方法属性（方法名即能力键）。"""
        merged = dict(self._capabilities)
        for attr in dir(self._impl):
            if attr.startswith("_"):
                continue
            value = getattr(self._impl, attr)
            if callable(value):
                merged.setdefault(attr, value)
        return merged

    def capability(self, name: str):
        """取能力：先查显式注册，再回退实现对象的方法属性；缺失返回 None。"""
        if name in self._capabilities:
            return self._capabilities[name]
        return getattr(self._impl, name, None)

    def __repr__(self) -> str:
        return f"<ServiceHandle {self._name}>"


class Container:
    """按名注册/取用服务的轻量容器（装配层持有，业务只读）。"""

    def __init__(self):
        self._services: dict[str, ServiceHandle] = {}

    def register(self, name: str, impl: Any,
                 capabilities: dict[str, Callable] | None = None) -> ServiceHandle:
        handle = ServiceHandle(name, impl, capabilities)
        self._services[name] = handle
        return handle

    def get(self, name: str) -> ServiceHandle | None:
        return self._services.get(name)

    def all(self) -> list[ServiceHandle]:
        return list(self._services.values())

    def names(self) -> list[str]:
        return sorted(self._services)


# 全局单例：库内模块经 container.get(服务名) 惰性取用，与旧 registry 同构。
container = Container()

# 兼容别名：迁移收敛后残留的 `from palm._core.container import registry` 仍可导入。
registry = container


class CapabilitySlot:
    """能力槽：服务对外暴露的可调用能力（对齐旧语义，供演化服务引用）。"""

    def __init__(self, name: str, handler: Callable, description: str = ""):
        self.name = name
        self.handler = handler
        self.description = description

    def __call__(self, *args, **kwargs):
        return self.handler(*args, **kwargs)

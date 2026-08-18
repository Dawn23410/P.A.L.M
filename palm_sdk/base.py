# 兼容别名：palm_sdk.base -> palm_sdk.bricks.base
from palm_sdk.bricks.base import (  # noqa: F401
    Brick, BrickManifest, BusType, CapabilitySlot, registry,
)

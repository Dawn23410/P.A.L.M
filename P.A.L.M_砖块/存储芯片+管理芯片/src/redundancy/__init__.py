"""存储砖·冗余子包：删除前保险库归档 + 删除路由回收站。

原 sandbox 砖的 vault / safe_delete 整体迁入此处（M0 冗余层迁移，行为不变仅移动）。
存储砖作为主板自带组件直接持有冗余能力，sandbox 砖改为委托本子包，杜绝跨砖重复逻辑。
"""
from __future__ import annotations

from . import vault as vault
from .recycle import send_to_recycle_bin

__all__ = ["vault", "send_to_recycle_bin"]

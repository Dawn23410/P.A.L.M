"""存储 IC（主+分模型）：每块砖的私有命名空间，互不污染全局池。

主板隐喻的「存储管理 IC」：此前存储砖统一吃全局 STORAGE_POOL_DIR，所有砖文件
混在一起。主+分 = 主 IC（全局池/保险库）+ 每砖专属分 IC（主/bricks/<namespace>）。
砖经 get_brick_storage(name) 取自己的分 IC 目录，写入即落该命名空间——某砖清理/
卸载时只删自己目录，不影响他人；容量软上限由 manifest.storage.quota_mb 声明。

纯加性：未调用则不创建目录；isolated=False 的砖仍复用主池（向后兼容）。
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from palm_sdk.bricks.base import registry
from palm_sdk.core.config import settings

_LOGGER = logging.getLogger(__name__)

# 主 IC 下的分 IC 根目录名
_BRICKS_SUBDIR = "bricks"


def main_root() -> str:
    """主 IC 根（全局存储池 / 保险库所在）。"""
    return settings.STORAGE_POOL_DIR


def _namespace_of(brick_name: str) -> str:
    """解析砖的存储命名空间：manifest.storage.namespace 优先，否则砖名。"""
    brick = registry.get(brick_name)
    if brick is not None:
        ns = brick.manifest.storage.namespace
        if ns:
            return ns
    return brick_name


def brick_dir(brick_name: str, create: bool = True) -> str:
    """返回砖的分 IC 目录（主/bricks/<namespace>）；isolated=False 退回主池。"""
    brick = registry.get(brick_name)
    isolated = brick.manifest.storage.isolated if brick is not None else True
    if not isolated:
        root = main_root()
        if create:
            os.makedirs(root, exist_ok=True)
        return root
    ns = _namespace_of(brick_name)
    path = os.path.join(main_root(), _BRICKS_SUBDIR, ns)
    if create:
        os.makedirs(path, exist_ok=True)
    return path


def get_brick_storage(brick_name: str) -> str:
    """便捷入口：取某砖的私有存储目录（惰性创建）。砖块落盘优先走此而非全局池。"""
    return brick_dir(brick_name, create=True)


def storage_policy_of(brick_name: str) -> dict:
    """砖的存储策略摘要（供快照/前端展示）。"""
    brick = registry.get(brick_name)
    if brick is None:
        return {"namespace": brick_name, "isolated": True, "quota_mb": None,
                "path": brick_dir(brick_name, create=False)}
    st = brick.manifest.storage
    return {
        "namespace": st.namespace or brick_name,
        "isolated": st.isolated,
        "quota_mb": st.quota_mb,
        "path": brick_dir(brick_name, create=False),
    }


def usage_of(brick_name: str) -> Optional[int]:
    """分 IC 当前占用字节数（best-effort）。isolated=False 返回 None（共享主池不计）。"""
    brick = registry.get(brick_name)
    if brick is not None and not brick.manifest.storage.isolated:
        return None
    path = brick_dir(brick_name, create=False)
    if not os.path.isdir(path):
        return 0
    total = 0
    try:
        for root, _dirs, files in os.walk(path):
            for f in files:
                fp = os.path.join(root, f)
                try:
                    total += os.path.getsize(fp)
                except OSError:
                    pass
    except Exception:  # noqa: BLE001
        return None
    return total
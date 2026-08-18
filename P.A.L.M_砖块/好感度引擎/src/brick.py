"""好感度砖：注册 + 对外暴露 affinity_api 门面。

affinity_api 即本砖包对象：__init__ 已把全部符号（AffinityState / resolve_ruleset /
settle_from_model / stance_text / AffinityStore / RuntimeContext 等）挂为包属性，
consumers 经 app.bricks._shared.interop.get_affinity_api() 取用。

on_entity_deleted：好感度状态按实体 id 索引（agent_affinity/），实体删除时自清，
避免孤儿数据（原属 roleplay 砖的清理职责，随本域拆出迁移至此）。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from palm_sdk.bricks.base import Brick, BrickManifest, registry
from palm_sdk.bricks.housekeeping import ENTITY_CHARACTER, ENTITY_CONVERSATION
from palm_sdk.core.config import settings

# affinity_api 即本砖包对象（同 roleplay 砖模式）。
affinity_api = sys.modules[__package__]


def _safe_entity_id(value: str) -> str:
    # 与 AffinityStore._safe_id 同规则净化，防路径穿越。
    return re.sub(r"[^A-Za-z0-9_\-]", "_", value or "default")


def _handle_entity_deleted(entity_type: str, entity_id: str) -> str:
    """清理本砖持有的实体好感度状态（agent_affinity/ 按实体 id 索引）。"""
    base = Path(settings.STORAGE_POOL_DIR)
    safe = _safe_entity_id(entity_id)
    aff = base / "agent_affinity" / f"{safe}.json"
    removed = 0
    if aff.exists():
        try:
            aff.unlink()
            removed += 1
        except OSError:
            pass
    return f"affinity {entity_type}:{entity_id} 清理 {removed} 项"


brick = Brick(
    manifest=BrickManifest(
        name="affinity",
        title="好感度引擎",
        description="双线好感度（base·dynamics·bond）/ 动态叠加 / 存储与结算，独立于角色扮演砖，供记忆与对话结算消费。",
        bus_type="ram",
    ),
    capabilities={
        "affinity_api": affinity_api,
        "on_entity_deleted": _handle_entity_deleted,
    },
)
registry.register(brick)
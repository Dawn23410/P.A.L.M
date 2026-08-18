"""角色扮演砖：注册 + 对外暴露 roleplay_api 门面。

原属 agent 砖的「角色扮演」域（人设卡片 / 渲染 / 语气守卫），
现抽为独立砖。所有符号经 capabilities["roleplay_api"] 暴露，供 agent / memory
经 app.bricks._shared.interop.get_roleplay_api() 取用，保持砖间零互导。
好感度域已于 2026-08-06 拆出为独立 affinity 砖（本砖不再持有 agent_affinity/）。

启动时把内置角色写入磁盘（已存在则跳过），并据环境变量/默认路径注入梦瑶 Skill。
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from palm_sdk.bricks.base import Brick, BrickManifest, registry
from palm_sdk.bricks.housekeeping import ENTITY_CHARACTER
from palm_sdk.core.config import settings
from palm_sdk.bricks._shared.paths import brick_local
from . import character

# roleplay_api 即本砖包对象：__init__ 已把全部符号（strip_roleplay_tone /
# CharacterCard / 角色卡管理）挂为包属性，consumers 直接经属性取用。
roleplay_api = sys.modules[__package__]


def _safe_entity_id(value: str) -> str:
    # 与 AffinityStore._safe_id 同规则净化，防路径穿越。
    return re.sub(r"[^A-Za-z0-9_\-]", "_", value or "default")


def _handle_entity_deleted(entity_type: str, entity_id: str) -> str:
    # 作为 capabilities["on_entity_deleted"] 被协调器扇出；只清理 roleplay 自身持有的实体。
    # roleplay 是角色卡（characters/）的写入方，须自清避免孤儿。
    # （好感度状态 agent_affinity/ 的清理随该域拆出迁移至 affinity 砖。）
    base = Path(settings.STORAGE_POOL_DIR)
    safe = _safe_entity_id(entity_id)
    removed = 0
    if entity_type == ENTITY_CHARACTER:
        card = base / "characters" / f"{safe}.json"
        if card.exists():
            try:
                card.unlink()
                removed += 1
            except OSError:
                pass
    return f"roleplay {entity_type}:{entity_id} 清理 {removed} 项"


brick = Brick(
    manifest=BrickManifest(
        name="roleplay",
        title="角色扮演引擎",
        description="人设卡片 / 渲染 / 语气污染守卫（好感度已拆出为独立 affinity 砖）。",
        bus_type="board",
    ),
    capabilities={
        "roleplay_api": roleplay_api,
        "on_entity_deleted": _handle_entity_deleted,
    },
)

# 启动时把内置角色写入磁盘（已存在则跳过）
# 梦瑶：默认随砖内聚于 data/，可用环境变量 PALM_MENGYAO_SKILL_PATH 覆盖（砖可随意移动）。
_mengyao_env = os.environ.get("PALM_MENGYAO_SKILL_PATH")
_mengyao_path = Path(_mengyao_env) if _mengyao_env else Path(brick_local(__file__, "data", "梦瑶 — 猫娘性格 Skill.md"))
if _mengyao_path.exists():
    character.set_mengyao_skill_path(str(_mengyao_path))
character.ensure_builtins()

registry.register(brick)
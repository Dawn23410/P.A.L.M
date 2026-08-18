"""好感度持久化：独立于记忆层，存储双线好感度状态（base / dynamics / bond）。

- 角色可选：affinity_enabled=False 时不写盘，get 返回中性 0（引擎侧短路）。
- base 饱和于 100、dynamics 范围 -50~50、bond 无上限，全部由引擎钳制，这里只负责存。
- 与记忆 JSON 同级 agent_affinity/ 目录，按核心记忆文件名索引。
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

_LOGGER = logging.getLogger(__name__)

_BASE_CLAMP = 100.0
_DYN_CLAMP = 50.0


def _safe_id(value: str) -> str:
    """净化 id 防路径穿越（与 brick._agent_memory_path 同规则）。"""
    return re.sub(r"[^A-Za-z0-9_\-]", "_", value or "default")


class AffinityStore:
    """按核心记忆文件路径索引的双线好感度存储。"""

    def __init__(self, core_memory_path: str | Path | None = None):
        self._core_path = Path(core_memory_path) if core_memory_path else None
        if self._core_path:
            self._path = self._core_path.parent / "agent_affinity" / (self._core_path.stem + ".json")
        else:
            self._path = None
        self._base = 0.0
        self._dynamics = 0.0
        self._bond = 0.0
        self._last_active_date = ""
        self._first_active_date = ""
        self._enabled = True
        self._loaded = False

    async def initialize(self, affinity_enabled: bool = True) -> None:
        """加载好感度（含从遗留 CoreMemory JSON 迁移 current_affinity）。"""
        self._enabled = affinity_enabled
        if self._loaded:
            return
        if self._path and self._path.exists():
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                self._base = float(raw.get("base", 0.0))
                self._dynamics = float(raw.get("dynamics", 0.0))
                self._bond = float(raw.get("bond", 0.0))
                self._last_active_date = str(raw.get("last_active_date", ""))
                self._first_active_date = str(raw.get("first_active_date", ""))
            except Exception as exc:
                _LOGGER.warning("好感度加载失败，回退 0: %s", exc)
        elif self._core_path and self._core_path.exists():
            # 迁移遗留：旧 CoreMemory 的 affinity 字段 → 视为 base
            try:
                raw = json.loads(self._core_path.read_text(encoding="utf-8"))
                legacy = float(raw.get("affinity", 0.0)) if "affinity" in raw else 0.0
                if legacy:
                    self._base = max(-_BASE_CLAMP, min(_BASE_CLAMP, legacy))
                    _LOGGER.info("已从遗留核心记忆迁移好感度(base)=%.2f", self._base)
            except Exception as exc:
                _LOGGER.warning("遗留好感度迁移失败: %s", exc)
        self._loaded = True

    # ── 读取 ──

    def get(self) -> float:
        """兼容旧调用：返回 base（饱和后）。角色未启用时中性 0。"""
        if not self._enabled:
            return 0.0
        return self._base

    def get_state(self) -> dict:
        """返回完整双线状态（供新流程使用）。"""
        return {
            "base": self._base,
            "dynamics": self._dynamics,
            "bond": self._bond,
            "last_active_date": self._last_active_date,
            "first_active_date": self._first_active_date,
            "affinity_enabled": self._enabled,
        }

    def is_enabled(self) -> bool:
        return self._enabled

    # ── 写入（由结算结果回写） ──

    def apply_settlement(self, base: float, dynamics: float, bond: float, last_active_date: str) -> None:
        """回写引擎结算后的双线数值（已钳制，这里只存）。"""
        self._base = max(-_BASE_CLAMP, min(_BASE_CLAMP, round(base, 4)))
        self._dynamics = max(-_DYN_CLAMP, min(_DYN_CLAMP, round(dynamics, 4)))
        self._bond = round(bond, 4)
        self._last_active_date = last_active_date
        # 首次活跃日期：仅记录一次，用于时间型动态（年龄/年级增长节奏）。不回写角色卡。
        if not self._first_active_date:
            self._first_active_date = last_active_date

    async def shutdown(self) -> None:
        if not self._path or not self._loaded:
            return
        if not self._enabled:
            return  # 角色未启用：不落盘
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(
                {
                    "base": self._base,
                    "dynamics": self._dynamics,
                    "bond": self._bond,
                    "last_active_date": self._last_active_date,
                    "first_active_date": self._first_active_date,
                    "affinity_enabled": self._enabled,
                },
                ensure_ascii=False, indent=2,
            ),
            encoding="utf-8",
        )

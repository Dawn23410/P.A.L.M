"""习惯推断引擎：从用户接受/拒绝历史中挖掘「最可能任务」，供闲置编排器提案。

设计要点（源自自主进化架构决策）：
- 接受账本随角色落盘（agent_habits/{角色}.json），随角色经 on_entity_deleted 级联清理，不造孤儿。
- 推断综合考虑：历史接受频次 × 近因权重 × 当前时段/星期匹配，输出 top-1 任务类别。
- 任务类别为粗粒度标签（起草/整理/提醒/摘要），由闲置编排器转成自然语言提案。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from palm_sdk.core.config import settings

# 任务类别 → 中文提案模板（闲置编排器直接使用）。
TASK_LABELS = {
    "draft_report": "起草一份当前最紧要的报告/周报",
    "organize_files": "帮你整理一下散落的文件夹",
    "set_reminder": "为接下来要做的事设个提醒",
    "summarize": "把近期内容提炼成一份小结",
}

_LEDGER_DIR = "agent_habits"


def _ledger_path(character_id: str) -> Path:
    # 净化 id 防路径穿越；账本与记忆同根目录，随角色隔离。
    safe = "".join(c if c.isalnum() or c in "_-" else "_" for c in (character_id or "default"))[:32]
    return Path(settings.STORAGE_POOL_DIR) / _LEDGER_DIR / f"{safe}.json"


def _load_ledger(character_id: str) -> list[dict]:
    p = _ledger_path(character_id)
    if not p.is_file():
        return []
    try:
        with open(p, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except (ValueError, OSError):
        return []


def _save_ledger(character_id: str, entries: list[dict]) -> None:
    p = _ledger_path(character_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(entries, fh, ensure_ascii=False)
    os.replace(tmp, p)


def record_feedback(task_type: str, accepted: bool, character_id: str = "",
                    ts: float | None = None) -> None:
    # 记录一条任务反馈（接受/拒绝），供后续推断；同一函数同时承担「学习」职责。
    ts = ts or time.time()
    local = time.localtime(ts)
    entries = _load_ledger(character_id)
    entries.append({
        "task_type": task_type,
        "accepted": bool(accepted),
        "ts": ts,
        "hour": local.tm_hour,
        "weekday": local.tm_wday,
    })
    _save_ledger(character_id, entries[-500:])


def infer_top_task(character_id: str = "", now: float | None = None) -> str | None:
    # 输出当前最可能执行的任务类别标签；无足够数据返回 None。
    now = now or time.time()
    local = time.localtime(now)
    entries = _load_ledger(character_id)
    accepted = [e for e in entries if e.get("accepted")]
    if not accepted:
        return None

    scores: dict[str, float] = {}
    for e in accepted:
        t = e.get("task_type", "")
        age_days = (now - float(e.get("ts", now))) / 86400.0
        recency = 1.0 / (1.0 + max(age_days, 0.0))  # 近因权重
        hour_match = 1.0 if int(e.get("hour", -1)) == local.tm_hour else 0.3
        weekday_match = 1.0 if int(e.get("weekday", -1)) == local.tm_wday else 0.6
        scores[t] = scores.get(t, 0.0) + recency * hour_match * weekday_match

    if not scores:
        return None
    best = max(scores.items(), key=lambda kv: kv[1])[0]
    return best


def describe_task(task_type: str | None) -> str | None:
    # 把任务类别标签转成面向用户的中文提案文案。
    if not task_type:
        return None
    return TASK_LABELS.get(task_type)
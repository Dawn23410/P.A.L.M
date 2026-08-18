"""Token 用量台账 — SQLite 持久化版。

相比旧版 JSON 全量读写的改进：
- INSERT 单条 O(1)，不再每次全量 load+save
- 无限明细（无 5000 上限）
- 查询用 SQL 替代 Python for 循环过滤
- ACID 事务防写坏
- 聚合用 SQL SUM/GROUP BY，而非手动累加
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import date, datetime
from pathlib import Path

from palm_sdk.core.config import settings
from palm_sdk.bricks._shared.paths import fallback_dir, resolve_storage

_LOGGER = logging.getLogger(__name__)

_DB_PATH = Path(fallback_dir(settings.STORAGE_POOL_DIR, __file__)) / ".token_usage.db"
_lock = threading.Lock()

# 保留天数/月数（与旧 JSON 版一致）
_KEEP_DAYS = 62
_KEEP_MONTHS = 13


def _get_conn() -> sqlite3.Connection:
    """获取线程安全的 SQLite 连接。"""
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # 读写不阻塞
    conn.execute("PRAGMA synchronous=NORMAL")  # 性能与安全平衡
    return conn


def _init_db() -> None:
    """建表（幂等）。"""
    with _get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS token_usage (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id     TEXT NOT NULL DEFAULT '',
                model       TEXT NOT NULL DEFAULT '',
                provider    TEXT NOT NULL DEFAULT '',
                prompt_tokens  INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens    INTEGER NOT NULL DEFAULT 0,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_usage_created
                ON token_usage(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_usage_model
                ON token_usage(model);

            CREATE TABLE IF NOT EXISTS token_aggregation (
                period_type TEXT NOT NULL,   -- 'daily' | 'monthly'
                period_key  TEXT NOT NULL,   -- '2026-07-29' | '2026-07'
                total_tokens INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (period_type, period_key)
            );
        """)


# ── 公开接口 ─────────────────────────────────────────────────

def current_usage() -> tuple[int, int]:
    """返回 (今日已用 token, 本月已用 token)。"""
    _init_db()
    today = date.today().isoformat()
    month = date.today().strftime("%Y-%m")
    with _lock, _get_conn() as conn:
        daily = conn.execute(
            "SELECT total_tokens FROM token_aggregation WHERE period_type=? AND period_key=?",
            ("daily", today),
        ).fetchone()
        monthly = conn.execute(
            "SELECT total_tokens FROM token_aggregation WHERE period_type=? AND period_key=?",
            ("monthly", month),
        ).fetchone()
    return (daily["total_tokens"] if daily else 0,
            monthly["total_tokens"] if monthly else 0)


def record_request(
    chat_id: str,
    model: str,
    provider: str,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int,
) -> None:
    """记录一次请求的完整用量明细，同时更新日/月聚合表。"""
    if total_tokens <= 0:
        return

    _init_db()
    with _lock, _get_conn() as conn:
        # 1) 插入明细
        conn.execute(
            """INSERT INTO token_usage
               (chat_id, model, provider, prompt_tokens, completion_tokens, total_tokens)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (chat_id, model or "", provider or "",
             int(prompt_tokens), int(completion_tokens), int(total_tokens)),
        )

        # 2) 更新日/月聚合（UPSERT）
        today = date.today().isoformat()
        month = date.today().strftime("%Y-%m")
        for pt, pk in [("daily", today), ("monthly", month)]:
            conn.execute(
                """INSERT INTO token_aggregation (period_type, period_key, total_tokens)
                   VALUES (?, ?, ?)
                   ON CONFLICT(period_type, period_key)
                   DO UPDATE SET total_tokens = total_tokens + ?""",
                (pt, pk, total_tokens, total_tokens),
            )

        # 3) 裁剪过期聚合（后台线程，不阻塞）
        _prune_if_needed(conn)


def query_records(
    start_date: str | None = None,
    end_date: str | None = None,
    model: str | None = None,
    provider: str | None = None,
    limit: int = 200,
) -> list[dict]:
    """查询逐请求用量明细，按时间倒序。"""
    _init_db()
    where_clauses: list[str] = []
    params: list = []

    if start_date:
        where_clauses.append("created_at >= ?")
        params.append(start_date)
    if end_date:
        where_clauses.append("created_at <= ?")
        params.append(end_date + " 23:59:59")
    if model:
        where_clauses.append("model LIKE ?")
        params.append(f"%{model}%")
    if provider:
        where_clauses.append("provider = ?")
        params.append(provider)

    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

    with _lock, _get_conn() as conn:
        rows = conn.execute(
            f"""SELECT chat_id, model, provider,
                       prompt_tokens, completion_tokens, total_tokens,
                       created_at as time
                FROM token_usage
                WHERE {where_sql}
                ORDER BY created_at DESC
                LIMIT ?""",
            (*params, limit),
        ).fetchall()

    return [dict(r) for r in rows]


def record_usage(total_tokens: int) -> None:
    """兼容接口：仅记录总量。"""
    record_request("", "", "", 0, 0, total_tokens)


# ── 内部 ─────────────────────────────────────────────────────

def _prune_if_needed(conn: sqlite3.Connection) -> None:
    """超阈值时清理过期聚合数据（每 10 次写触发一次）。"""
    # 简单概率采样：被调用约 1/10 时执行清理
    import random
    if random.random() > 0.1:
        return

    try:
        # 清理明细：保留近 62 天
        cutoff = date.today().isoformat()
        conn.execute(
            "DELETE FROM token_usage WHERE created_at < date(?, '-62 days')",
            (cutoff,),
        )

        # 清理聚合：daily 只留 62 天，monthly 只留 13 个月
        conn.execute(
            "DELETE FROM token_aggregation WHERE period_type='daily' AND period_key < date(?, '-62 days')",
            (cutoff,),
        )
        # monthly key 格式 '2026-07'，用简单的按名删除（保留最新的 13 个）
        conn.execute("""
            DELETE FROM token_aggregation WHERE period_type='monthly' AND period_key NOT IN (
                SELECT period_key FROM token_aggregation
                WHERE period_type='monthly' ORDER BY period_key DESC LIMIT ?
            )""", (_KEEP_MONTHS,))
    except Exception as exc:
        _LOGGER.warning("token 用量清理失败: %s", exc)
"""专业 Agent 私有记忆区（外骨骼版，移植自 palm/services/agent/dual/professional_memory.py）。

设计目标：轻量、私有、可合并。存经验总结、用户画像、错误记录；检索只做基础关键词
匹配，不复用主记忆的五因子检索——已验证可用，直接复用。

与归档版差异（去 palm 化）：
- 移除 palm._core.paths / palm.adapters.model 依赖；db_path 由装配层注入。
- 支持 db_path=None 的内存态（mock 零落盘合规），非空则 sqlite 明文持久化。
- 异步整理（schedule_trace_digest）的 LLM 调用改为可注入的同步 fn，缺省跳过。
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path

import sqlite3

_LOGGER = logging.getLogger(__name__)

K_EXPERIENCE = "experience"
K_USER_PROFILE = "user_profile"
K_ERROR = "error"
ALLOWED_KINDS = {K_EXPERIENCE, K_USER_PROFILE, K_ERROR}

_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)


@dataclass
class ProfessionalMemoryRecord:
    """专业 Agent 私有记忆记录。"""

    id: int
    kind: str
    content: str
    keywords: list[str]
    source_task_id: str = ""
    hit_count: int = 1
    created_at: float = 0.0
    updated_at: float = 0.0
    metadata: dict | None = None


class ProfessionalMemory:
    """专业 Agent 跨任务私有经验库。

    存储后端：db_path 非空用 sqlite3（避免额外依赖）；为空则纯内存。
    检索：关键词评分 + 最近记录兜底。
    """

    def __init__(self, db_path: str | Path | None = None, max_per_kind: int = 100) -> None:
        self._db_path = Path(db_path) if db_path else None
        self._mem: list[ProfessionalMemoryRecord] = []
        self._seq = 0
        self._max_per_kind = max(1, int(max_per_kind))
        if self._db_path is not None:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._init_db()

    # ── 连接 / 建表 ──────────────────────────────────────────
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS professional_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    content TEXT NOT NULL,
                    keywords TEXT NOT NULL DEFAULT '[]',
                    source_task_id TEXT NOT NULL DEFAULT '',
                    hit_count INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    metadata TEXT NOT NULL DEFAULT '{}'
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_prof_memory_kind_updated "
                "ON professional_memory(kind, updated_at)"
            )

    # ── 写入 ─────────────────────────────────────────────────
    def add(
        self,
        kind: str,
        content: str,
        keywords: list[str] | None = None,
        source_task_id: str = "",
        metadata: dict | None = None,
    ) -> ProfessionalMemoryRecord:
        """写入一条私有记忆；若与同类项相似则合并。"""
        kind = self._normalize_kind(kind)
        content = (content or "").strip()
        if not content:
            raise ValueError("专业Agent记忆内容不能为空")
        manual_keywords = self._normalize_manual_keywords(keywords)
        normalized_keywords = self._normalize_keywords(keywords, content)
        metadata = metadata or {}
        metadata.setdefault("_manual_keywords", manual_keywords)
        now = time.time()

        if self._db_path is None:
            return self._add_memory_in_memory(
                kind, content, normalized_keywords, source_task_id, metadata, now)

        with self._connect() as conn:
            similar = self._find_similar(conn, kind, manual_keywords)
            if similar:
                merged_content = self._merge_content(similar["content"], content)
                merged_keywords = self._merge_keywords(
                    self._decode_json(similar["keywords"], []),
                    normalized_keywords,
                )
                merged_metadata = self._merge_metadata(
                    self._decode_json(similar["metadata"], {}),
                    metadata,
                )
                conn.execute(
                    """
                    UPDATE professional_memory
                    SET content = ?, keywords = ?, source_task_id = ?,
                        hit_count = hit_count + 1, updated_at = ?, metadata = ?
                    WHERE id = ?
                    """,
                    (
                        merged_content,
                        json.dumps(merged_keywords, ensure_ascii=False),
                        source_task_id or similar["source_task_id"],
                        now,
                        json.dumps(merged_metadata, ensure_ascii=False),
                        similar["id"],
                    ),
                )
                record = self._get_by_id(conn, int(similar["id"]))
            else:
                cur = conn.execute(
                    """
                    INSERT INTO professional_memory
                    (kind, content, keywords, source_task_id, hit_count, created_at, updated_at, metadata)
                    VALUES (?, ?, ?, ?, 1, ?, ?, ?)
                    """,
                    (
                        kind,
                        content,
                        json.dumps(normalized_keywords, ensure_ascii=False),
                        source_task_id,
                        now,
                        now,
                        json.dumps(metadata, ensure_ascii=False),
                    ),
                )
                record = self._get_by_id(conn, int(cur.lastrowid))
            self._trim_kind(conn, kind)
            return record

    def _add_memory_in_memory(
        self, kind, content, keywords, source_task_id, metadata, now,
    ) -> ProfessionalMemoryRecord:
        self._seq += 1
        existing = self._find_similar_in_memory(kind, keywords)
        if existing:
            existing.content = self._merge_content(existing.content, content)
            existing.keywords = self._merge_keywords(existing.keywords, keywords)
            existing.metadata = self._merge_metadata(existing.metadata, metadata)
            existing.hit_count += 1
            existing.updated_at = now
            return existing
        record = ProfessionalMemoryRecord(
            id=self._seq, kind=kind, content=content, keywords=keywords,
            source_task_id=source_task_id, hit_count=1, created_at=now,
            updated_at=now, metadata=metadata,
        )
        self._mem.append(record)
        self._trim_kind_in_memory(kind)
        return record

    # ── 检索 ─────────────────────────────────────────────────
    def search(
        self,
        query: str,
        kinds: list[str] | None = None,
        min_items: int = 3,
        max_items: int = 5,
    ) -> list[ProfessionalMemoryRecord]:
        """基础检索：关键词评分，结果动态控制在 3 到 5 条之间。"""
        selected_kinds = [self._normalize_kind(k) for k in (kinds or list(ALLOWED_KINDS))]
        max_items = max(1, min(5, int(max_items)))
        min_items = max(0, min(int(min_items), max_items))
        query_terms = self._terms(query)

        if self._db_path is None:
            rows = [self._record_to_row(r) for r in self._mem if r.kind in selected_kinds]
        else:
            with self._connect() as conn:
                rows = conn.execute(
                    f"""
                    SELECT * FROM professional_memory
                    WHERE kind IN ({",".join("?" for _ in selected_kinds)})
                    ORDER BY updated_at DESC
                    """,
                    selected_kinds,
                ).fetchall()

        scored: list[tuple[int, ProfessionalMemoryRecord]] = []
        fallback: list[ProfessionalMemoryRecord] = []
        for row in rows:
            record = self._row_to_record(row)
            fallback.append(record)
            score = self._score_record(record, query_terms)
            if score > 0:
                scored.append((score, record))
        scored.sort(key=lambda item: (item[0], item[1].updated_at), reverse=True)
        picked = [record for _, record in scored[:max_items]]
        seen = {record.id for record in picked}
        for record in fallback:
            if len(picked) >= min_items:
                break
            if record.id not in seen:
                picked.append(record)
                seen.add(record.id)
        return picked[:max_items]

    def build_injection_context(self, query: str, min_items: int = 3, max_items: int = 5) -> str:
        """构造注入 Worker system prompt 的私有经验文本。"""
        records = self.search(query, min_items=min_items, max_items=max_items)
        if not records:
            return ""
        lines = ["## 专业Agent私有经验", "以下内容来自专业Agent自己的跨任务工作笔记，仅用于当前任务执行。"]
        for record in records:
            keywords = "、".join(record.keywords[:5])
            suffix = f"（关键词：{keywords}）" if keywords else ""
            lines.append(f"- [{record.kind}] {record.content}{suffix}")
        return "\n".join(lines)

    def count(self) -> int:
        if self._db_path is None:
            return len(self._mem)
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM professional_memory").fetchone()
            return int(row["c"])

    def _get_by_id(self, conn: sqlite3.Connection, record_id: int) -> ProfessionalMemoryRecord:
        row = conn.execute(
            "SELECT * FROM professional_memory WHERE id = ?",
            (record_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError("专业Agent记忆写入后读取失败")
        return self._row_to_record(row)

    def _find_similar(
        self,
        conn: sqlite3.Connection,
        kind: str,
        manual_keywords: list[str],
    ) -> sqlite3.Row | None:
        rows = conn.execute(
            "SELECT * FROM professional_memory WHERE kind = ? ORDER BY updated_at DESC LIMIT 30",
            (kind,),
        ).fetchall()
        return self._match_similar(rows, manual_keywords)

    def _find_similar_in_memory(self, kind: str, manual_keywords: list[str]) -> ProfessionalMemoryRecord | None:
        rows = [r for r in self._mem if r.kind == kind]
        matched = self._match_similar(rows, manual_keywords)
        return matched

    def _match_similar(self, rows, manual_keywords: list[str]):
        for row in rows:
            existing = row if isinstance(row, sqlite3.Row) else None
            if existing is not None:
                existing_meta = self._decode_json(existing["metadata"], {})
                existing_manual = existing_meta.get("_manual_keywords") or []
                overlap = set(existing_manual) & set(manual_keywords)
                strong_overlap = [
                    kw for kw in overlap
                    if len(kw) >= 4 or re.search(r"[A-Za-z]", kw)
                ]
                if len(overlap) >= 2 and strong_overlap:
                    return row
            else:
                # 内存记录
                if isinstance(row, ProfessionalMemoryRecord):
                    existing_meta = row.metadata or {}
                    existing_manual = existing_meta.get("_manual_keywords") or []
                    overlap = set(existing_manual) & set(manual_keywords)
                    strong_overlap = [
                        kw for kw in overlap
                        if len(kw) >= 4 or re.search(r"[A-Za-z]", kw)
                    ]
                    if len(overlap) >= 2 and strong_overlap:
                        return row
        return None

    def _trim_kind(self, conn: sqlite3.Connection, kind: str) -> None:
        rows = conn.execute(
            """
            SELECT id FROM professional_memory
            WHERE kind = ?
            ORDER BY updated_at DESC
            """,
            (kind,),
        ).fetchall()
        stale = rows[self._max_per_kind:]
        if not stale:
            return
        conn.executemany(
            "DELETE FROM professional_memory WHERE id = ?",
            [(row["id"],) for row in stale],
        )

    def _trim_kind_in_memory(self, kind: str) -> None:
        rows = [r for r in self._mem if r.kind == kind]
        if len(rows) <= self._max_per_kind:
            return
        rows.sort(key=lambda r: r.updated_at, reverse=True)
        keep = {r.id for r in rows[:self._max_per_kind]}
        self._mem = [r for r in self._mem if r.id in keep]

    @staticmethod
    def _normalize_kind(kind: str) -> str:
        kind = (kind or "").strip()
        if kind not in ALLOWED_KINDS:
            raise ValueError(f"不支持的专业Agent记忆类型: {kind}")
        return kind

    @staticmethod
    def _normalize_manual_keywords(keywords: list[str] | None) -> list[str]:
        result: list[str] = []
        for keyword in keywords or []:
            kw = str(keyword).strip()
            if kw and kw not in result:
                result.append(kw)
        return result[:12]

    @staticmethod
    def _normalize_keywords(keywords: list[str] | None, content: str) -> list[str]:
        result: list[str] = []
        for keyword in keywords or []:
            kw = str(keyword).strip()
            if kw and kw not in result:
                result.append(kw)
        for term in ProfessionalMemory._terms(content):
            if len(term) >= 2 and term not in result:
                result.append(term)
            if len(result) >= 12:
                break
        return result[:12]

    @staticmethod
    def _terms(text: str) -> set[str]:
        return {token.lower() for token in _TOKEN_RE.findall(text or "") if token.strip()}

    @staticmethod
    def _decode_json(text: str, default) -> object:
        try:
            return json.loads(text or "")
        except Exception:  # noqa: BLE001
            return default

    @staticmethod
    def _merge_keywords(left: list[str], right: list[str]) -> list[str]:
        merged: list[str] = []
        for keyword in list(left) + list(right):
            kw = str(keyword).strip()
            if kw and kw not in merged:
                merged.append(kw)
        return merged[:12]

    @staticmethod
    def _merge_metadata(left: dict, right: dict) -> dict:
        merged = dict(left or {})
        merged.update(right or {})
        return merged

    @staticmethod
    def _merge_content(old: str, new: str) -> str:
        if new in old:
            return old
        if old in new:
            return new
        return f"{old}\n补充：{new}"

    @staticmethod
    def _score_record(record: ProfessionalMemoryRecord, query_terms: set[str]) -> int:
        if not query_terms:
            return 0
        text_terms = ProfessionalMemory._terms(record.content)
        keyword_terms = {kw.lower() for kw in record.keywords}
        overlap = query_terms & (text_terms | keyword_terms)
        score = len(overlap) * 5
        joined = (record.content + " " + " ".join(record.keywords)).lower()
        for term in query_terms:
            if term and term in joined:
                score += 2
        score += min(record.hit_count, 5)
        return score

    def _row_to_record(self, row) -> ProfessionalMemoryRecord:
        if isinstance(row, sqlite3.Row):
            return ProfessionalMemoryRecord(
                id=int(row["id"]),
                kind=row["kind"],
                content=row["content"],
                keywords=list(self._decode_json(row["keywords"], [])),
                source_task_id=row["source_task_id"],
                hit_count=int(row["hit_count"]),
                created_at=float(row["created_at"]),
                updated_at=float(row["updated_at"]),
                metadata=dict(self._decode_json(row["metadata"], {})),
            )
        # 内存记录直接返回
        return row

    def _record_to_row(self, record: ProfessionalMemoryRecord):
        return record

    # ── 异步经验整理（可选，缺省跳过） ───────────────────────
    def schedule_trace_digest(
        self,
        trace_text: str,
        llm_fn: callable | None = None,
        model: str = "",
        task_id: str = "",
    ) -> str | None:
        """从任务轨迹提炼私有工作笔记；llm_fn 缺省则跳过整理。

        llm_fn 形如 fn(prompt:str)->str（同步或异步皆可，此处同步等待）。
        返回写入的摘要文本或 None。
        """
        if llm_fn is None:
            return None
        prompt = _DIGEST_PROMPT.replace("{trace_text}", (trace_text or "")[:12000])
        try:
            raw = llm_fn(prompt)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("专业Agent私有记忆整理失败（跳过）: %s", exc)
            return None
        data = _parse_json_object(raw)
        keywords = data.get("keywords") if isinstance(data.get("keywords"), list) else []
        written = []
        if data.get("experience"):
            self.add(K_EXPERIENCE, str(data["experience"]), keywords=keywords, source_task_id=task_id)
            written.append("experience")
        if data.get("user_profile"):
            self.add(K_USER_PROFILE, str(data["user_profile"]), keywords=keywords, source_task_id=task_id)
            written.append("user_profile")
        if data.get("error"):
            self.add(K_ERROR, str(data["error"]), keywords=keywords, source_task_id=task_id)
            written.append("error")
        return " ".join(written) if written else None


_DIGEST_PROMPT = """请从以下专业Agent任务轨迹中提炼私有工作笔记。

只输出 JSON 对象，不要解释：
{
  "experience": "可复用的任务经验，一句话；没有则空字符串",
  "user_profile": "用户工作偏好，一句话；没有则空字符串",
  "error": "错误记录或规避方式，一句话；没有则空字符串",
  "keywords": ["3到6个关键词"]
}

任务轨迹：
{trace_text}
"""


def _parse_json_object(text: str) -> dict:
    text = (text or "").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        data = json.loads(text[start:end + 1])
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}

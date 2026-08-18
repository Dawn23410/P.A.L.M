"""向量记忆 —— 基于 ChromaDB 的语义检索层。

职责：
- `add(text)` → 生成 embedding → 存入 ChromaDB
- `search(query, top_k)` → 生成 query embedding → 向量检索 → 返回结果
- 无 Ollama 时降级，不崩溃
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from palm._core.paths import brick_local

_LOGGER = logging.getLogger(__name__)

# 进程级客户端单例：按 persist_dir 复用 PersistentClient，避免每次 Agent 请求都重建
# 客户端（含 HNSW 索引加载/SQLite 打开），否则会叠加到首事件时延上。
_CLIENT_CACHE: dict[str, "chromadb.ClientAPI"] = {}


def _get_client(persist_dir: str) -> "chromadb.ClientAPI":
    """获取（或创建并缓存）ChromaDB 持久化客户端。"""
    import chromadb
    from chromadb.config import Settings as ChromaSettings
    cached = _CLIENT_CACHE.get(persist_dir)
    if cached is not None:
        return cached
    client = chromadb.PersistentClient(
        path=persist_dir,
        settings=ChromaSettings(anonymized_telemetry=False),
    )
    _CLIENT_CACHE[persist_dir] = client
    return client

# ── 嵌入模型配置 ──
# 主模型与降级模型必须同维度：ChromaDB 集合首次写入即锁定维度，降级到不同维度模型
# 会破坏集合维度一致性（报 "expecting 768 got 1024"）。bge-m3 与 mxbai-embed-large
# 均为 1024 维；nomic-embed-text 为 768 维，不可作为降级目标。
_DEFAULT_EMBED_MODEL = "bge-m3:latest"
_FALLBACK_EMBED_MODEL = "mxbai-embed-large:latest"
_OLLAMA_API = "http://127.0.0.1:11434/api/embed"
_COLLECTION_NAME = "agent_archived_memory"


def _ollama_embed(texts: list[str], model: str = _DEFAULT_EMBED_MODEL) -> list[list[float]] | None:
    """调用 Ollama embed API 批量生成向量；主模型失败时降级后备模型。

    经网卡门面出网（localhost 回环由网卡放行），不持有 urllib 原语。
    """
    from palm._core.net import request

    for attempt_model in [model, _FALLBACK_EMBED_MODEL]:
        try:
            resp = request("POST", _OLLAMA_API,
                           json={"model": attempt_model, "input": texts},
                           timeout=10.0)
            data = resp.json()
        except Exception:
            continue
        embeddings = data.get("embeddings")
        if embeddings:
            if attempt_model != model:
                _LOGGER.info("embedding 降级 %s ← %s", attempt_model, model)
            return embeddings
    _LOGGER.warning("所有 embedding 模型均不可用")
    return None


class VectorMemory:
    """基于 ChromaDB 的向量记忆存储。

    用法：
      vm = VectorMemory(persist_dir="Data/vector_memory")
      vm.add("用户偏好：喜欢猫娘")
      results = vm.search("用户喜欢什么风格", top_k=5)
    """

    def __init__(self, persist_dir: str = "", collection_name: str = _COLLECTION_NAME):
        self._persist_dir = persist_dir or brick_local(__file__, "data", "vector_memory")
        self._client: chromadb.ClientAPI | None = None
        self._collection: chromadb.Collection | None = None
        self._collection_name = collection_name
        self._ready = False

    # ── 生命周期 ─────────────────────────────────────────────────

    def initialize(self) -> None:
        """初始化 ChromaDB 客户端和集合（客户端进程级复用，不每次重建）。"""
        try:
            Path(self._persist_dir).mkdir(parents=True, exist_ok=True)
            self._client = _get_client(self._persist_dir)
            self._collection = self._client.get_or_create_collection(
                name=self._collection_name,
                metadata={"hnsw:space": "cosine"},
            )
            count = self._collection.count()
            _LOGGER.info("向量记忆就绪：集合=%s 条目=%d", self._collection_name, count)
            self._ready = True
        except Exception as exc:
            _LOGGER.warning("ChromaDB 初始化失败（向量记忆降级）: %s", exc)
            self._ready = False

    def close(self) -> None:
        """仅标记本实例不可用；客户端保留在进程级缓存以便后续请求复用。"""
        self._ready = False
        self._collection = None
        self._client = None

    @property
    def is_ready(self) -> bool:
        return self._ready

    # ── 写入 ─────────────────────────────────────────────────────

    def _heal_dimension_mismatch(self) -> bool:
        """旧集合以不同 embedding 维度创建导致写入/查询冲突时，删除旧集合并以当前
        模型维度重建，同时用新维度重索引旧文档（保留语义记忆）；重建失败则退化为空集合。
        """
        try:
            old = self._collection.get(include=["documents", "metadatas"])
            old_ids = old.get("ids", []) or []
            old_docs = old.get("documents", []) or []
            old_metas = old.get("metadatas", []) or []
            self._client.delete_collection(self._collection_name)
            self._collection = self._client.get_or_create_collection(
                name=self._collection_name, metadata={"hnsw:space": "cosine"})
            if old_docs:
                new_embs = _ollama_embed(old_docs)
                if new_embs:
                    self._collection.add(
                        ids=old_ids, embeddings=new_embs,
                        metadatas=old_metas, documents=old_docs)
                    _LOGGER.info("向量记忆维度自愈：重索引 %d 条旧记忆", len(old_docs))
            return True
        except Exception as exc:
            _LOGGER.warning("向量记忆维度自愈失败（尝试重建空集合）: %s", exc)
            try:
                self._client.delete_collection(self._collection_name)
                self._collection = self._client.get_or_create_collection(
                    name=self._collection_name, metadata={"hnsw:space": "cosine"})
                return True
            except Exception:
                return False

    def add(self, text: str, metadata: dict | None = None,
            batch: bool = False) -> str | None:
        """添加一条文本到向量记忆。

        返回记录 ID，embedding 失败时返回 None（不中断主流程）。
        """
        if not self._ready or not self._collection:
            return None

        record_id = uuid.uuid4().hex[:16]

        # 检查内容是否已存在（防重复）
        existing = self._collection.get(where={"content_hash": hash(text)})
        if existing and existing.get("ids"):
            return existing["ids"][0]

        # 生成 embedding
        embedding = _ollama_embed([text])
        if embedding is None:
            return None  # embedding 失败，无向量可存

        meta = {
            "content_hash": hash(text),
            "timestamp": datetime.now().isoformat(),
            "text_preview": text[:200],
        }
        if metadata:
            meta.update(metadata)

        try:
            self._collection.add(
                ids=[record_id],
                embeddings=embedding,
                metadatas=[meta],
                documents=[text],
            )
            return record_id
        except Exception as exc:
            # 维度冲突：旧集合以不同维度创建，重建并以当前维度重索引后再试一次
            if "dimension" in str(exc).lower() and self._heal_dimension_mismatch():
                try:
                    self._collection.add(
                        ids=[record_id], embeddings=embedding,
                        metadatas=[meta], documents=[text])
                    return record_id
                except Exception as exc2:
                    _LOGGER.warning("向量记忆写入失败(自愈后重试): %s", exc2)
                    return None
            _LOGGER.warning("向量记忆写入失败: %s", exc)
            return None

    # ── 检索 ─────────────────────────────────────────────────────

    def search(self, query: str, top_k: int = 5,
               where: dict | None = None) -> list[dict[str, Any]]:
        """语义检索最相关的记忆条目。

        返回：[{id, content, metadata, distance}, ...]
        """
        if not self._ready or not self._collection:
            return []

        query_emb = _ollama_embed([query])
        if query_emb is None:
            return []  # 无 embedding 则无法向量检索

        try:
            results = self._collection.query(
                query_embeddings=query_emb,
                n_results=min(top_k, 50),
                where=where,
            )
        except Exception as exc:
            # 维度冲突：旧集合维度与当前查询向量不符，自愈（重建+重索引）后重试一次
            if "dimension" in str(exc).lower() and self._heal_dimension_mismatch():
                try:
                    results = self._collection.query(
                        query_embeddings=query_emb,
                        n_results=min(top_k, 50), where=where)
                except Exception:
                    return []
                return self._parse_results(results)
            _LOGGER.warning("向量检索失败: %s", exc)
            return []

        return self._parse_results(results)

    def _parse_results(self, results: dict) -> list[dict[str, Any]]:
        """把 ChromaDB query 返回扁平化为统一条目列表。"""
        items: list[dict[str, Any]] = []
        metas = results.get("metadatas", [[]])[0] or []
        docs = results.get("documents", [[]])[0] or []
        dists = results.get("distances", [[]])[0] or []
        ids = results.get("ids", [[]])[0] or []

        for i in range(len(ids)):
            items.append({
                "id": ids[i],
                "content": docs[i] if i < len(docs) else "",
                "metadata": metas[i] if i < len(metas) else {},
                "distance": dists[i] if i < len(dists) else 1.0,
                "score": 1.0 - (dists[i] if i < len(dists) else 0.0),
            })

        return items

    # ── 统计 ─────────────────────────────────────────────────────

    def count(self) -> int:
        if self._ready and self._collection:
            try:
                return self._collection.count()
            except Exception:
                pass
        return 0

    def get_recent(self, limit: int = 30, where: dict | None = None,
                   skip_kind: str | None = None) -> list[dict[str, Any]]:
        """按写入时间倒序取近期记忆文本（跳过简报等指定 kind，可附加 where 过滤）。

        每日简报等场景的读取源必须是这里——ArchivedMemory 是纯内存壳不落盘，
        跨进程持久的长期记忆实际落在 VectorMemory（ChromaDB），从空壳 archived
        读取会让简报在真实部署中恒为空、永不生成。
        """
        if not (self._ready and self._collection):
            return []
        try:
            res = self._collection.get(include=["documents", "metadatas"], where=where)
        except Exception:
            return []
        docs = res.get("documents", []) or []
        metas = res.get("metadatas", []) or []
        pairs: list[tuple[str, str]] = []
        for doc, meta in zip(docs, metas):
            if not doc:
                continue
            meta = meta or {}
            if skip_kind and meta.get("kind") == skip_kind:
                continue
            pairs.append((meta.get("timestamp", ""), doc))
        # 按时间戳升序后取末尾 limit 条 = 最近 limit 条
        pairs.sort(key=lambda x: x[0])
        return [{"content": doc} for _, doc in pairs[-limit:]]

    def delete(self, record_id: str) -> None:
        if self._ready and self._collection:
            try:
                self._collection.delete(ids=[record_id])
            except Exception:
                pass

    def purge_by_conv_id(self, conv_id: str) -> int:
        """删除本集合内 metadata.conv_id 匹配的条目，返回删除条数。"""
        if not conv_id or not (self._ready and self._collection):
            return 0
        try:
            res = self._collection.get(where={"conv_id": conv_id}, include=[])
            ids = res.get("ids", []) or []
            if ids:
                self._collection.delete(ids=ids)
                return len(ids)
        except Exception:
            pass
        return 0


def purge_vector_by_conv_id(conv_id: str, base_dir: str = "") -> int:
    """跨全部角色集合删除 metadata.conv_id 匹配的向量条目，返回删除条数。

    向量记忆按角色共享存储（vector_memory/{角色}），删除单会话需逐集合扫描定位，
    而非整目录清理。仅对写入 conv_id 的条目生效（A2 之后落盘的）。
    """
    if not conv_id:
        return 0
    base = Path(base_dir) if base_dir else brick_local(__file__, "data", "vector_memory")
    if not base.is_dir():
        return 0
    total = 0
    for coll_dir in sorted(base.iterdir()):
        if not coll_dir.is_dir():
            continue
        try:
            client = _get_client(str(coll_dir))
            collection = client.get_or_create_collection(
                name=_COLLECTION_NAME, metadata={"hnsw:space": "cosine"})
            res = collection.get(where={"conv_id": conv_id}, include=[])
            ids = res.get("ids", []) or []
            if ids:
                collection.delete(ids=ids)
                total += len(ids)
        except Exception:
            continue
    return total

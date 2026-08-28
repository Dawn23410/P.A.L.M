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

# 本地 ONNX embedding（脱离 Ollama 运行时）：weights/ 下放置
# bge_m3.onnx + tokenizer.json（Xenova/bge-m3 转换版，1024 维）。
# 模型缺失 / onnxruntime 未装 / 推理失败 → 返回 None，由 Ollama 接口兜底。
_WEIGHTS_DIR = Path(__file__).resolve().parent / "weights"
_onnx_session = None
_onnx_tokenizer = None


def _local_onnx_embed(texts: list[str]) -> list[list[float]] | None:
    """本地 bge-m3 ONNX 推理：XLM-R 词表 tokenize → [CLS] 池化 → L2 归一化（1024 维）。"""
    global _onnx_session, _onnx_tokenizer
    model_path = _WEIGHTS_DIR / "bge_m3.onnx"
    tok_path = _WEIGHTS_DIR / "tokenizer.json"
    if not (model_path.is_file() and tok_path.is_file()):
        return None
    try:
        if _onnx_session is None:
            import onnxruntime as ort
            _onnx_session = ort.InferenceSession(
                str(model_path), providers=["CPUExecutionProvider"])
        if _onnx_tokenizer is None:
            from tokenizers import Tokenizer
            _onnx_tokenizer = Tokenizer.from_file(str(tok_path))
        encs = _onnx_tokenizer.encode_batch(texts, add_special_tokens=True)
        max_len = min(max((len(e.ids) for e in encs), default=1), 8192)
        input_ids, attn = [], []
        for e in encs:
            ids = e.ids[:max_len]
            input_ids.append(ids + [0] * (max_len - len(ids)))
            attn.append([1] * len(ids) + [0] * (max_len - len(ids)))
        outputs = _onnx_session.run(None, {
            "input_ids": input_ids, "attention_mask": attn})
        # Xenova 转换版输出 last_hidden_state[batch, seq, 1024] → [CLS] 池化；
        # 兼容直接输出 [batch, 1024] 的导出形态。
        emb = outputs[0]
        cls_vec = emb[:, 0, :] if len(emb.shape) == 3 else emb
        vecs = []
        for v in cls_vec:
            # float() 包裹 sum：np.float32 累加会污染 norm 类型，导致后续除法
            # 结果仍是 np.float32（chromadb 校验拒绝），必须回归 Python float
            norm = float(sum(x * x for x in v)) ** 0.5
            vecs.append([round(float(x) / norm, 6) if norm else 0.0 for x in v])
        return vecs
    except Exception as exc:
        _LOGGER.warning("本地 ONNX embedding 不可用：%s", exc)
        return None


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


def _embed(texts: list[str]) -> list[list[float]] | None:
    """embedding 总入口：本地 ONNX 优先（脱离 Ollama），失败走 Ollama 接口。"""
    vecs = _local_onnx_embed(texts)
    if vecs:
        return vecs
    return _ollama_embed(texts)


class VectorMemory:
    """基于 ChromaDB 的向量记忆存储。

    用法：
      vm = VectorMemory(persist_dir="Data/vector_memory")
      vm.add("用户偏好：喜欢猫娘")
      results = vm.search("用户喜欢什么风格", top_k=5)
    """

    def __init__(self, persist_dir: str = "", collection_name: str = _COLLECTION_NAME,
                 cipher=None):
        self._persist_dir = persist_dir or brick_local(__file__, "data", "vector_memory")
        self._client: chromadb.ClientAPI | None = None
        self._collection: chromadb.Collection | None = None
        self._collection_name = collection_name
        self._ready = False
        # 可选加密器（encrypt_text/decrypt_text）：加密落盘，检索返回时解密；None=明文
        self._cipher = cipher

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
        """关闭底层 ChromaDB 客户端并释放 SQLite 文件锁。

        同时移出进程级缓存：close 后目录可被清理/重建；后续复用由 _get_client
        按需新建（缓存 miss 自动重建）。
        """
        self._ready = False
        self._collection = None
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            _CLIENT_CACHE.pop(self._persist_dir, None)
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
                new_embs = _embed(old_docs)
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
        embedding = _embed([text])
        if embedding is None:
            return None  # embedding 失败，无向量可存

        meta = {
            "content_hash": hash(text),
            "timestamp": datetime.now().isoformat(),
            # 预览与正文同样加密（避免泄露明文）
            "text_preview": (self._cipher.encrypt_text(text[:200])
                             if self._cipher else text[:200]),
        }
        if metadata:
            meta.update(metadata)

        doc_text = self._cipher.encrypt_text(text) if self._cipher else text

        try:
            self._collection.add(
                ids=[record_id],
                embeddings=embedding,
                metadatas=[meta],
                documents=[doc_text],
            )
            return record_id
        except Exception as exc:
            # 维度冲突：旧集合以不同维度创建，重建并以当前维度重索引后再试一次
            if "dimension" in str(exc).lower() and self._heal_dimension_mismatch():
                try:
                    self._collection.add(
                        ids=[record_id], embeddings=embedding,
                        metadatas=[meta], documents=[doc_text])
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

        query_emb = _embed([query])
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
            raw_doc = docs[i] if i < len(docs) else ""
            # 加密器存在时返回前解密；旧明文数据解密失败原样返回（兼容）
            content = (self._cipher.decrypt_text(raw_doc)
                       if self._cipher and raw_doc else raw_doc)
            items.append({
                "id": ids[i],
                "content": content,
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

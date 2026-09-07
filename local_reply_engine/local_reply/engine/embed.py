"""本地 ONNX 嵌入层（zero-network 推理），独立包自包含。

模型选择（env `PALM_EMBED_MODEL`）：
- "m3"（默认）：Xenova/bge-m3 转换版，1024 维，[CLS] 池化 + L2 归一化。
- "small"：bge-small-zh-v1.5 int8，512 维——低内存档（RSS ~300MB），
  质量缩水见 能力复测_换模型对比 报告。

设计约束：
- 权重只从本包 models/weights/ 加载（独立包自包含，不依赖外部项目）。
- 纯依赖 onnxruntime + tokenizers + numpy（default venv 已装）。
- 失败时返回 None（fail-closed），由调用方降级到 lexical 检索，绝不崩主流程。
- 进程级单例缓存 session/tokenizer，避免每次请求重建导致首事件时延叠加。
"""
from __future__ import annotations

import math
import os
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_WEIGHTS_DIR = _THIS_DIR / "models" / "weights"

# 模型注册表：tag → (onnx 文件名, tokenizer 文件名, 维度, max_len)
# max_len=256：聊天查询中位 18 token，8192 上限会让单条长粘贴打出
# +4.8GB RSS / 18.3s 停顿（ORT arena 永久保留，实测见 mem 探针）——256 封顶零质量损失。
_MODEL_REGISTRY = {
    "m3": ("bge_m3.onnx", "tokenizer.json", 1024, 256),
    "small": ("bge_small.onnx", "tokenizer_small.json", 512, 512),
}


def _active_tag() -> str:
    tag = os.environ.get("PALM_EMBED_MODEL", "m3").strip().lower()
    return tag if tag in _MODEL_REGISTRY else "m3"


def model_tag() -> str:
    """当前嵌入模型标识（供缓存文件命名/日志）。"""
    return _active_tag()


def _resolve_paths():
    fname, tok_name, _dim, _ml = _MODEL_REGISTRY[_active_tag()]
    model_path = _WEIGHTS_DIR / fname
    tok_path = _WEIGHTS_DIR / tok_name
    return (model_path if model_path.is_file() else None,
            tok_path if tok_path.is_file() else None)


_session = None
_tokenizer = None
_ready = None  # True / False / None(未探测)


def is_available() -> bool:
    """权重与依赖是否齐备，可跑本地语义嵌入。"""
    global _ready
    if _ready is not None:
        return _ready
    model_path, tok_path = _resolve_paths()
    if model_path is None or tok_path is None:
        _ready = False
        return False
    try:
        import onnxruntime  # noqa: F401
        import tokenizers   # noqa: F401
        import numpy        # noqa: F401
        _ready = True
    except Exception:
        _ready = False
    return _ready


def _ensure_session():
    global _session, _tokenizer
    if _session is not None and _tokenizer is not None:
        return _session, _tokenizer
    model_path, tok_path = _resolve_paths()
    if model_path is None or tok_path is None:
        raise RuntimeError(f"嵌入权重缺失（PALM_EMBED_MODEL={_active_tag()}）")
    import onnxruntime as ort
    from tokenizers import Tokenizer
    # WHY 锁线程：本机 24 逻辑核，embed 默认全核 + reranker 锁 8 → 两 ORT session
    # 争抢调度，respond 偶发 3.5s 级抖动（实测两次复现于同一 query）。两侧都锁 8 后
    # 稳态 ~15ms。与 reranker._load 同一约束：两个 session 共存必须都锁线程。
    so = ort.SessionOptions()
    so.intra_op_num_threads = 8
    so.inter_op_num_threads = 1
    _session = ort.InferenceSession(str(model_path), so, providers=["CPUExecutionProvider"])
    _tokenizer = Tokenizer.from_file(str(tok_path))
    return _session, _tokenizer


def dim() -> int:
    """当前模型的向量维度（索引矩阵/缓存校验用）。"""
    return _MODEL_REGISTRY[_active_tag()][2]


def _make_feed(sess, input_ids, attn) -> dict:
    """按 session 实际签名构造输入：bge-m3 只要 ids/mask，bge-small 还要 token_type_ids。"""
    feed = {"input_ids": input_ids, "attention_mask": attn}
    if "token_type_ids" in {i.name for i in sess.get_inputs()}:
        feed["token_type_ids"] = [[0] * len(r) for r in input_ids]
    return feed


def embed(texts: list[str]) -> list[list[float]] | None:
    """批量生成 L2 归一化向量（维度随模型）；失败返回 None（fail-closed）。"""
    if not texts:
        return []
    try:
        sess, tok = _ensure_session()
    except Exception:
        return None
    try:
        max_len_cap = _MODEL_REGISTRY[_active_tag()][3]
        encs = tok.encode_batch(texts, add_special_tokens=True)
        max_len = min(max((len(e.ids) for e in encs), default=1), max_len_cap)
        input_ids, attn = [], []
        for e in encs:
            ids = e.ids[:max_len]
            input_ids.append(ids + [0] * (max_len - len(ids)))
            attn.append([1] * len(ids) + [0] * (max_len - len(ids)))
        outputs = sess.run(None, _make_feed(sess, input_ids, attn))
        emb = outputs[0]
        cls_vec = emb[:, 0, :] if len(emb.shape) == 3 else emb
        vecs = []
        for v in cls_vec:
            norm = math.sqrt(float(sum(x * x for x in v)))
            vecs.append([round(float(x) / norm, 6) if norm else 0.0 for x in v])
        return vecs
    except Exception:
        return None


def cosine(a: list[float], b: list[float]) -> float:
    """余弦相似度（输入已 L2 归一化时可简化为点积）。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))


__all__ = ["is_available", "embed", "cosine", "dim", "model_tag"]

# -*- coding: utf-8 -*-
"""Cross-encoder 重排器（bge-reranker-base int8 ONNX）。

WHY：稠密检索的双塔点积是「各说各话再对答案」，中带（0.72~0.80）的存疑
候选常差之毫厘。cross-encoder 把 (query, candidate) 拼在一起过 transformer，
交互更充分，专治榜首不清。但每对候选都要全量前向，成本 ~2ms/对（int8 CPU），
故**只对存疑中带、只对 top-K=8** 重排——高带直通、低带直接降级，不进这里。
"""
import os
import math

_BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "reranker")
_V2M3 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "reranker_v2m3")


def _pick_dir():
    """v2-m3（多语言强基座，中文域标定有效）优先；base 已标定失效仅作兜底。"""
    for d in (_V2M3, _BASE):
        if os.path.exists(os.path.join(d, "model_quant.onnx")) and \
           os.path.exists(os.path.join(d, "tokenizer.json")):
            return d
    return None


_DIR = None
_ONNX = None
_TOK = None

_session = None
_tokenizer = None
_max_len = 128


def is_available():
    d = _pick_dir()
    return d is not None


def warmup():
    """启动期预加载模型。WHY：880MB 首载 2~3.5s 是一次性开销，惰性加载会把它
    推迟到对话中途——空泛句门槛修掉 warm 路径后实测复现（3942ms 尖峰落在
    连贯性重排首触发）。用户的 400ms 预算内禁止模型冷启动，故在引擎 _load
    时显式预热。fail-closed：加载失败静默，rerank 时再退回原判定。"""
    _load()


def _load():
    global _session, _tokenizer, _DIR, _ONNX, _TOK
    if _session is not None:
        return True
    _DIR = _pick_dir()
    if _DIR is None:
        return False
    _ONNX = os.path.join(_DIR, "model_quant.onnx")
    if not os.path.exists(_ONNX):
        _ONNX = os.path.join(_DIR, "model_quantized.onnx")
    _TOK = os.path.join(_DIR, "tokenizer.json")
    try:
        import onnxruntime as ort
        from tokenizers import Tokenizer
        # WHY intra=8：默认 24 逻辑核全开时，与 bge-m3 embed session 的线程池
        # 互相踩踏，实测单次 326~3900ms 剧烈抖动；锁 8 线程后稳定 ~150ms。
        so = ort.SessionOptions()
        so.intra_op_num_threads = 8
        so.inter_op_num_threads = 1
        _session = ort.InferenceSession(
            _ONNX, sess_options=so,
            providers=["CPUExecutionProvider"])
        _tokenizer = Tokenizer.from_file(_TOK)
        _tokenizer.no_padding()
        _tokenizer.no_truncation()
        return True
    except Exception:
        _session = None
        _tokenizer = None
        return False


def _encode_pairs(query, texts, max_len=None):
    """手工拼 XLM-R 对句格式：<s> q </s></s> c </s>（Xenova 导出的
    post_processor 模板不保证带 pair 分支，手工构造数值等价且可控）。"""
    if max_len is None:
        max_len = _max_len
    enc_q = _tokenizer.encode(query, add_special_tokens=False)
    ids_q = [0] + enc_q.ids[:max_len - 4] + [2]
    out = []
    for t in texts:
        enc_c = _tokenizer.encode(t, add_special_tokens=False)
        ids_c = [0] + enc_c.ids[:_max_len - len(ids_q) - 3] + [2]
        ids = ids_q + [2] + ids_c
        mask = [1] * len(ids)
        out.append((ids, mask))
    return out


def rerank(query, candidates, max_len=_max_len):
    """candidates: [(idx, dense_score, text)] → [(idx, 相关概率)]，按概率降序。

    max_len 可调：连贯性重排传 96（正文短），压缩 padding 换延迟。
    返回 sigmoid 后的**相关概率**（0~1），调用方用标定阈值判接受。
    fail-closed：模型不可用/异常 → 返回 None，调用方保持原判定。
    """
    if not candidates:
        return None
    if not _load():
        return None
    texts = [c[2] for c in candidates]
    try:
        pairs = _encode_pairs(query, texts, max_len)
        max_len = max(len(ids) for ids, _ in pairs)
        input_ids = [ids + [1] * (max_len - len(ids)) for ids, _ in pairs]
        attn = [m + [0] * (max_len - len(m)) for _, m in pairs]
        feed = {
            "input_ids": input_ids,
            "attention_mask": attn,
        }
        names = {i.name for i in _session.get_inputs()}
        if "token_type_ids" in names:
            feed["token_type_ids"] = [[0] * max_len for _ in input_ids]
        logits = _session.run(None, feed)[0]
        # 兼容 (1, b, 1) / (b, 1) / (b,) 三种导出形状
        flat = [float(x) for x in logits.reshape(-1)]
        probs = [1.0 / (1.0 + math.exp(-l)) for l in flat]
        ranked = sorted(
            ((candidates[i][0], p) for i, p in enumerate(probs)),
            key=lambda x: x[1], reverse=True)
        return ranked
    except Exception:
        return None

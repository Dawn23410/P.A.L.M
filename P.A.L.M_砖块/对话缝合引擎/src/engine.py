# -*- coding: utf-8 -*-
"""对话缝合引擎 · 运行时（零联网，默认 mock 模式）。

流水线：情感调语气 → 检索召回 → 桥接缝合 → 人格四要素调味 → 多样性改写 → 短上下文回调。

两种检索后端：
- 默认 mock 模式：core.HybridRetriever（BM25 + 字 n-gram TF-IDF）内存索引，
  零模型、零预构建向量，开箱即用。这是砖的默认形态。
- 可选语义升级：当本砖 models/weights/bge_small.onnx 就位 且 data/stitching_vectors.json
  已预构建时，自动切换为 bge 稠密语义检索（hub.Embedder 真实路径）。接口不变，
  权重就位即升级，缺失则静默退回 mock。
"""
import json
import os
import re
import random
import glob

from . import core
from .hub import Hub


def _cosine(a, b):
    # 稀疏 dict 余弦（离线哈希向量）
    inter = set(a) & set(b)
    return sum(a[k] * b[k] for k in inter)


class StitchEngine:
    def __init__(self, corpus_dir=None, data_dir=None, hub=None, use_jieba=True):
        here = os.path.dirname(__file__)
        self.corpus_dir = corpus_dir or os.path.join(here, "corpus")
        self.data_dir = data_dir or os.path.join(here, "data")
        self.hub = hub or Hub()
        self.use_jieba = use_jieba
        self.records = []
        self.mode = "mock"
        self.vectors = None
        self._load()

    def _load(self):
        part_files = sorted(glob.glob(os.path.join(self.corpus_dir, "mengyao_hq_part*.jsonl")))
        self.records = core.load_persona_bank(part_files)
        if not self.records:
            raise FileNotFoundError(f"未找到手写语料：{self.corpus_dir}/mengyao_hq_part*.jsonl")
        # 可选语义升级：真实 embedder 可用 + 预构建稠密向量就位 → 切换 semantic
        vec_path = os.path.join(self.data_dir, "stitching_vectors.json")
        corpus_path = os.path.join(self.data_dir, "stitching_corpus.jsonl")
        if self.hub.embedder.available() and os.path.exists(vec_path) and os.path.exists(corpus_path):
            try:
                with open(corpus_path, encoding="utf-8") as fh:
                    disk = [json.loads(l) for l in fh if l.strip()]
                if len(disk) == len(self.records):
                    with open(vec_path, encoding="utf-8") as fh:
                        self.vectors = json.load(fh)
                    self.mode = "semantic"
            except Exception:
                self.vectors = None
        if self.mode == "mock":
            self.retriever = core.HybridRetriever(self.records, self.use_jieba)

    # ── 检索 ──
    def retrieve(self, query, top_k=3):
        if self.mode == "semantic" and self.vectors is not None:
            qv = self.hub.embedder.encode([query])[0]
            scored = [(i, _cosine(qv, v)) for i, v in enumerate(self.vectors)]
            scored.sort(key=lambda x: x[1], reverse=True)
            return scored[:top_k]
        # HybridRetriever.search 返回 (idx, 混合分, 词级分, 字级分)，归一为 (idx, 分)。
        return [(i, mixed) for (i, mixed, _, _) in self.retriever.search(query, top_k)]

    # ── 主入口 ──
    def respond(self, query, history=None):
        history = history or []
        emotion, _ = self.hub.sentiment.classify(query)
        tone = self.hub.sentiment.tone_for(emotion)
        scored = self.retrieve(query, 3)
        # 相对阈值：top1 须明显领先 top2，否则视为未命中（避免中文短句误匹配）
        if not scored or (len(scored) > 1 and scored[0][1] < max(scored[1][1] * 1.05, 0.02)):
            return self._fallback(emotion, tone, query, scored)
        top = [self.records[i] for i, _ in scored]
        base = top[0]
        body = base.get("body") or base.get("a_raw")
        bridge = self._pick_bridge(top, query, body)
        flavored = self._flavor(base, body + bridge, tone)
        variants = self.hub.rewriter.rewrite(flavored, n=3)
        pick = variants[abs(hash(query)) % len(variants)]
        reply = self._callback(pick, history)
        return {
            "reply": reply,
            "emotion": emotion,
            "tone_manner": random.choice(tone["manner"]),
            "matches": [(self.records[i]["q"], round(s, 4)) for i, s in scored],
            "rewrite_variants": variants,
            "mode": self.mode,
            "recall_real": scored[0][1] >= 0.02,
            "recognized": True,
            "suggest_llm": False,
        }

    def _fallback(self, emotion, tone, query, scored):
        # 诚实兜底：检索无自信匹配时，明确告知自己答不了，建议用户请教 LLM，
        # 绝不假装“没听清/再说一遍”误导用户以为输入有问题。
        line = random.choice([
            "呜…翻遍了猫娘的对话小本本也没找到能接上的回答，怕乱答会骗到你。这种问题你还是去问问大语言模型吧，它们懂得多喵",
            "这个嘛…我对话库里没翻到合适的，不想瞎编误导你。要不你拿去问 LLM？比我靠谱呜",
            "杂鱼，这道题超出猫娘能答的范围啦，硬答会出错。建议直接问大语言模型，它们更在行",
        ])
        reply = self._callback(line, [])
        return {
            "reply": reply,
            "emotion": emotion,
            "tone_manner": random.choice(tone["manner"]),
            "matches": [(self.records[i]["q"], round(s, 4)) for i, s in scored],
            "rewrite_variants": [reply],
            "mode": self.mode,
            "recall_real": False,
            "recognized": False,
            "suggest_llm": True,
        }

    def _pick_bridge(self, top, query, base_body):
        if len(top) < 2:
            return ""
        second = re.split(r"[。！？\n]", top[1].get("body") or "")[0].strip()
        if len(second) < 4 or len(second) > 20:
            return ""
        toks = set(re.sub(r"\s+", "", query)) | set(re.sub(r"\s+", "", base_body))
        if not any(t in second for t in toks if len(t) > 1):
            return ""
        return f"，对了，{second}"

    def _flavor(self, base, fused, tone):
        parts = []
        if random.random() < 0.6:
            manner = tone["manner"]
            parts.append(f"（{random.choice(manner)}）")
        body = fused
        if random.random() < 0.5:
            body = self._diversify(body)
        if base.get("inner") and random.random() < 0.3:
            parts.insert(0, f"<{base['inner']}>")
        if base.get("action") and random.random() < 0.4:
            parts.insert(0, f"[{base['action']}]")
        return "".join(parts) + body

    def _diversify(self, text):
        # 只替换多字词语，避免单字拆坏复合词（如「好吃」被「好→可还行」破坏）
        for word, syns in core.EXPRESSION_LIB.items():
            if len(word) >= 2 and word in text and random.random() < 0.4:
                text = text.replace(word, random.choice(syns), 1)
        return text

    def _callback(self, text, history):
        """短上下文回调：若本轮与上一轮共享话题词，补一句承接，增强连续感。"""
        if len(history) < 1:
            return text
        prev = history[-1]
        grams = {prev[i:i + 2] for i in range(len(prev) - 1)}
        shared = [g for g in grams if g in text and len(g) == 2]
        if shared and random.random() < 0.5:
            return text + f"（就像你刚说的「{random.choice(shared)}」那回事）"
        return text

    def status(self):
        return {
            "mode": self.mode,
            "records": len(self.records),
            "models": self.hub.status(),
        }

# -*- coding: utf-8 -*-
"""对话缝合引擎 · 核心检索与解析（零依赖，默认 mock 模式）。

移植自桌面 _stitching_demo/zh_stitch_core.py，适配为砖内模块。

设计目标（对应中文环境优化 + 默认 mock）：
- 纯规则「BM25 + 字 n-gram 混合稀疏检索」，零神经模型依赖。
  仅用 jieba 词典分词（可选关闭，关闭后纯字符级、仅标准库）。不导入任何
  Embedding / LLM；神经向量模型（bge-small-zh 等）仅作为可选升级项，由 engine.py
  在有真实权重时替换检索后端，本模块永不加载模型。
- 四要素解析 [动作]（神态）<内心> 正文，与角色卡「格式约定」对齐。
- 参数集从梦瑶手写语料抽取经验库（四要素模板 + 习惯动作 + 口癖）。

网络不可达、无第三方包时整条流水线仍可离线跑通（mock 模式）。
"""
import json
import math
import os
import random
import re
from collections import defaultdict

# 四要素解析： [动作]（神态）<内心> 正文
_FEAT_RE = re.compile(
    r"^\[(?P<action>[^\]]*)\]\s*（(?P<manner>[^）]*)）\s*<(?P<inner>[^>]*)>\s*(?P<body>.*)$",
    re.DOTALL,
)


def parse_reply(text):
    """把一条助手回复拆成四要素；非标准格式整体当作正文。"""
    m = _FEAT_RE.match((text or "").strip())
    if not m:
        return {"action": "", "manner": "", "inner": "", "body": (text or "").strip()}
    return {
        "action": m.group("action").strip(),
        "manner": m.group("manner").strip(),
        "inner": m.group("inner").strip(),
        "body": m.group("body").strip(),
    }


def load_persona_bank(jsonl_paths, limit=5000):
    """从手写语料 jsonl（可多个文件）加载经验库；抽取四要素。

    入参 jsonl_paths 为路径列表（glob 结果），每行形如
    {"conversations":[{"from":"human","value":..},{"from":"gpt","value":..}]}。
    """
    records = []
    for path in jsonl_paths:
        with open(path, encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                if i >= limit:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except (ValueError, json.JSONDecodeError):
                    continue
                conv = obj.get("conversations", [])
                q = next((m["value"] for m in conv if m["from"] == "human"), "")
                a = next((m["value"] for m in conv if m["from"] == "gpt"), "")
                if not q or not a:
                    continue
                feats = parse_reply(a)
                records.append({"q": q, "a_raw": a, **feats})
    return records


def char_ngrams(text, n=2):
    """字 n-gram：缓解分词错误，增强中文模糊匹配。"""
    text = re.sub(r"\s+", "", text)
    if len(text) < n:
        return [text] if text else []
    return [text[i:i + n] for i in range(len(text) - n + 1)]


def tokenize(text, use_jieba=True):
    """分词：默认 jieba 词典分词；关闭后纯字符级（零外部依赖，纯规则）。

    jieba 为惰性导入——本模块不要求任何第三方包即可加载，关掉 jieba 后
    仅靠标准库即可完成检索，彻底满足「不依赖任何模型」的约束。
    """
    if use_jieba:
        try:
            import jieba
            return list(jieba.cut(text))
        except Exception:
            pass
    # 纯字符级：去空白后逐字（规则兜底，不依赖任何模型/词典）
    return [c for c in re.sub(r"\s+", "", text)]


class HybridRetriever:
    """离线混合稀疏检索：BM25（词级）+ 字 n-gram TF-IDF 余弦（字级）。

    替代英文句向量；不依赖任何联网模型即可工作。构建期在内存从语料建立索引，
    运行期只做查表，零模型零预构建向量文件 —— 这是砖的「默认 mock 模式」检索后端。
    """

    def __init__(self, records, use_jieba=True):
        self.records = records
        self.use_jieba = use_jieba
        self.doc_tokens = [tokenize(r["q"], use_jieba) for r in records]
        self.doc_grams = [char_ngrams(r["q"]) for r in records]
        self._build_bm25()
        self._build_gram_idf()

    def _build_bm25(self):
        n = len(self.doc_tokens)
        df = defaultdict(int)
        for toks in self.doc_tokens:
            for t in set(toks):
                df[t] += 1
        self.bm25_idf = {t: math.log((n - df[t] + 0.5) / (df[t] + 0.5) + 1) for t in df}
        self.avg_dl = sum(len(t) for t in self.doc_tokens) / max(1, n)

    def _build_gram_idf(self):
        n = len(self.doc_grams)
        df = defaultdict(int)
        for gs in self.doc_grams:
            for g in set(gs):
                df[g] += 1
        self.gram_idf = {g: math.log((n - df[g] + 0.5) / (df[g] + 0.5) + 1) for g in df}

    def _bm25_score(self, q_tokens, doc_i):
        dl = len(self.doc_tokens[doc_i]) or 1
        k1, b = 1.5, 0.75
        tf = defaultdict(int)
        for t in self.doc_tokens[doc_i]:
            tf[t] += 1
        score = 0.0
        for t in q_tokens:
            if t in self.bm25_idf:
                f = tf[t]
                score += self.bm25_idf[t] * (f * (k1 + 1)) / (f + k1 * (1 - b + b * dl / self.avg_dl))
        return score

    def _gram_score(self, q_grams, doc_i):
        doc_gs = self.doc_grams[doc_i]
        doc_tf = defaultdict(int)
        for g in doc_gs:
            doc_tf[g] += 1
        denom = math.sqrt(len(q_grams) * len(doc_gs)) or 1
        dot = 0.0
        for g in set(q_grams):
            if g in doc_tf:
                q_w = self.gram_idf.get(g, 0.0)
                d_w = self.gram_idf.get(g, 0.0) * doc_tf[g]
                dot += q_w * d_w
        return dot / denom

    def search(self, query, top_k=3):
        """返回 [(idx, 混合得分, 词级分, 字级分)]，按混合分降序。"""
        q_tokens = tokenize(query, self.use_jieba)
        q_grams = char_ngrams(query)
        scored = []
        for i in range(len(self.records)):
            s_bm = self._bm25_score(q_tokens, i)
            s_gr = self._gram_score(q_grams, i)
            mixed = 0.7 * s_bm + 0.3 * s_gr
            scored.append((i, mixed, s_bm, s_gr))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]


# 扩充口语/情绪表达库（原 Demo 仅 3 个词）。覆盖常见情绪与通用词，带口语与喵味变体。
EXPRESSION_LIB = {
    "开心": ["高兴", "快乐", "愉快", "美滋滋", "乐呵", "欢喜"],
    "难过": ["伤心", "沮丧", "低落", "失落", "难受", "委屈"],
    "好": ["棒", "不错", "挺好", "蛮赞", "贼好", "可还行"],
    "喜欢": ["中意", "稀饭", "爱死", "好感", "待见"],
    "累": ["乏", "疲", "倦", "没劲儿", "虚", "瘫了"],
    "饿": ["肚子空", "饥", "想啃", "胃抗议", "嘴馋"],
    "想": ["惦记", "念叨", "琢磨", "盘算", "挂念"],
    "漂亮": ["好看", "养眼", "标致", "水灵", "俏"],
    "讨厌": ["烦", "膈应", "嫌弃", "不爱", "腻歪"],
    "害怕": ["怂", "慌", "怯", "发毛", "虚得很"],
    "冷": ["凉", "冻", "寒", "瑟瑟", "冰"],
    "热": ["烫", "闷", "燥", "汗颜", "焐"],
    "困": ["瞌睡", "乏眼皮", "眯瞪", "想睡", "犯懒"],
    "无聊": ["闲得慌", "没劲", "发闷", "空落落", "闷得慌"],
    "生气": ["恼", "火大", "憋屈", "炸毛", "气鼓鼓"],
    "谢谢": ["谢啦", "多谢", "承情", "感喵", "谢喵"],
    "可以": ["成", "行", "没毛病", "妥", "中"],
    "知道": ["晓得", "懂了", "门儿清", "悟了", "明了"],
    "真的": ["当真", "没忽悠", "绝了", "不骗喵", "实打实"],
}

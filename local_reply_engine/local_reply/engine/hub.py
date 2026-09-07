# -*- coding: utf-8 -*-
"""垂直小模型中心：真实权重(本地) + 离线占位(零依赖) 双后端。

移植自桌面 _stitching_demo/models/hub.py，适配为砖内模块。

设计原则（对应约束）：
- 垂直领域小模型可用，禁用对话式 LLM：这里只有「嵌入 / 情感分类 / 改写」三类单任务小模型。
- 运行期绝对零联网：权重与语料全部本地；真实权重缺失时自动降级为离线实现，
  接口不变，权重就位即获得完整能力（无需改业务代码）。
- 真实模型权重放入本砖 models/weights/ 即生效：bge_small.onnx / sentiment.onnx / t5_rewrite.onnx。
  缺省（默认 mock 模式）全部走离线实现，零模型零下载即可运行。
"""
import os
import re
import math
import random
import hashlib

# 模型目录：本包内 engine/models/weights/（真实权重可放置于此，缺省走 mock）。
# 独立包自包含：不依赖外部项目（如 P.A.L.M 的 domain/memory/weights）。
MODEL_DIR = os.path.join(os.path.dirname(__file__), "models", "weights")
_OFFLINE_DIM = 4096  # 离线哈希向量维度
# 语义嵌入统一用 bge-m3（1024 维）；独立包内权重即放在本包 models/weights/。
_BGE_M3_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "models", "weights"))


# --------------------------------------------------------------------------
# 1) 语义嵌入：bge-m3（真实，1024 维，本地 ONNX） / 字 n-gram 哈希 TF-IDF（离线占位）
# --------------------------------------------------------------------------
class Embedder:
    """把文本编码为向量；真实路径用 bge-m3 ONNX，离线路径用哈希 TF-IDF。"""

    def __init__(self, model_dir=MODEL_DIR):
        self.model_dir = model_dir
        self._real = None
        self._tok = None
        self._idf = {}
        self._dim = _OFFLINE_DIM
        self.kind = "offline"
        self._load_attempted = False
        # WHY 惰性：运行时引擎用 engine.embed 模块，不经过这里；boot 即加载会
        # 与之重复占一份 ~600MB session（实测独立包化后 RSS +500MB）。仅
        # build_corpus 等离线工具首次调用 available()/encode() 时才真正加载。

    def _load_real(self):
        if self._load_attempted:
            return
        self._load_attempted = True
        # 统一 bge-m3（1024 维）：权重在本包 models/weights/
        onnx = os.path.join(_BGE_M3_DIR, "bge_m3.onnx")
        tok = os.path.join(_BGE_M3_DIR, "tokenizer.json")
        if os.path.exists(onnx) and os.path.exists(tok):
            try:
                import onnxruntime as ort  # 惰性导入，离线环境无需安装
                self._real = ort.InferenceSession(onnx)
                self._dim = 1024
                self.kind = "real"
            except Exception:
                self._real = None

    def available(self):
        self._load_real()
        return self._real is not None

    def fit_corpus(self, texts):
        """离线路径：在语料上估算 idf 供运行期复用（真实路径不需要）。"""
        df = {}
        for t in texts:
            for h in set(self._hash_vec(t).keys()):
                df[h] = df.get(h, 0) + 1
        n = max(1, len(texts))
        self._idf = {h: math.log((n - df[h] + 0.5) / (df[h] + 0.5) + 1) for h in df}

    def load_idf(self, idf_map, dim=None):
        # JSON 序列化会把 int 键变成 str，必须转回 int 才能与哈希维度对齐
        self._idf = {int(k): v for k, v in (idf_map or {}).items()}
        if dim:
            self._dim = dim

    def _hash_vec(self, text):
        # 用稳定哈希（md5），否则跨进程 hash() 随机化会导致构建/运行期维度错配
        text = re.sub(r"\s+", "", text)
        grams = [c for c in text] + [text[i:i + 2] for i in range(len(text) - 1)]
        vec = {}
        for g in grams:
            h = int(hashlib.md5(g.encode("utf-8")).hexdigest(), 16) % _OFFLINE_DIM
            vec[h] = vec.get(h, 0) + 1
        return vec

    def encode(self, texts):
        """返回 list[向量]；离线=稀疏 dict，真实=稠密 list。"""
        if self.available():
            return self._encode_real(texts)
        out = []
        for t in texts:
            vec = self._hash_vec(t)
            if self._idf:
                vec = {h: cnt * self._idf.get(h, 0.0) for h, cnt in vec.items()}
            norm = math.sqrt(sum(x * x for x in vec.values())) or 1.0
            out.append({h: x / norm for h, x in vec.items()})
        return out

    def _encode_real(self, texts):
        # 真实 bge-m3：权重在 domain/memory/weights（与向量记忆同源）。
        # 取 [CLS] 池化 + L2 归一化（bge 标准做法），输出 1024 维稠密向量。
        import numpy as np
        if self._tok is None:
            from tokenizers import Tokenizer
            self._tok = Tokenizer.from_file(
                os.path.join(_BGE_M3_DIR, "tokenizer.json"))
        encs = self._tok.encode_batch(texts, add_special_tokens=True)
        maxlen = min(max((len(e.ids) for e in encs), default=1), 8192)
        ids, masks = [], []
        for e in encs:
            seq = e.ids[:8192]
            ids.append(seq + [0] * (maxlen - len(seq)))
            masks.append([1] * len(seq) + [0] * (maxlen - len(seq)))
        inputs = {
            "input_ids": np.array(ids, dtype=np.int64),
            "attention_mask": np.array(masks, dtype=np.int64),
        }
        if any(i.name == "token_type_ids" for i in self._real.get_inputs()):
            inputs["token_type_ids"] = np.zeros_like(inputs["input_ids"])
        out = self._real.run(None, inputs)
        pooled = np.asarray(out[0])[:, 0, :]  # [CLS] 位置句向量
        norms = np.linalg.norm(pooled, axis=1, keepdims=True) + 1e-9
        return [(pooled[i] / norms[i]).tolist() for i in range(len(texts))]


# --------------------------------------------------------------------------
# 2) 情感分类：中文情感 tiny-BERT（真实） / 词典（离线占位）
# --------------------------------------------------------------------------
class Sentiment:
    """识别用户情绪 → 驱动回复语气（共情维度）。"""

    EMOTIONS = ["happy", "sad", "angry", "urgent", "calm"]
    LEXICON = {
        "happy": ["开心", "高兴", "快乐", "喜欢", "爱", "笑", "棒", "美", "中奖",
                  "及格", "发财", "生日", "可爱", "温柔", "缘分", "陪", "想你", "赢"],
        "sad": ["难过", "伤心", "哭", "累", "困", "失眠", "感冒", "心情不好", "想哭",
                "失恋", "病", "疼", "哑", "无聊", "孤单", "怕"],
        "angry": ["生气", "火大", "讨厌", "恼", "炸毛", "烦", "烂", "迟", "嫌弃"],
        "urgent": ["快", "急", "马上", "赶紧", "坏了", "雷", "虫", "蛇", "鬼", "救命"],
        "calm": ["睡", "晚安", "散步", "晴天", "音乐", "花", "牛奶", "看书", "海边"],
    }
    # 情绪 → 人格调味偏好（傲娇猫娘基调 + 情绪微调）
    TONE = {
        "happy": {"manner": ["眼睛发亮", "尾巴翘高", "笑嘻嘻"], "inner": ["和你一起才开心", "难得你也有趣"]},
        "sad": {"manner": ["放柔声调", "轻轻靠过来", "难得正经"], "inner": ["看你这样我不爽", "别怕有我在"]},
        "angry": {"manner": ["叉腰", "眯眼瞪你", "尾巴拍地"], "inner": ["气死我了", "你真烦"]},
        "urgent": {"manner": ["耳朵竖起", "干脆利落", "急晃尾巴"], "inner": ["快快快", "别磨蹭"]},
        "calm": {"manner": ["懒懒的", "眯眼", "歪头"], "inner": ["难得清静", "就这样挺好"]},
    }

    def __init__(self, model_dir=MODEL_DIR):
        self.model_dir = model_dir
        self._real = None
        self._tok = None
        onnx = os.path.join(self.model_dir, "sentiment.onnx")
        if os.path.exists(onnx):
            try:
                import onnxruntime as ort
                self._real = ort.InferenceSession(onnx)
            except Exception:
                self._real = None

    def available(self):
        return self._real is not None

    def classify(self, text):
        if self.available():
            return self._classify_real(text)
        # 离线词典版：与真实版对齐的优先逻辑（急迫 > 情绪词精准 > 中性兜底）
        if any(w in text for w in self.LEXICON["urgent"]):
            return "urgent", 1.0
        for e in ("sad", "angry", "calm", "happy"):
            if any(w in text for w in self.LEXICON[e]):
                return e, 1.0
        return "calm", 0.0

    def _classify_real(self, text):
        # 真实多语情感（Xenova/bert-base-multilingual-uncased-sentiment，5 类星级极性）
        # 作为模糊兜底；角色扮演情绪词用专用词典精准优先，避免短口语被极性模型误判。
        import numpy as np
        if self._tok is None:
            from tokenizers import Tokenizer
            self._tok = Tokenizer.from_file(os.path.join(self.model_dir, "sentiment_tokenizer.json"))
        # 1) 急迫维度模型无覆盖，关键词最高优先
        if any(w in text for w in self.LEXICON["urgent"]):
            return "urgent", 1.0
        # 2) 对话情绪词专用词典精准命中（happy/sad/angry/calm），命中即返回
        for e in ("happy", "sad", "angry", "calm"):
            if any(w in text for w in self.LEXICON[e]):
                return e, 1.0
        # 3) 模糊句：用模型星级极性兜底（正→happy / 中→calm / 负→sad）
        enc = self._tok.encode(text, add_special_tokens=True)
        seq = enc.ids[:512]
        inputs = {
            "input_ids": np.array([seq], dtype=np.int64),
            "attention_mask": np.array([[1] * len(seq)], dtype=np.int64),
        }
        if any(i.name == "token_type_ids" for i in self._real.get_inputs()):
            inputs["token_type_ids"] = np.zeros((1, len(seq)), dtype=np.int64)
        logits = np.asarray(self._real.run(None, inputs)[0][0])
        idx = int(np.argmax(logits))
        score = float(logits[idx])
        if idx >= 3:
            return "happy", score
        if idx == 2:
            return "calm", score
        # 负面极性兜底：有愤怒词归 angry，否则归 calm（中性问句不应误判 sad）
        return ("angry" if any(w in text for w in self.LEXICON["angry"]) else "calm"), score

    def tone_for(self, emotion):
        return self.TONE.get(emotion, self.TONE["calm"])


# --------------------------------------------------------------------------
# 3) 多样性改写：Randeng-T5-77M（真实） / 模板变体（离线占位）
# --------------------------------------------------------------------------
_REWRITE_OPENERS = ["[歪头]", "[尾巴轻晃]", "[戳了戳你]", "[猫耳抖了抖]", "[眯眼看你]", "[蹭过来]", "[托腮]"]
# WHY 不含"杂鱼"：随机尾缀加"杂鱼"会攻击性突兀（"谁欺负你了杂鱼"）。语癖堆叠
# 护栏：句尾已是任何语气词（嘛/呗/啦…）时不再追加，杜绝"嘛呀""喵呀"双粒子（实测）。
_REWRITE_TICS = ["喵", "呀", "呜", "哼"]
_REWRITE_TAIL_PARTICLES = tuple(_REWRITE_TICS) + ("嘛", "呗", "啦", "哦", "咯", "吧", "呢")


class Rewriter:
    """对选中骨架生成多个表面表达，轮换避免复读机（多样性维度）。"""

    def __init__(self, model_dir=MODEL_DIR):
        self.model_dir = model_dir
        self._real = None
        onnx = os.path.join(self.model_dir, "t5_rewrite.onnx")
        if os.path.exists(onnx):
            try:
                import onnxruntime as ort
                self._real = ort.InferenceSession(onnx)
            except Exception:
                self._real = None

    def available(self):
        return self._real is not None

    def rewrite(self, text, n=3):
        if self.available():
            return self._rewrite_real(text, n)
        return self._rewrite_offline(text, n)

    def _rewrite_offline(self, text, n):
        # WHY 保留四要素前缀：原实现用正则把「[动作]（神态）<内心>」整段剥掉，
        # 只重建 body + 通用 opener，导致最终回复丢失人格四要素（实测完整三要素率仅 0.107）。
        # 现改为：解析并保留前缀，仅对 body 做口癖/替词变体，结构性保持角色一致。
        m = re.match(r"^(\[[^\]]*\]\s*（[^）]*）\s*<[^>]*>\s*)(?P<body>.*)$", text, re.DOTALL)
        header = m.group(1) if m else ""
        body = (m.group("body") if m else text).strip()
        variants = [text]
        for i in range(1, n):
            v = body
            # WHY 摘尾括号再判：句尾"（心虚）"这类括号补语会挡住真实句尾，贴出
            # "（心虚）呀"（实测"吃……吃了吧，大概喵？（心虚）呀"）。摘出括号组后
            # 用主干判定，需要加口癖时插回括号之前。
            if i % 2 == 1:
                _trail = ""
                _m2 = re.search(r"（[^）]*）[\s]*$", v)
                if _m2:
                    _trail = v[_m2.start():]
                    v = v[:_m2.start()]
                if not v.rstrip("。！？～~…").endswith(_REWRITE_TAIL_PARTICLES):
                    v = v.rstrip("。！？") + random.choice(_REWRITE_TICS)
                v = v + _trail
            full = (header + v) if header else v
            if full != text and full not in variants:
                variants.append(full)
        return variants[:n]

    def _rewrite_real(self, text, n):
        raise NotImplementedError("请于 models/weights/ 放置 t5_rewrite.onnx 与 tokenizer.json")


class Hub:
    """三件套聚合，供引擎统一调用。缺省全部 offline（默认 mock 模式）。"""

    def __init__(self, model_dir=MODEL_DIR):
        self.embedder = Embedder(model_dir)
        self.sentiment = Sentiment(model_dir)
        self.rewriter = Rewriter(model_dir)

    def status(self):
        return {
            "embedder": self.embedder.kind,
            "sentiment": "real" if self.sentiment.available() else "offline",
            "rewriter": "real" if self.rewriter.available() else "offline",
        }

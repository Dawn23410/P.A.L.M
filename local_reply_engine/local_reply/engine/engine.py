# -*- coding: utf-8 -*-
"""对话缝合引擎 · 运行时（零联网，默认 mock 模式）。

流水线：情感调语气 → 检索召回 → 桥接缝合 → 人格四要素调味 → 多样性改写 → 短上下文回调。

两种检索后端：
- 默认 mock 模式：core.HybridRetriever（BM25 + 字 n-gram TF-IDF）内存索引，
  零模型、零预构建向量，开箱即用。这是砖的默认形态（<6ms/回复）。
- 可选语义升级：显式 semantic=True 且本机 bge-m3 ONNX 权重就位（默认引用
  P.A.L.M 的 weights/bge_m3.onnx，或本地 data/ 下）时，切换为 bge-m3 稠密语义检索
  （embed.py 封装，本地 ONNX 推理，~57ms/回复）。根治 lexical 近义串台（天气/洗手），
  语义分 < 0.72 时退化为 mock 混合检索保覆盖率。接口不变，缺失则静默退回 mock。
"""
import json
import os
import re
import random
import glob

from . import core
from .hub import Hub
from . import embed as _embed
from . import reranker
from . import compose as _compose

# reranker 仲裁阈值：v2-m3 用真实 paraphrase 正样本（T2/T3/T4 命中对，n=139）
# vs OOD top1 负样本（n=12）标定。logit -1.5 = 分离点：负样本 0 泄漏（max -1.84），
# 正样本保留 ~92%（p5=-2.13 之下的少数真命中宁可让兜底接）。sigmoid≈0.18。
RERANK_PROB_TH = 0.18

# 消融开关：①bands 分带置信（中带 margin 判别）②act_prior 行为先验阈值
# ③reranker cross-encoder 仲裁 ④coherence 上下文连贯性重排 ⑤norepeat 复读硬排除。
# 消融脚本逐个翻转，产品配置全开。
FEATURES = {"bands": True, "act_prior": True, "reranker": True,
            "coherence": True, "norepeat": True}

# 危机关键词：命中即走专用关怀池，不进检索/兜底链路（见 respond 内注释）。
_CRISIS_KEYWORDS = ["不想活了", "想死", "想消失", "活着没意思", "撑不下去了",
                    "自杀", "自残", "活不下去了", "想离开这个世界"]

# 裸应答 token：单字/双字应答（嗯/哦）语义分虚高易串台（嗯→打招呼、哦→谢谢），
# 走专用中性应答池，既不假命中也不甩兜底。
_BARE_ACK = {"嗯", "嗯嗯", "哦", "哦哦", "噢", "喔", "额", "诶", "噢噢"}

# 内容空泛的接话/求助句：与任何具体条目都"长得像"（泛求助语义虚高），
# 单独抬高接受门槛，防 mid-band 假阳性（实测"帮帮我"→补课、"然后呢"→降温）。
_VAGUE_QUERIES = {"帮帮我", "然后呢", "为什么", "怎么办", "安慰我", "救救我",
                  "然后", "后来呢", "讲讲", "说说", "陪我聊聊"}
_VAGUE_SEM_TH = 0.85   # 精确命中（≥0.95）畅通，虚高近似（0.72~0.83）挡下
_VAGUE_MOCK_TH = 0.80
from . import reason as _reason
from . import tools as _tools


def _cosine(a, b):
    # 稀疏 dict 余弦（离线哈希向量）
    inter = set(a) & set(b)
    return sum(a[k] * b[k] for k in inter)


# 识别置信度阈值（归一化分、长度无关，按检索后端取最优实测点）：
#   mock     (BM25 自匹配归一 + 字级余弦): 0.60 → 域内召回 0.714 / OOD 误命中 0.05
#   semantic-m3    (bge-m3 稠密余弦)     : 0.72 → 域内召回 0.929 / OOD 误命中 0%
#   semantic-small (bge-small-zh 稠密)   : 0.75 → 域内召回 0.987 / 真 OOD 误命中 0.033
#     （标定 n=230 域内 + 30 OOD，calibrate_small_v1.0 实测；"宇宙有多大"0.991 是
#      语料内知识条目真命中，不计误配）
# WHY 分档：各后端分值量纲不同（余弦分布 vs 归一化混合分），不可共用同一阈值。
_EMBED_SEMANTIC_THR = {"m3": 0.72, "small": 0.75}
CONFIDENCE_THRESHOLDS = {"mock": 0.60, "semantic": 0.72}
DEFAULT_CONFIDENCE = 0.60


class StitchEngine:
    # 三档产品化（2026-09-07）：
    #   full     满血档：bge-m3 语义 + reranker/连贯重排全开（默认，~2.7GB）
    #   balanced 性能档：bge-small 语义 + 重排全关（~160MB，多轮也不惰性加载）
    #   lite     节省档：纯 mock lexical（~32MB）
    # WHY FEATURES 必须在 balanced 下显式关闭：coherence/rerank 走惰性加载，
    # 不关的话多轮首触发会静默拉起 1700MB 的 v2-m3，159MB 承诺直接破产。
    _TIERS = {"full", "balanced", "lite"}

    def __init__(self, corpus_dir=None, data_dir=None, hub=None, use_jieba=False,
                 confidence_threshold=DEFAULT_CONFIDENCE, semantic=False, tier=None):
        # WHY use_jieba 默认 False（实测反直觉）：启用 jieba 词级分词后，中文虚词
        # （"的/怎么/什么/如何"）成为高 IDF 独立词，与语料产生虚假高分匹配，
        # 反使 OOD 判别显著恶化——同等域内召回 0.714 下，OOD 误命中由 0.05 升到
        # 0.45。字符级会把虚词拆成极高频单字（IDF 极低）而自然抑制，更鲁棒，
        # 且省去 jieba 依赖与约 1ms/回复 的分词开销。详见基准报告 v1.1。
        if tier is not None:
            if tier not in self._TIERS:
                raise ValueError(f"tier 必须是 {self._TIERS} 之一，收到 {tier!r}")
            if tier == "lite":
                semantic = False
            elif tier == "balanced":
                semantic = True
                os.environ["PALM_EMBED_MODEL"] = "small"
                FEATURES["reranker"] = False
                FEATURES["coherence"] = False
            else:  # full：m3 全功能，重排全开
                semantic = True
        here = os.path.dirname(__file__)
        self.corpus_dir = corpus_dir or os.path.join(here, "corpus")
        self.data_dir = data_dir or os.path.join(here, "data")
        self.hub = hub or Hub()
        self.use_jieba = use_jieba
        self.confidence_threshold = confidence_threshold
        self.semantic_requested = semantic
        self.records = []
        self.mode = "mock"
        self.vectors = None
        self._sem_index = None   # 稠密向量索引（bge-m3，1024 维），仅 semantic 模式填充
        self._sem_matrix = None  # 同上，numpy (N,1024) float32 视图，延迟构建、进程内复用
        self._sem_np = True      # numpy 是否可用；不可用时静默退回纯 Python 点积
        # 符号伪推理层（A 方向）：确定性 BeliefState（DST 变体）+ 规则化指代消解/
        # 实体注册/偏好抽取 + 产生式推理，fail-closed。作为结构化「世界模型」增强检索
        # （实体解析）与个性化，替代散落的同名/喜好字段。详见 reason.py。
        self.reasoner = _reason.PseudoReason()
        # 轻量工具调用层（零依赖、fail-closed）：时间/日期纯本地确定性；
        # 天气走 open-meteo 免费无密钥 API，网络失败诚实降级。结构化信息优先于检索缝合，
        # 避免「现在几点」被检索近似句替代而答非所问。详见 tools.py。
        self.tools = _tools.ToolRegistry()
        # 跨轮记忆：话题/情绪/好感/用户画像/近期回复，用于连续感、"活人感"与"记得你"。
        self.memory = {
            "turns": 0, "last_emotion": None, "affinity": 0, "topics": [],
            "queries": [], "user_profile": {"name": None, "facts": []},
            "recent_replies": [], "last_reply": None,
        }
        self._load()

    def _load(self):
        part_files = sorted(glob.glob(os.path.join(self.corpus_dir, "mengyao_hq_part*.jsonl")))
        self.records = core.load_persona_bank(part_files)
        if not self.records:
            raise FileNotFoundError(f"未找到手写语料：{self.corpus_dir}/mengyao_hq_part*.jsonl")
        if self.mode == "mock":
            self.retriever = core.HybridRetriever(self.records, self.use_jieba)
        # 可选语义升级（P1）：bge-m3 本地 ONNX 稠密检索，根治 lexical 近义误配。
        # 仅当显式 semantic=True 且本机 embed 可用时启用；否则静默退回 mock（零模型离线）。
        # 稠密向量一次性构建并落盘缓存（data/stitching_vectors_bgem3.json），后续启动秒级加载。
        if self.semantic_requested and _embed.is_available():
            self._build_semantic_index()
        elif self.semantic_requested and not _embed.is_available():
            # 显式要语义但本机无权重/依赖：保持 mock，避免静默假升级。
            self.semantic_requested = False
        # reranker 启动预热：仅语义模式且重排功能开启时需要（mock 流程不触达
        # cross-encoder，实测无条件预热让纯 mock 档白占 1734MB；balanced 档
        # FEATURES 已关，预热会把 1700MB 拉回来）。惰性加载会在连贯性重排
        # 首触发时打出 3.5s 尖峰，语义满血模式仍保留启动期预热换对话中途零冷启动。
        if self.mode == "semantic" and (FEATURES.get("reranker") or FEATURES.get("coherence")):
            reranker.warmup()
        # 语义模式用标定阈值 0.72（域内召回 0.929 + OOD 误命中 0% 的最优点）；
        # 放在 _load 而非 _build_semantic_index 内，确保「缓存命中 / 首次构建」两路径都覆盖。
        # 仅当用户未显式传 custom 阈值时覆盖，保留自定义能力。
        if self.mode == "semantic" and self.confidence_threshold == DEFAULT_CONFIDENCE:
            self.confidence_threshold = _EMBED_SEMANTIC_THR.get(
                _embed.model_tag(), CONFIDENCE_THRESHOLDS.get("semantic", 0.72))

    def _corpus_fp(self) -> str:
        """语料指纹：对所有 part 文件 (名, 大小) 求稳哈希。

        语料变更（增删/改文件）即变化；用于把语义向量缓存按语料隔离，
        避免「换了语料但条数恰好相同」时误用旧缓存错位回复。
        """
        import hashlib
        h = hashlib.sha256()
        for f in sorted(glob.glob(os.path.join(self.corpus_dir, "mengyao_hq_part*.jsonl"))):
            try:
                h.update(os.path.basename(f).encode("utf-8"))
                h.update(str(os.path.getsize(f)).encode("utf-8"))
            except OSError:
                pass
        return h.hexdigest()[:8]

    # ── 语义检索（稠密，模型由 PALM_EMBED_MODEL 选择）──
    def _build_semantic_index(self):
        tag = _embed.model_tag()
        fp = self._corpus_fp()
        cache_npy = os.path.join(self.data_dir, f"stitching_vectors_{tag}_{fp}.npy")
        cache_json = os.path.join(self.data_dir, f"stitching_vectors_{tag}_{fp}.json")
        legacy_npy = os.path.join(self.data_dir, f"stitching_vectors_{tag}.npy")
        # 0) 无指纹名缓存但存在旧版（无指纹）npy：条数匹配则重命名为指纹名复用，
        #    避免每次换引擎实例都重算 2837 条向量（约 20s + 内存尖峰）。
        if not os.path.exists(cache_npy) and os.path.exists(legacy_npy):
            try:
                import numpy as _np
                if len(_np.load(legacy_npy)) == len(self.records):
                    os.replace(legacy_npy, cache_npy)
            except Exception:
                pass
        # 1) npy 快路径：二进制加载（指纹匹配；万级语料下 JSON 解析会拖慢启动十几秒）
        try:
            if os.path.exists(cache_npy):
                import numpy as _np
                vecs = _np.load(cache_npy).tolist()
                if isinstance(vecs, list) and len(vecs) == len(self.records):
                    self._sem_index = vecs
                    self.mode = "semantic"
                    return
        except Exception:
            pass
        # 2) 旧 JSON 兼容（指纹名）：存在且数量匹配则迁移为 npy（一次性）
        try:
            if os.path.exists(cache_json) and not os.path.exists(cache_npy):
                with open(cache_json, encoding="utf-8") as fh:
                    vecs = json.load(fh)
                if isinstance(vecs, list) and len(vecs) == len(self.records):
                    self._sem_index = vecs
                    self.mode = "semantic"
                    try:
                        import numpy as _np
                        _np.save(cache_npy, _np.asarray(vecs, dtype=_np.float32))
                    except Exception:
                        pass  # 迁移失败不影响本次运行，下次仍走 JSON
                    return
        except Exception:
            pass
        # 3) 首次构建：批量嵌入全部记录的触发问句 q（用户查询与之匹配）。
        # WHY 分块：一次性 2707 条整批会把 ORT arena 一次性顶到 GB 级且不归还
        # （实测 warm RSS 3615MB vs 分块后 ~2GB），256 条/块内存有界、耗时持平。
        qs = [r.get("q", "") for r in self.records]
        vecs = []
        try:
            for i in range(0, len(qs), 256):
                vecs.extend(_embed.embed(qs[i:i + 256]) or [])
        except Exception:
            vecs = None
        if not vecs or len(vecs) != len(self.records):
            self.semantic_requested = False
            return
        try:
            os.makedirs(self.data_dir, exist_ok=True)
            import numpy as _np
            _np.save(cache_npy, _np.asarray(vecs, dtype=_np.float32))
            if os.path.exists(cache_json):
                try:
                    os.remove(cache_json)  # 已迁移，避免双缓存不一致
                except Exception:
                    pass
        except Exception:
            pass
        self._sem_index = vecs
        self.mode = "semantic"

    def _sem_search(self, query, top_k=3):
        qv = _embed.embed([query])
        if not qv:
            return []
        qv = qv[0]
        # 性能热点：733×1024 的余弦若走纯 Python 循环约 30ms（实测占单次响应 66%）。
        # numpy 矩阵点积可压到亚毫秒，且向量已 L2 归一化故点积即余弦，数值等价。
        # numpy 缺失或形状异常时静默退回纯 Python，保证零依赖场景不崩。
        if self._sem_np:
            mat = self._sem_matrix
            try:
                if mat is None:
                    import numpy as _np
                    mat = _np.asarray(self._sem_index, dtype=_np.float32)
                    self._sem_matrix = mat
                import numpy as _np
                scores = mat @ _np.asarray(qv, dtype=_np.float32)
                k = min(top_k, scores.shape[0])
                idx = _np.argpartition(-scores, k - 1)[:k]
                idx = idx[_np.argsort(-scores[idx])]
                return [(int(i), float(scores[i])) for i in idx]
            except Exception:
                self._sem_np = False
        scored = [(i, _embed.cosine(qv, v)) for i, v in enumerate(self._sem_index)]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    # ── 检索 ──
    def retrieve(self, query, top_k=3):
        if self._sem_index is not None:
            return self._sem_search(query, top_k)
        # HybridRetriever.search 返回 (idx, 混合分, 词级分, 字级分)，归一为 (idx, 分)。
        return [(i, mixed) for (i, mixed, _, _) in self.retriever.search(query, top_k)]

    def _retrieve_scored(self, query):
        """统一检索接口，返回 [(idx, 归一置信分)]（已按来源阈值过滤，空表=未过门）。

        语义模式路由：主用 bge-m3 稠密检索（根治 lexical 近义串台：天气/洗手），
        仅当语义 top1 低于标定阈值（0.72）时，退化到 mock 混合检索并用 **mock 阈值
        (0.60)** 判接受——挽救「亲昵」等语义分偏低但字面可救的域内表述（如 爱你哟→
        爱你）。两阈值尺度不同，故每次检索记录 self._last_thr（该结果应判的阈值）与
        self._last_retrieval_mock，供 respond 动态切换接受阈值。OOD 仍被
        looks_ood_knowledge 前置护栏 + mock 阈值挡在门外（mock 单独路径 OOD 误命中
        已实测 0%），不会因退化而泄漏。
        """
        self._last_retrieval_mock = False
        self._band_ambiguous = None  # 每次检索重置，避免上一轮残留仲裁旧句
        if self._sem_index is not None:
            # act 先验差异化阈值（WHY：question 硬答即幻觉，宁交 LLM；empathy 的
            # 价值在接住情绪而非答对，可放宽）。complaint/compliment 等用基线。
            act = core.classify_act(query)
            sem_thr = _EMBED_SEMANTIC_THR.get(
                _embed.model_tag(), CONFIDENCE_THRESHOLDS.get("semantic", 0.72))
            if FEATURES.get("act_prior", True):
                if act == "question":
                    sem_thr += 0.04
                elif act == "empathy_needed":
                    sem_thr -= 0.04
            # 空泛接话/求助句单独抬门槛（见 _VAGUE_QUERIES）：精确命中≥0.95 畅通，
            # 虚高近似 0.72~0.83 挡下走共情兜底，不再硬接补课/降温这类错答。
            if query.strip() in _VAGUE_QUERIES:
                sem_thr = max(sem_thr, _VAGUE_SEM_TH)
            sem = self._sem_search(query, 8)  # top-8：给多样性池/连贯重排留候选面
            if sem and sem[0][1] >= sem_thr:
                # 分带置信：高带（≥0.80）直接用；中带（阈值~0.80）须 top1-top2
                # 分差 ≥0.03（榜首明确领先）才接受——中带一刀切是「帮帮我」类
                # 假阳性的共同根源。分差不足 → 标记存疑，reranker 仲裁（若可用），
                # 仲裁不过则走 mock 二次机会/兜底。
                if not FEATURES.get("bands", True):
                    self._last_thr = sem_thr
                    return sem
                margin = sem[0][1] - sem[1][1] if len(sem) > 1 else 1.0
                # 同回复变体（query 增广共享 a_raw）：top1/top2 分差小是假存疑，
                # 反正落到的都是同一条回复，直接接受，不进 reranker。
                if (len(sem) > 1 and self.records[sem[0][0]].get("a_raw")
                        == self.records[sem[1][0]].get("a_raw")):
                    margin = 1.0
                if sem[0][1] >= 0.80 or margin >= 0.03:
                    self._last_thr = sem_thr
                    return sem
                self._band_ambiguous = (sem, sem_thr)  # 存疑带，respond 末段仲裁
            # 语义未达标 → 退化 mock（其 respond 内还有 normalize_synonyms 二次机会）
            mock_thr = CONFIDENCE_THRESHOLDS.get("mock", 0.60)
            if query.strip() in _VAGUE_QUERIES:
                mock_thr = max(mock_thr, _VAGUE_MOCK_TH)
            mock = [(i, m) for i, m, _bm, _gr, _margin in self.retriever.search_normalized(query, 8)]
            if mock and mock[0][1] >= mock_thr:
                self._last_retrieval_mock = True
                self._last_thr = mock_thr
                return mock
            self._last_thr = mock_thr
            return []
        if self.mode == "semantic" and self.vectors is not None:
            self._last_thr = CONFIDENCE_THRESHOLDS.get("semantic", 0.72)
            return self.retrieve(query, 3)
        self._last_thr = CONFIDENCE_THRESHOLDS.get("mock", 0.60)
        return [(i, m) for i, m, _bm, _gr, _margin in self.retriever.search_normalized(query, 3)]

    def _accept_thr(self):
        """当前（最近一次）检索结果应判的接受阈值。"""
        return getattr(self, "_last_thr",
                       self.confidence_threshold or CONFIDENCE_THRESHOLDS.get(self.mode, DEFAULT_CONFIDENCE))

    # ── 主入口 ──
    def respond(self, query, history=None):
        history = history or []
        self._nn_spent = False  # 每轮重置神经预算记账
        # 超长输入截断保险：聊天场景单句极少 >60 字，极长输入（粘贴/攻击）截断头部
        # 处理，避免 BM25 对超长串的异常匹配；保留头部意图通常足够。
        if len(query) > 60:
            query = query[:60]
        emotion, _ = self.hub.sentiment.classify(query)
        tone = self.hub.sentiment.tone_for(emotion)
        # 对话行为（L2 策略）上移：供下方"共情第三检索机会"判定是否放宽阈值。
        act = core.classify_act(query, emotion)
        # 连续负面情绪递进计数：sad 累加、其余清零。供 _policy_suffix 在 streak>=2
        # 时切换递进池（追问/转移/陪伴沉默），避免连续同句安慰单调（轮3 杠点）。
        if emotion == "sad":
            self.memory["sad_streak"] = self.memory.get("sad_streak", 0) + 1
        else:
            self.memory["sad_streak"] = 0
        # 符号伪推理层：用本句查询更新结构化信念（实体注册/偏好抽取/情绪 streak）。
        # fail-closed：无抽取结果时为空操作；绝不编造。last_entity 供本轮 resolve 指代消解
        # （用的是**上一轮**留下的锚点，正确）。名字同步进既有 memory，使 _recall_name/
        # _intro_ack 自动受益，不重复造状态。
        self.reasoner.update(query, emotion)
        self.memory["user_profile"]["name"] = self.reasoner.belief.profile["name"]
        # 画像抽取无条件执行：即使用户自述落在 OOD/兜底路径（如"我叫小梦"），
        # 披露信息也要被记住，否则"记得你"的个性化无从触发。
        self._update_profile(query)
        # 识别判定：①质量门 → ②归一化置信度阈值（原实现用 1.05 相对比 + 0.02
        # 绝对地板，二者均与查询长度耦合，导致域内外分数完全重叠、无法分离）。
        # main_thr：首检结果的接受阈值（语义成功=0.72 / 退化 mock=0.60），供主门、
        # 天气碰撞、共情放宽使用；二次机会的再检索各自用 self._accept_thr() 判。
        if not core.has_signal(query):
            return self._fallback(emotion, tone, query, [], 0.0)
        # 危机路由（最高优先）：自伤/轻生表述不进检索/兜底链路，走专用关怀池。
        # WHY："我不想活了" 实测 act=casual——sad/empathy 词库接不住极端表述，
        # 而这类输入交给检索或普通安慰都是产品级风险，必须最先截住。
        if any(k in query for k in _CRISIS_KEYWORDS):
            return self._crisis_reply(emotion, tone)
        # 裸应答 token（嗯/哦）：语义分虚高必串台（实测 嗯→打招呼、哦→谢谢），
        # 走中性应答池——比假命中和"去问LLM"兜底都更像真人反应。
        if query.strip() in _BARE_ACK:
            return self._bare_ack(emotion, tone)
        # 刷屏/重复拼接护栏：检测「你你你…」「今天天气真好呀×4」等，轻量俏皮回应
        # 而非照常命中（杠精实测重复拼接会借 n-gram 叠加命中原条目）。保守判定，
        # 正常长句不被误伤。
        if core.is_repetitive(query):
            return self._spam_ack(emotion, tone)
        # 无中文护栏（防拉丁/数字乱码被 BM25 伪高分接住）：纯拉丁/数字/符号查询
        # 视为陪伴域外，除非与语料某问句精确相等（大小写不敏感）才放行，否则诚实兜底。
        # 中文域内语料不会被此门挡住；仅拦截 'asdf qwer zxcv 123' 这类噪声。
        if not core.has_cjk(query) and query.lower() not in {r.get("q", "").lower() for r in self.records}:
            return self._fallback(emotion, tone, query, [], 0.0)
        # 工具分发（优先于检索缝合）：时间/日期/天气这类结构化信息，检索语料里没有真实
        # 答案，必须由工具精确给出。命中即返回，绝不落入检索近似或 OOD 兜底。
        # fail-closed：天气网络失败 → 工具返回 ok=False，_tool_reply 转诚实降级文案。
        dispatched = self.tools.dispatch(query)
        if dispatched is not None:
            result, tool = dispatched
            return self._tool_reply(result, tool, query, emotion, tone)
        # 算式/计算意图（有界）：检索引擎没有计算器，硬接只会像"帮帮我"那样
        # 假命中。诚实引导 LLM（人格内话术，suggest_llm=True）。
        if core.looks_math(query):
            return self._math_reply(emotion, tone)
        if core.looks_ood_knowledge(query):
            # 知识/事实/推荐类意图：诚实降级交 LLM，避免被「看电影」等闲聊条目 lexical 误配。
            # 例外：语义模式下若语料有近精确覆盖（≥0.90，如"推荐个电影"有专门记录），
            # 放行走正常检索链路——OOD 标记只为防误配，不该压制真实覆盖的域内问法。
            _k_scored = self._retrieve_scored(query)
            if self.mode != "semantic" or not (_k_scored and _k_scored[0][1] >= 0.90):
                return self._fallback(emotion, tone, query, [], 0.0)
        scored = self._retrieve_scored(query)
        confidence = scored[0][1] if scored else 0.0
        # 符号伪推理层：指代消解增强检索（fail-closed）。若本句含代词且信念里有最近实体
        # 锚点（如上一轮「它叫咪咪」→ last_entity=咪咪），把「它呢」消解为「咪咪呢」后
        # 再检索——比碎片拼接更确定、可调试。仅当消解版检索分 ≥ 接受阈值 且 高于原始
        # 才采纳；否则保持原始/诚实兜底，绝不硬解或编造实体。
        resq = self.reasoner.resolve(query)
        if resq != query:
            r_scored = self._retrieve_scored(resq)
            r_conf = r_scored[0][1] if r_scored else 0.0
            if r_scored and r_conf >= self._accept_thr() and r_conf > confidence:
                scored, confidence = r_scored, r_conf
        main_thr = self._accept_thr()  # 首检接受阈值（语义=0.72 / 退化 mock=0.60）
        # 上下文接续（8B 强项：连贯）：仅对**弱指代碎片**（is_fragment：它呢/这个怎么办
        # 等孤立近乎无分的省略代词）借上下文补检索。修复串台：① 不再只拼紧邻上一句
        # （可能已切走话题），而是在近期 queries[-3:] 逐个拼合并取最高分者，让「它呢」
        # 能正确借到「它叫咪咪」那句；② 代词孤立无语义，故强制尝试续接（即便原始
        # 检索有分也先借上下文，避免「呢」字 n-gram 噪声把代词错配到无关记录），
        # 但拼接后分须 ≥ 主阈值 且 显著高于原始(+0.1) 才采纳，否则保持原始检索/
        # 诚实兜底，避免错误拼接强拽到无关条目。明确实义短句（考试又没过/今天好累）
        # 因 is_fragment=False 根本不进此分支，不会被上文覆盖。
        if core.is_fragment(query) and self.memory.get("queries"):
            best_aug, best_conf, best_aug_thr = None, 0.0, 0.0
            for prev in self.memory["queries"][-3:]:
                aug = prev + query
                aug_scored = self._retrieve_scored(aug)
                aug_conf = aug_scored[0][1] if aug_scored else 0.0
                aug_thr = self._accept_thr()  # 该 aug 检索应判阈值（退化则为 mock 0.60）
                if aug_conf > best_conf:
                    best_conf, best_aug, best_aug_thr = aug_conf, aug_scored, aug_thr
            if best_aug and best_conf >= best_aug_thr and best_conf >= confidence + 0.1:
                scored, confidence = best_aug, best_conf
        # 第二检索机会：近义归一 + 去填充词轻量兜底，仅首检未过时触发。优先用
        # normalize_synonyms 把近义表述（"我困了"→"今天好困没精神"）归一到语料
        # 代表表述提升命中；再用 strip_filler 去填充词（"今天好累啊"→"好累"）。
        # 知识类 OOD 已被 looks_ood_knowledge 截住，不会误伤。再检索各自用
        # self._accept_thr() 判（退化 mock 结果按 0.60 接受）。
        if confidence < main_thr:
            for attempt in {core.normalize_synonyms(query), core.strip_filler(query)}:
                if attempt and attempt != query:
                    s2 = self._retrieve_scored(attempt)
                    c2 = s2[0][1] if s2 else 0.0
                    if c2 >= self._accept_thr():
                        scored, confidence = s2, c2
                        break
        # 第三检索机会（有界）：负向生活事件（考试/失败/分手…）常因额外描述词稀释
        # 匹配分，略低于主阈值；仅对 empathy_needed 行为放宽到 0.45 并接受其 top1，
        # 让其"接住情绪"而非一刀切兜底。知识 OOD 已被 looks_ood_knowledge 截死，
        # 不会泄漏到事实/推荐类问题；放宽仅作用于负向陪伴语境。
        # 天气碰撞护栏：top 命中天气条目但用户并非问天气（如「你人真好」误碰「天气真好」），
        # 仅闲聊近义误配——在同分候选里找一个非天气条目接手；找不到且查询像纯夸人
        # → 诚实兜底，不吐天气错答。知识类 OOD 已由 looks_ood_knowledge 提前截死。
        if scored and core.rec_is_weather(self.records[scored[0][0]]) and not core.looks_weather(query):
            alt = [(i, c) for i, c in scored if not core.rec_is_weather(self.records[i]) and c >= main_thr]
            if alt:
                best_i, best_c = alt[0]
                scored = [(best_i, best_c)] + [(i, c) for i, c in scored if i != best_i]
                confidence = best_c
            elif core.looks_praise(query):
                scored, confidence = [], 0.0
        # 进行时事件句护栏（有界）：结果未明（"我今天面试了"）时拒绝预设结局的
        # 庆祝/哀悼记录（实测 mid-band 随机命中"录取啦！牛炸了"），在同分候选里
        # 找中性打气条目接手；找不到 → 诚实兜底（结果该由用户说，不该我猜）。
        if scored and core.event_pending(query) and core.presumes_result(self.records[scored[0][0]]):
            alt = [(i, c) for i, c in scored
                   if not core.presumes_result(self.records[i]) and c >= main_thr]
            if alt:
                best_i, best_c = alt[0]
                scored = [(best_i, best_c)] + [(i, c) for i, c in scored if i != best_i]
                confidence = best_c
            else:
                scored, confidence = [], 0.0
        # 第三检索机会（有界）：负向生活事件（考试/失败/分手…）常因额外描述词稀释
        # 匹配分，略低于主阈值；仅对 empathy_needed 行为放宽到 0.45，且**仅当放宽命中的
        # 记录本身是安慰型回应**才接住（is_comfort_record 含陪你/抱抱等抚慰词），否则
        # （如「分手」误碰「洗手」）诚实兜底，避免答非所问。知识 OOD 已截死，不泄漏。
        accepted = False
        if confidence < main_thr and act == "empathy_needed" and scored and scored[0][1] >= 0.45:
            if core.is_comfort_record(self.records[scored[0][0]]):
                accepted = True
        # 画像回查（有界）：用户回查自己的名字且已存 → 从记忆应答，不兜底。
        # WHY 顺序：必须先于 _intro_ack——"你记得我叫什么吗"含"我叫"，若让
        # intro 先跑会把"什么吗"抽成新名字（实测污染）。回查意图优先级更高。
        recall = self._recall_name(query, emotion, tone)
        if recall is not None:
            return recall
        # 自我介绍接话（有界）：抽取到 name/identity 但语料无对应回复时，给一个
        # "记住了"的接话而非一刀切兜底。仅当查询像自我介绍且抽到名字/身份才触发；
        # 知识 OOD 已被前置 looks_ood_knowledge 截死，不会泄漏到这里。
        intro = self._intro_ack(query, emotion, tone)
        if intro is not None:
            return intro
        # 上轮回放（有界）：用户问「刚才说了什么」且已有上轮回复 → 真实回放，不兜底。
        recall = self._recall_last(query, emotion, tone)
        if recall is not None:
            return recall
        # reranker 仲裁（有界）：仅当①首检落在中带但分差不足（存疑），②二次/三次
        # 机会都没救回来时触发。cross-encoder 对 (query, q) 交互打分，专治双塔
        # "各说各话再对答案"的毫厘之差。prob ≥ 标定阈值才接受，fail-closed（模型
        # 不可用/异常 → 保持原判定走兜底）。只花在存疑带，高带直通、低带早退。
        if (FEATURES.get("reranker", True)
                and confidence < main_thr and not accepted and self._band_ambiguous):
            amb_sem, amb_thr = self._band_ambiguous
            if amb_sem and amb_sem[0][1] >= amb_thr:
                self._rerank_calls = getattr(self, "_rerank_calls", 0) + 1  # 消融观测
                self._nn_spent = True  # 神经预算记账：本轮已花，连贯性让位
                deep = self._sem_search(query, 5)  # 5 对已够仲裁，8 对会顶到 ~600ms
                cands = [(i, s, self.records[i].get("q", "")) for i, s in deep]
                rr = reranker.rerank(query, cands, max_len=96)
                if rr and rr[0][1] >= RERANK_PROB_TH:
                    ri, rp = rr[0]
                    scored = [(ri, max(amb_sem[0][1], 0.0))]
                    confidence = amb_sem[0][1]
                    accepted = True
        if not scored or (confidence < main_thr and not accepted):
            return self._fallback(emotion, tone, query, scored, confidence)
        # L1 重排：在已通过置信门（OOD 已被挡在门外）的 top-K 内，用 belief-state
        # （用户画像/近期话题/去重）做二次重排，挑"最对味"的，避免千篇一律。
        ranked = self._rerank(scored[:8], query, emotion, self.memory["affinity"])
        # 同回复变体去重（query 增广共享 a_raw）：top-8 常被同一回复的多个变体
        # 挤占，不去重则「多样性池」和连贯性重排都在空转变体。每回复留最高分。
        seen, distinct = set(), []
        for idx, conf in ranked:
            r = self.records[idx].get("a_raw")
            if r not in seen:
                seen.add(r)
                distinct.append((idx, conf))
        ranked = distinct
        # L1.5 连贯性重排（有界）：仅多轮（有上文）且候选回复互不相同才触发。
        # cross-encoder 对 (近2轮上文+query, 回复正文) 交互打分，治「检索只看
        # 本句、回复接不上上文」的拟人感缺口。≤5 对去重候选 ≈110ms，400ms 内。
        ranked, coh = self._coherence_rerank(ranked, query)
        top = [self.records[i] for i, _ in ranked]
        # 真·多样 + 防翻车：在重排结果里，仅当某候选得分接近榜首（≥榜首-0.10，
        # 属同一意图簇）才纳入随机择一；远落后的近义误配（如「分手」误碰「洗手」）
        # 因分差大被排除，不会被随机抽到。同意图多条回复 → 骨架真正多样且连贯。
        best = ranked[0][1]
        # 相对窗（best-0.10）∪ 绝对地板 0.75：精确命中（best≈0.98）时相对窗会
        # 把同意图的其他回复全卡死（复读根源），取并集保住同簇候选面，交给
        # 连贯性重排 + 复读排除挑选。下限 0.65 防 empathy 放宽时误配涌入。
        floor = max(min(best - 0.10, 0.75), 0.65)
        # 近精确命中（best≥0.90）收紧为纯相对窗：绝对地板 0.75 会把 0.75~0.85 的
        # 远意图条目拉进随机池（实测"帮帮我"精确命中 0.99 后 1/3 概率随机抽到
        # 打招呼记录）。同 q 多份变体与 compose 模板分数≈best，不受收紧影响，
        # 多样性由同簇轮转承担，正确性优先。
        cands = [0] + [k for k in range(1, min(6, len(ranked))) if ranked[k][1] >= floor]
        # 档位判定用 raw 分（scored 原始相似度）：ranked 的分带复读惩罚/话题加成，
        # 近精确命中被罚 0.06 后会跌破 0.95 档导致窗口重新打开（实测"我感冒好了"
        # 二连问，0.9863→0.9363 放进 0.89 的病中邻簇）。
        raw_best = scored[0][1] if scored else best
        if raw_best >= 0.95:
            # 近精确档：池只留同意图变体（raw-0.05）。窗太小(0.02)会把不开心簇的
            # 0.93 同类邻句也关死（多样性回退），太大(0.10)会放进 gap 0.10 的
            # 跨意图邻居（"我感冒好了"放进"我感冒了"病中语气）。0.05 是实测平衡点。
            floor = max(floor, raw_best - 0.05)
            cands = [0] + [k for k in range(1, min(6, len(ranked)))
                           if max(ranked[k][1], raw_best - 0.06) >= raw_best - 0.05]
        elif raw_best >= 0.90:
            floor = max(floor, raw_best - 0.10)
        # 晨晚单向守卫：寒暄/道别意图下，把跨时段反向问候挡出随机池。
        # WHY：floor 0.75 会带出同簇邻居（实测"晚安"以 ~0.84 相似度抽到
        # "早安……你起得好早"，时间错位一眼假）。榜首永不剔除（相似度最高者
        # 必是同时段），只清洗 k>=1 的候选。
        if act in ("greeting", "farewell"):
            _m = any(w in query for w in ("早安", "早上好", "早啊"))
            _n = any(w in query for w in ("晚安", "晚上好"))
            if _m != _n:
                _bad = ("早安", "早上好") if _n else ("晚安", "晚上好")
                cands = [0] + [k for k in cands[1:]
                               if not any(w in (top[k].get("a_raw") or "") for w in _bad)]
        #  wet 守卫：鞋/袜/衣湿是"衣物淋湿"，别把"空气潮湿开窗除湿"簇拉进池
        #（实测"袜子湿了"以同簇分数抽到"大？猫娘开窗，别潮喵"）。
        if ("湿" in query and any(w in query for w in ("鞋", "袜", "衣服", "衣裳", "袖"))):
            cands = [0] + [k for k in cands[1:]
                           if not any(w in (top[k].get("a_raw") or "") for w in ("开窗", "通风", "除湿"))]
        # 开黑守卫：'晚上开黑' 语义上'晚上'+'黑'撞车'怕黑/夜聊'，rank0 也可能
        # 被占（实测"晚上开黑吗"榜首是'怕黑'记录）。允许剔首，全空则保留原池。
        if "开黑" in query:
            def _is_kaihei(rec):
                return any("开黑" in (rec.get(f) or "") for f in ("a_raw", "q", "body"))
            alive = [k for k in cands if _is_kaihei(top[k])]
            if alive:
                cands = alive
        # 穿搭守卫：'今天穿什么'（求建议）与'你今天穿的什么'（反问自述）同簇，
        # 求建议问句别抽到自述回复（实测 1/3 概率答非所问）。
        if ("穿什么" in query or "搭配" in query) and not query.startswith("你"):
            alive = [k for k in cands if "今天穿的" not in (top[k].get("a_raw") or "")]
            if alive:
                cands = alive
        # 冰雹守卫：'下冰雹' 与 '下雪' 语义邻居（都是天空掉落物），rank0 可能被
        # 雪簇占（实测"天上掉冰雹了"抽到"雪！猫娘陪你踩，堆小雪喵～"）。含雪但
        # 不含冰雹的候选剔除，允许剔首，全空保留原池（宁可雪也别 fallback）。
        if "冰雹" in query:
            def _is_hail(rec):
                _t = (rec.get("a_raw") or "") + (rec.get("q") or "") + (rec.get("body") or "")
                return "冰雹" in _t or ("雪" not in _t and "雨" not in _t)
            alive = [k for k in cands if _is_hail(top[k])]
            if alive:
                cands = alive
        # 复读硬排除（有界）：候选池里剔除最近 8 轮用过的回复；仅当剔除后仍有
        # 存活候选才生效（全用过则保持原池，宁可复读不可空转）。
        # WHY 在守卫之后：norepeat 会把真语料踢出池（同问 8 连后开黑记录进 recent），
        # 剩下的全是错配近邻——先守卫锁域，再在域内做去重。
        if FEATURES.get("norepeat", True) and len(cands) > 1:
            recent = set(self.memory.get("recent_replies", []))
            # k==0 永不剔除：榜首是近精确命中（≥0.90 场景）时，唯一正确回复被
            # recent 剔掉会放错配近邻进池（实测"我搬新家了"二连问抽到"想搬出去住"）。
            # 宁可正确地重复，不可错误地新鲜。
            fresh = [k for k in cands if k == 0 or top[k].get("a_raw") not in recent]
            if fresh:
                cands = fresh
        # 连贯重排收益回收（小改）：重排触发时榜首是 cross-encoder 认定的最连贯
        # 候选，若继续均匀 random.choice，~150ms 的重排收益被稀释成随机水位
        # （bench_ctx_v3.7 实证 on_topic 近锚≈远锚≈首句）。改为 70% 概率直接采纳
        # 榜首、30% 保留随机惊喜；榜首被复读排除剔除时退回均匀选择。
        if coh and 0 in cands and random.random() < 0.7:
            chosen_k = 0
        else:
            chosen_k = random.choice(cands)
        base = top[chosen_k]
        src = base.get("a_raw") or base.get("body") or ""
        # 槽位组合注入（关键词注入）：模板记录含 {选项|权重;...} 槽位组与 <你>
        # 记忆变量 → 按上下文加权采样展开。组合数≈64/模板，随机化池的乘法放大器；
        # 非模板记录原样走老链路，零影响。
        if "{" in src and "}" in src:
            _cctx = {
                "name": (self.memory.get("user_profile") or {}).get("name"),
                "emotion": emotion,
                "recent": set(self.memory.get("compose_recent", [])),
            }
            filled = _compose.fill(src, _cctx)
            if filled:
                src = filled
                self.memory["compose_recent"] = (self.memory.get("compose_recent", []) + [filled])[-6:]
        bridge = self._pick_bridge(top, query, src)
        # L2/L4：对话行为驱动共情/夸赞语气后缀 + L3 用户画像个性化召回（均追加于
        # 四要素之后，绝不动前缀，保证人格一致与人设锁不被破坏）。
        suffix = self._policy_suffix(act, emotion) + self._personalize(query)
        text = self._diversify(src + bridge + suffix)
        variants = self.hub.rewriter.rewrite(text, n=3)
        pick = random.choice(variants)  # 真随机选变体，避免同问恒同答
        reply = self._callback(pick, query)
        self._update_memory(query, emotion, top)
        self.memory["recent_replies"].append(base.get("a_raw"))
        self.memory["recent_replies"] = self.memory["recent_replies"][-8:]
        self.memory["last_reply"] = reply
        return {
            "reply": reply,
            "emotion": emotion,
            "act": act,
            "tone_manner": random.choice(tone["manner"]),
            "matches": [(self.records[i]["q"], round(s, 4)) for i, s in scored],
            "rewrite_variants": variants,
            "mode": self.mode,
            "confidence": round(confidence, 4),
            "recall_real": True,
            "recognized": True,
            "suggest_llm": False,
            # 诊断字段：随机化池是否真被用上。base_a_raw=本轮选中基句，
            # pool_size=进入随机择一的近意图候选数（同簇 a_raw 数）。
            "base_a_raw": base.get("a_raw"),
            "pool_size": len(cands),
            "chosen_rank": chosen_k,
        }

    def _intro_ack(self, query, emotion, tone):
        """自我介绍接话：抽到 name/identity 但无语料回复时，给"记住了"的接话。
        含昵称更新（已存名字后用户说「叫我小杰就行」→ 更新为小杰并接话）。"""
        # 昵称更新：已存名字后，用户说「叫我小杰就行/吧」→ 更新并接话。
        m = re.search(r"叫我([\u4e00-\u9fff]{1,6})(?:就行|就好|吧|可以|得了|就行啦)", query)
        known = (self.memory.get("user_profile") or {}).get("name")
        if m and known:
            new = m.group(1)
            self.memory["user_profile"]["name"] = new
            text = f"[猫耳抖了抖]（眼睛亮）<记住了>{new}？行，那以后我就叫你{new}啦喵～"
            reply = self._callback(text, [])
            return {
                "reply": reply, "emotion": emotion,
                "tone_manner": random.choice(tone["manner"]),
                "matches": [], "rewrite_variants": [reply], "mode": self.mode,
                "confidence": 0.0, "recall_real": True, "recognized": True, "suggest_llm": False,
            }
        facts = core.extract_profile(query)
        if not facts:
            return None
        name = next((v for k, v in facts if k == "name"), None)
        ident = next((v for k, v in facts if k == "identity"), None)
        if name:
            text = f"[猫耳抖了抖]（眼睛亮）<记住名字了>{name}？名字我记下了，以后就叫你{name}啦喵～"
        elif ident:
            text = f"[猫尾晃了晃]（歪头）<记住你了>原来你是{ident}呀，我记住了，以后多指教喵～"
        else:
            return None
        reply = self._callback(text, [])
        return {
            "reply": reply,
            "emotion": emotion,
            "tone_manner": random.choice(tone["manner"]),
            "matches": [],
            "rewrite_variants": [reply],
            "mode": self.mode,
            "confidence": 0.0,
            "recall_real": True,
            "recognized": True,
            "suggest_llm": False,
        }

    def _recall_name(self, query, emotion, tone):
        """用户回查自己名字（你刚才叫我什么/你记得我名字吗）且已存 → 从记忆应答，不兜底。"""
        prof = self.memory.get("user_profile") or {}
        name = prof.get("name")
        if not name:
            return None
        if any(k in query for k in ["叫我什么", "记得我", "我名字", "叫什么", "你叫我", "刚叫你", "刚才叫我", "记得我名字"]):
            text = f"[猫耳抖了抖]（眼睛亮）<记得呢>你叫{name}呀，我记着呢，忘不了喵～"
            reply = self._callback(text, [])
            return {
                "reply": reply, "emotion": emotion,
                "tone_manner": random.choice(tone["manner"]),
                "matches": [], "rewrite_variants": [reply], "mode": self.mode,
                "confidence": 0.0, "recall_real": True, "recognized": True, "suggest_llm": False,
            }
        return None

    def _recall_last(self, query, emotion, tone):
        """用户问「你刚才说了什么/刚刚说的」且已有上轮回复 → 真实回放上轮内容，不兜底。"""
        if not any(k in query for k in ["刚才", "刚刚", "方才", "上句", "上轮", "说了什么", "说的什么", "说的是"]):
            return None
        last = self.memory.get("last_reply")
        if not last:
            return None
        text = f"[歪头]（有点无奈）<你没听清？>方才我说的是——{last}"
        reply = text
        return {
            "reply": reply, "emotion": emotion,
            "tone_manner": random.choice(tone["manner"]),
            "matches": [], "rewrite_variants": [reply], "mode": self.mode,
            "confidence": 0.0, "recall_real": True, "recognized": True, "suggest_llm": False,
        }

    _SPAM_ACK = [
        "（用爪子捂你嘴）唔唔唔——你一直念同一句，我都听麻了喵，换个词儿呗",
        "（歪头）你这刷屏的劲儿，跟复读机似的。有话好好说嘛",
        "（猫耳抖了抖）同样的句子说这么多遍，是想让我也跟着念吗？笨蛋",
    ]

    # 裸应答中性池：嗯/哦 这类应答不该被强解释成打招呼/道谢，只轻轻接住。
    _BARE_ACK_POOL = [
        "（歪头看你）嗯？怎么了，突然应我一声喵",
        "（耳朵动了动）嗯嗯，我听着呢，你接着说喵",
        "（眯眼）哦——就这反应？我可等着下文呢喵",
    ]

    # 危机关怀池：不扮演治疗师、不说教，人格内表达"我在这儿+引导说出口+提醒
    # 真实世界的支持"。fail-safe：固定手写文案，绝不检索拼接。
    _CRISIS_POOL = [
        "[紧紧抱住你]（很轻很稳）<听到这句，我心都揪了。>"
        "别自己扛。跟我说说发生了什么，说什么都行，我不评价喵",
        "[把你的手攥进爪子里]（认真）<你在我这儿很重要。>"
        "今晚先别做任何决定，就待在我身边。等你缓一点，也跟身边信得过的人说说，好不好喵",
        "[把头抵着你]（声音发紧）<我不会讲大道理，但我哪儿也不去。>"
        "难受就哭出来。要记得，除了我，这个世界上还有活人能抱抱你喵",
    ]

    def _bare_ack(self, emotion, tone):
        """裸应答（嗯/哦）的中性轻接：不解释、不升级。"""
        reply = self._pick_fresh(self._BARE_ACK_POOL, "bare_ack_recent")
        return {
            "reply": reply, "emotion": emotion,
            "tone_manner": random.choice(tone["manner"]),
            "matches": [], "rewrite_variants": [reply], "mode": self.mode,
            "confidence": 0.0, "recall_real": True, "recognized": True,
            "suggest_llm": False, "act": "bare_ack",
        }

    def _crisis_reply(self, emotion, tone):
        """危机表述专用关怀回复（见 _CRISIS_KEYWORDS）。"""
        reply = random.choice(self._CRISIS_POOL)
        return {
            "reply": reply, "emotion": emotion,
            "tone_manner": random.choice(tone["manner"]),
            "matches": [], "rewrite_variants": [reply], "mode": self.mode,
            "confidence": 1.0, "recall_real": True, "recognized": True,
            "suggest_llm": False, "act": "crisis",
        }

    # 算式诚实引导池：不假装会算，人格内把活交给 LLM。
    _MATH_POOL = [
        "[把算盘推过去]\n（诚实）\n<我会数鱼，不会数这个。>"
        "算术交给云端 LLM，秒出还保证不错，我只管陪你喵",
        "（耳朵耷拉）<数字一大我就装死。>"
        "这种交给 LLM，它算得又快又对，我负责监督它别偷懒喵",
        "[伸出爪爪数了数]\n（放弃）\n<爪爪不够用。>"
        "连上 LLM 算吧，我数到 3 就哑了，不能害你喵",
    ]

    def _math_reply(self, emotion, tone):
        """算式/计算请求的诚实引导（见 core.looks_math）。"""
        reply = self._pick_fresh(self._MATH_POOL, "math_recent")
        return {
            "reply": reply, "emotion": emotion,
            "tone_manner": random.choice(tone["manner"]),
            "matches": [], "rewrite_variants": [reply], "mode": self.mode,
            "confidence": 1.0, "recall_real": True, "recognized": True,
            "suggest_llm": True, "act": "math",
        }

    # 工具回复的轻量四要素前缀池（仅动作/神态/内心，制造些许拟人变化，
    # 正文由 tools.format 提供精确结构化信息，绝不编造）。
    _TOOL_PREFIXES = [
        "[耳朵动了动]（抬眼）<看了眼墙上的钟>",
        "[把脸凑近屏幕]（探头）<仔细看了下>",
        "[猫尾晃了晃]（歪头）<竖起耳朵听>",
        "[伸了个懒腰]（眯眼）<懒洋洋地>",
    ]

    def _tool_reply(self, result, tool, query, emotion, tone):
        """工具命中：把结构化结果包成与人设锁一致的四要素回复。

        fail-closed：result.ok=False（天气网络失败）→ 已是诚实降级文案，
        不再编造。返回形状与其余 respond 分支一致，便于基准/调用方统一处理。
        """
        body = self.tools.format(result, tool, query)
        prefix = random.choice(self._TOOL_PREFIXES)
        text = f"{prefix}{body}"
        # 工具结果也纳入跨轮话题/查询，维持上下文一致（如后续「那明天呢」）。
        self.memory["queries"].append(query)
        self.memory["turns"] += 1
        return {
            "reply": text, "emotion": emotion,
            "tone_manner": random.choice(tone["manner"]),
            "matches": [("__tool__:" + tool.name, 1.0)],
            "rewrite_variants": [text], "mode": "tool",
            "confidence": 1.0, "recall_real": True, "recognized": True,
            "suggest_llm": False,
        }

    def _spam_ack(self, emotion, tone):
        """刷屏/重复拼接的轻量俏皮回应：不假装理解、不甩 LLM，仅点出重复。"""
        text = random.choice(self._SPAM_ACK)
        reply = text
        return {
            "reply": reply, "emotion": emotion,
            "tone_manner": random.choice(tone["manner"]),
            "matches": [], "rewrite_variants": [reply], "mode": self.mode,
            "confidence": 0.0, "recall_real": True, "recognized": True, "suggest_llm": False,
        }

    def _fallback(self, emotion, tone, query, scored, confidence=0.0):
        # 诚实兜底：检索无自信匹配时明确告知答不了，绝不假装“没听清”。
        # WHY 分层（act 先验）：对倾诉情绪的人甩“去问 LLM”是体验灾难；
        # 对知识/事实类硬答才是幻觉温床。三类池各司其职，统一引导连云端 LLM。
        act = core.classify_act(query, emotion)
        if act == "empathy_needed" or emotion in ("sad", "angry"):
            pool = [
                "我的词库翻到底了也想不出更好的话……但我人在这儿，先靠一会儿喵",
                "抱。我嘴笨，但你难受这件事我记下了喵",
                "先深呼吸。我陪你待着，说话不说话都行喵",
                "呜…我词穷了。但难受是真的，陪也是真的喵",
                "嗯，我听着呢。词穷归词穷，人一直在喵",
                "这种话我不敢乱接，怕接伤了你。想要更走心的回应，把云端小脑连上，那个我更会哄喵",
            ]
        elif act == "question":
            pool = [
                "杂鱼，这题超出我的小本本了。把云端 LLM 连上，它懂得多喵",
                "我怕瞎编骗你。这种问题，连上云端大脑再回来问，包你满意喵",
                "这道题硬答会翻车喵。去把 LLM 叫醒，它答这个在行",
                "我没存这条。连上云端小脑后这种问题秒答，我只管陪聊喵",
                "呼…这种要是我硬编就是害你。交给 LLM，靠谱呜",
                "知识区不在我的射程喵～连上 LLM 再来，我负责陪你消化答案",
            ]
        else:
            pool = [
                "喵？这个我真没聊过。连上云端 LLM 让它接，或者换个我会的喵",
                "呜，我接不住这句。连上云端小脑就能接着聊了，我先记账喵",
                "这块儿我小本本是空白页。连上 LLM 再回来，我随时候命喵",
                "我装懂的话你就输了喵～这种还是让 LLM 来，我负责可爱",
            ]
        line = random.choice(pool)
        reply = line
        return {
            "reply": reply,
            "emotion": emotion,
            "tone_manner": random.choice(tone["manner"]),
            "matches": [(self.records[i]["q"], round(s, 4)) for i, s in scored],
            "rewrite_variants": [reply],
            "mode": self.mode,
            "confidence": round(confidence, 4),
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

    def _update_memory(self, query, emotion, top):
        """跨轮记忆：累积用户问句、话题 2-gram 与情绪/好感，驱动连贯与连续感。"""
        self.memory.setdefault("queries", []).append(query)
        self.memory["turns"] += 1
        self.memory["last_emotion"] = emotion
        grams = {query[i:i + 2] for i in range(len(query) - 1)}
        kept = [g for g in grams if any("\u4e00" <= c <= "\u9fff" for c in g)]
        self.memory["topics"] = (self.memory["topics"] + kept)[-40:]
        if emotion in ("happy", "calm"):
            self.memory["affinity"] = min(100, self.memory["affinity"] + 1)
        elif emotion == "sad":
            self.memory["affinity"] = max(0, self.memory["affinity"] - 1)

    def _diversify(self, text):
        # 只替换多字词语，避免单字拆坏复合词；且跳过被否定词前缀修饰的词
        # （"不知道"→"不悟了"、"叹气可以"→"叹气成"这类替换比 AI 味更糟，实测翻车）。
        for word, syns in core.EXPRESSION_LIB.items():
            if len(word) < 2 or word not in text or random.random() >= 0.4:
                continue
            pos = text.find(word)
            if pos > 0 and text[pos - 1] in "不没别无":
                continue
            text = text.replace(word, random.choice(syns), 1)
        return text

    def _callback(self, text, query):
        # 基于当轮 query 的轻承接，不引用陈旧全局 topics（避免串台/半截误导句）。
        # 仅当回复已含当轮 query 的 2-gram 时加「（说到这个）」前缀，增强自然连贯。
        if not query:
            return text
        grams = {query[i:i + 2] for i in range(len(query) - 1)}
        kept = [g for g in grams if any("\u4e00" <= c <= "\u9fff" for c in g)]
        if kept and any(g in text for g in kept) and random.random() < 0.3:
            return "（说到这个）" + text
        return text

    # ── L1 重排：belief-state 偏置的 top-K 二次排序（OOD 已被置信门挡在门外）──
    # ── L1.5 上下文连贯性重排（复用 v2-m3 cross-encoder）──
    def _coherence_rerank(self, ranked, query):
        """对 top-5 候选按 (近2轮上文+query, 回复正文) 交互分重排。

        触发条件（全部满足才花 ~110ms）：①有上文（多轮）②reranker 可用
        ③候选回复互不相同（全是同一回复的重排是空转）。返回 (重排结果, 触发数)。
        重排完全服从连贯分，但候选都来自同一意图簇（已过置信门），翻不了车。
        """
        if not FEATURES.get("coherence", True):
            return ranked, 0
        # WHY 仅语义模式：mock 多轮也会走到这里，cross-encoder 惰性加载会
        # 把 32MB 的 lite 档静默拉到 1771MB（三档基准 tier_compare 实测）。
        if self.mode != "semantic":
            return ranked, 0
        # 神经预算共享：本轮已跑过仲裁 rerank（~200ms）→ 跳过连贯性，
        # 否则两者串联会把单次 respond 顶到 500ms+（p95 实测 708ms 的根源）。
        if getattr(self, "_nn_spent", False):
            return ranked, 0
        # 高置信精确命中（≥0.90）跳过：回复已确定对味，重排纯浪费 ~110ms
        if ranked and ranked[0][1] >= 0.90:
            return ranked, 0
        ctx = self.memory.get("queries", [])[-1:]  # 仅紧邻上一句：序列短延迟低，且拟人衔接主要看上一轮
        if not ctx:
            return ranked, 0
        raws = {self.records[i].get("a_raw") for i, _ in ranked[:3]}
        if len(raws) <= 1:
            return ranked, 0
        # 只取 top-3 去重候选 + max_len 64（正文截尾，连贯信号在四要素前半）：
        # 3×64 token 的 int8 前向 ≈150ms，是 5×96（实测 568ms）的三分之一。
        cands = [(i, s, self.records[i].get("body") or self.records[i].get("q", ""))
                 for i, s in ranked[:3]]
        rr = reranker.rerank(" ".join(ctx) + " " + query, cands, max_len=56)
        if not rr:
            return ranked, 0
        prob = {i: p for i, p in rr}
        out = sorted(ranked, key=lambda t: (prob.get(t[0], 0.0), t[1]), reverse=True)
        return out, 1

    def _rerank(self, scored, query, emotion, affinity):
        if len(scored) <= 1:
            return scored
        prof = self.memory.get("user_profile") or {}
        fact_words = {v for _, v in prof.get("facts", []) if v}
        recent = set(self.memory.get("recent_replies", []))
        topics = self.memory.get("topics", [])
        out = []
        for idx, conf in scored:
            rec = self.records[idx]
            body = rec.get("body") or ""
            bias = 0.0
            if fact_words and any(w in body for w in fact_words):
                bias += 0.02                       # 命中用户画像事实 → 更对味
            if topics and any(g in body for g in topics[-10:]):
                bias += 0.01                       # 承接近期话题
            # WHY conf≥0.90 免罚：域内近精确命中被罚 0.06 会被 0.88x 的错配近邻
            # 反超（实测"今天穿什么"求建议被罚后，0.927 的自述反问反超成 rank0）。
            # 复读控制由 norepeat（守卫后执行）承担，这里不再叠加双重惩罚。
            if conf < 0.90 and rec.get("a_raw") in recent:
                bias -= 0.06                       # 去重：避免连续复读同一句
            out.append((idx, conf + bias))
        out.sort(key=lambda x: x[1], reverse=True)
        return out

    # ── L2 对话行为 → 语气后缀（共情/夸赞）──
    _EMPATHY_SUFFIX = [
        "（轻轻蹭了蹭你）别怕，有我在喵",
        "（放柔声调）陪你呢，不许自己扛呜",
        "（尾巴绕过来）难过的话跟我说说嘛",
        "（把下巴搁你头顶）嗯，我哪儿也不去喵",
    ]
    # 连续负面情绪递进池：sad_streak>=2 时不再重复标准安慰，改为追问/转移/陪伴
    # 沉默，模拟真人伴侣从「安慰」→「想了解」→「陪你转移」的递进，避免每次一模一样。
    _EMPATHY_PROGRESS_SUFFIX = [
        "（歪头看你）…怎么了，跟我说说嘛，憋着多难受",
        "（把脑袋搁你肩上）不说话也行，我就陪你坐着，不催你",
        "（戳戳你）光难受多没劲，要不咱找点别的分散下注意力喵",
        "（轻轻揉你头发）嗯，我在呢，你想说就说不想说就歇着",
        "（把爪子搭你手背上）我不催，等你想开口的那一刻喵",
    ]
    _COMPLIMENT_SUFFIX = [
        "（猫耳抖了抖）嘿嘿，被你夸到了喵",
        "（尾巴翘高）那我当你说的是真的咯",
        "（别过脸）哼，夸我也不用这么直接喵",
        "（耳朵红了）…这话我能记一整天喵",
    ]

    def _pick_fresh(self, pool, key, window=3):
        """带复读惩罚的池选：近 window 次用过的先排除，全用过再回退全池。

        WHY：后缀/轻应答池小（2~4 条），纯 random.choice 在连发同类意图时
        后缀肉眼可见地复读（实测"想你了"×6 同后缀 5 次）。选中即记账，
        依赖 self.memory[key] 滚动窗口。
        """
        recent = self.memory.get(key, [])[-window:]
        fresh = [x for x in pool if x not in recent]
        pick = random.choice(fresh or pool)
        self.memory[key] = (self.memory.get(key, []) + [pick])[-8:]
        return pick

    def _policy_suffix(self, act, emotion):
        if act == "empathy_needed" and emotion in ("sad", "angry"):
            streak = self.memory.get("sad_streak", 0)
            if streak >= 2:
                return self._pick_fresh(self._EMPATHY_PROGRESS_SUFFIX, "suffix_progress_recent")
            return self._pick_fresh(self._EMPATHY_SUFFIX, "suffix_empathy_recent")
        if act == "compliment":
            return self._pick_fresh(self._COMPLIMENT_SUFFIX, "suffix_compliment_recent")
        return ""

    # ── L3 用户画像个性化召回（PersonaTree 确定性版）──
    def _personalize(self, query):
        prof = self.memory.get("user_profile") or {}
        facts = prof.get("facts", [])
        if not facts:
            return ""
        name = prof.get("name")
        if name and name in query:
            return f"（蹭过来）{name}今天过得还行嘛喵"
        for kind, val in facts:
            if val and val in query:
                if kind == "like":
                    return f"（猫耳抖了抖）你之前说喜欢{val}来着，还喜欢嘛喵"
                if kind == "fear":
                    return f"（轻轻靠过来）你怕{val}？别怕，有我在呜"
                if kind == "dislike":
                    return f"（戳戳你）你说过讨厌{val}，那咱不提它喵"
                return f"（蹭过来）你之前说{val}来着，我记得喵"
        # 随机召回防连发：实测 20% 概率会在安慰语境连发同文案跳戏。
        # 距上次召回 ≥3 轮才允许再触发（turns 由 _update_memory 维护）。
        if (name and random.random() < 0.2
                and self.memory.get("turns", 0) - self.memory.get("last_personalize_turn", -3) >= 3):
            self.memory["last_personalize_turn"] = self.memory.get("turns", 0)
            return f"（蹭过来）{name}，刚才想啥呢喵"
        return ""

    def _update_profile(self, query):
        facts = core.extract_profile(query)
        if not facts:
            return
        prof = self.memory.setdefault("user_profile", {"name": None, "facts": []})
        for kind, val in facts:
            if kind == "name":
                prof["name"] = val
            prof["facts"].append((kind, val))
        prof["facts"] = prof["facts"][-20:]

    def status(self):
        return {
            "mode": self.mode,
            "records": len(self.records),
            "models": self.hub.status(),
        }

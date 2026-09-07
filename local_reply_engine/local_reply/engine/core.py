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


def has_signal(query):
    """查询质量门：剔除空 / 纯空白 / 纯标点 / 纯 emoji / 无信息量输入。

    WHY：这类输入在 BM25 上会得到 0 分，本应走兜底；但若不加门，短乱码
    （如 "asdf"）可能因巧合命中语料而被误判为「识别成功」。
    """
    s = (query or "").strip()
    if not s:
        return False
    keep = [c for c in s if ("\u4e00" <= c <= "\u9fff") or c.isalnum()]
    # 注：单字中文（如「滚」「喵」）属有效陪伴输入，应放行到检索；纯拉丁/数字
    # 单字即使通过此处也会被 has_cjk 护栏在 respond 中诚实兜底，不会泄漏。
    return len(keep) >= 1


# 知识/事实类意图标记：命中即判 OOD 诚实降级，不被 lexical 误配进 persona 闲聊。
# 严格不覆盖任何域内/闲聊语料问句（无 推荐/翻译/原理/股市/代码/等于几 等）。
_OOD_KNOWLEDGE_MARKERS = [
    "推荐", "介绍", "排行", "哪部", "攻略", "翻译", "原理", "股市",
    "等于几", "代码", "python", "程序", "怎么写",
]


def has_cjk(query):
    """查询是否含中文字符。中文陪伴域的域内语料全为中文，纯拉丁/数字/符号
    查询（如 'asdf qwer zxcv 123'、'party'）应视为域外，除非精确命中语料
    否则诚实兜底——避免 BM25 对拉丁乱码的 IDF 伪高分被误判为「识别成功」。
    """
    return any("\u4e00" <= c <= "\u9fff" for c in (query or ""))


# 弱指代碎片标记：仅含这些成分的短句（如「它呢」「这个怎么办」）才是
# 需要上下文续接的省略/代词碎片；明确实义句（今天好累/考试又没过）不算。
_FRAGMENT_MARKERS = ["它", "他", "她", "那个", "这个", "咋", "怎么办", "咋办",
                    "呢", "啥", "哪个", "怎么", "什么", "哪"]


def is_fragment(query):
    """判断是否为弱指代碎片（省略/代词类短句），仅此类才允许上下文续接。

    WHY：上下文续接本为「它/那个/怎么办」这类孤立几乎无分的碎片设计，
    但「考试又没过」(孤立 0.50)、「今天好累」(孤立有分) 等明确实义短句
    本身已能匹配，不应借上文覆盖，否则会与上文拼接强拽到无关条目（串台）。
    """
    q = (query or "").strip()
    if not q or len(q) > 6:
        return False
    clean = re.sub(r"[\s，。？！、~…—\-,.?!]", "", q)
    if len(clean) > 4:
        return False
    return any(m in clean for m in _FRAGMENT_MARKERS)


# 语气词集合：拉长（啊啊啊/哈哈哈）是中文正常情绪表达，不算刷屏。
# 判定时先折叠语气词连串再查重复；折叠后只剩语气词 → 才是真刷字。
_INTERJECTION_CHARS = set("啊哈嘿嘻哦噢喔嗯呜哎呀哇嗷诶额哟嗚嗻嘿咯")


def _collapse_interjections(s):
    """语气词连串折叠到 2 个（啊啊啊啊啊→啊啊），非语气词游程原样保留。"""
    out, i, n = [], 0, len(s)
    while i < n:
        j = i
        while j < n and s[j] == s[i]:
            j += 1
        out.append(s[i] * (2 if (j - i) >= 2 and s[i] in _INTERJECTION_CHARS else (j - i)))
        i = j
    return "".join(out)


def is_repetitive(query):
    """检测刷屏/重复拼接（如「你你你…」「今天天气真好呀」×4）。

    WHY：纯检索引擎对「同一短语重复拼接」会因 n-gram 叠加被正向匹配到该短语
    对应条目（杠精实测「今天天气真好呀×4」竟命中天气条目）。这类输入不是真提问，
    应轻量俏皮回应而非照常命中。
    判定三步：①折叠语气词拉串（啊啊啊→啊啊）——真情宣泄（"啊啊啊今天好累"）
    不再误杀（实测翻车点）；②折叠后只剩语气词 → 纯刷字（哈哈哈×N）判刷屏；
    ③在折叠串上查非语气词单字长游程（你你你你你你）与精确重复单元。
    """
    s = re.sub(r"[\s，。？！、~…—\-,.?!]", "", query or "")
    if len(s) < 4:
        return False
    s = _collapse_interjections(s)
    # 纯刷字：折叠后只剩语气词（哈哈哈哈哈哈 / 嗯嗯嗯嗯嗯）
    if s and all(ch in _INTERJECTION_CHARS for ch in s):
        return True
    # 非语气词单字长游程（你你你你你你）
    run = 1
    for i in range(1, len(s)):
        if s[i] == s[i - 1]:
            run += 1
            if run >= 6:
                return True
        else:
            run = 1
    # 精确重复单元：s 由某前缀 unit 重复构成（整除或 exact-repeat 前缀）
    for L in range(2, len(s) // 2 + 1):
        unit = s[:L]
        if s == unit * (len(s) // L) and len(s) % L == 0 and len(s) // L >= 2:
            return True
        # 非整除但前段 exact-repeat 且尾部为该 unit 前缀也算（如 unit*N + 部分）
        rep = unit * (len(s) // L)
        if len(s) > len(rep) and s[: len(rep)] == rep and len(s) // L >= 2:
            return True
    return False


# 近义归一：把用户的近义/口语表述映射到语料中已有的代表表述，提升同意图
# 多表述的命中率（避免「我困了」漏而「今天好困没精神」命中这类覆盖不均）。
# rep 必须指向语料真实存在的 q，否则归一反而造出无匹配的新词。
_SYNONYM_MAP = [
    (["我困了", "好困啊", "好困呀", "眼皮打架", "犯困", "瞌睡", "打瞌睡", "困死了", "困死"], "今天好困没精神"),
    (["好饿", "肚子叫了", "肚子饿", "肚饿", "饿死了", "饿坏", "嘴馋了", "嘴馋", "馋了", "馋死"], "我想吃火锅"),
    (["好想你", "想你啦", "有点想你", "想死你了", "超想你"], "想你了"),
    (["无聊死了", "没事干", "闲得慌", "好闲", "闲着", "无聊透顶"], "好无聊啊"),
    (["伤心", "沮丧", "难受", "不好受", "心塞"], "我好难过"),
    (["撑不住了", "累瘫", "累死想睡", "困得想睡", "快累趴"], "今天好累"),
]


def normalize_synonyms(query):
    """将近义表述归一到语料已有代表表述；无映射则原样返回。

    WHY：检索是字面 n-gram 匹配，同一意图的不同口语（「我困了」vs「今天好困没精神」）
    检索分差异大、覆盖不均。归一到语料代表表述后，命中率更稳。仅做保守精确
    替换，避免把「你别伤心」这类劝慰误改成自我情绪表述。
    """
    q = strip_filler(query or "")
    for keys, rep in _SYNONYM_MAP:
        for k in keys:
            if k in q:
                return strip_filler(q.replace(k, rep))
    return q




def looks_ood_knowledge(query):
    """识别明显的事实/知识/推荐类提问 → 应诚实降级交 LLM，避免被「看电影」等闲聊条目误配。"""
    q = (query or "").lower()
    return any(m.lower() in q for m in _OOD_KNOWLEDGE_MARKERS)


# 安慰型回应识别：共情放宽检索只接受「本身是安慰型」的命中，避免「分手」误碰「洗手」。
_COMFORT_CUES = ["陪你", "陪着", "抱抱", "心疼", "难过", "在呢", "别怕", "有我在", "安慰",
                "扛", "乖", "揉", "暖", "靠", "别哭", "别急", "慢慢来", "陪"]

def is_comfort_record(rec):
    """命中记录是否为安慰/共情型回应（含陪伴性抚慰词）。用于共情放宽的有界护栏。"""
    text = (rec.get("a_raw") or rec.get("body") or "")
    return any(c in text for c in _COMFORT_CUES)


# 天气碰撞护栏：闲聊近义（「你人真好」↔「天气真好」）仅因共享字误配天气条目时，
# 在同分候选里找一个非天气条目；找不到且查询像纯夸人 → 诚实兜底，不吐天气错答。
_WEATHER_WORDS = ["天气", "天晴", "下雨", "刮风", "太阳", "多云", "降温", "出太阳",
                 "阴天", "下雪", "打雷", "天好", "天儿"]

def looks_weather(query):
    return any(w in (query or "") for w in _WEATHER_WORDS)

def rec_is_weather(rec):
    return any(w in (rec.get("q") or "") for w in _WEATHER_WORDS)

_PRAISE_WORDS = ["真好", "真棒", "真可爱", "真萌", "真厉害", "好棒", "好厉害", "喜欢你",
                "爱你", "漂亮", "温柔", "可爱", "牛", "赞"]

def looks_praise(query):
    q = query or ""
    return ("你" in q or "咱" in q) and any(w in q for w in _PRAISE_WORDS)


# ── 算式/计算意图：检索引擎算不了，诚实引导 LLM（实测"387乘以42"被"帮帮我"
# 泛化接住却什么都没做——既没回答也没引导，是最差的一档）。"算了"不匹配：
# 数字/运算符要求挡住口语"算了/算了吧"。
_MATH_RE = re.compile(
    r"\d+\s*[×xX*+＋\-－/÷]\s*\d+"          # 387*42 / 3+5
    r"|\d+\s*[乘加加减除]\s*\d+"            # 387乘以42（乘/加/减/除单字）
    r"|\d+\s*(乘以|加上|减去|除以)\s*\d+"
    r"|\d+\s*等于几?|等于多少|[0-9]+%.*多少"
)


def looks_math(query):
    return bool(_MATH_RE.search(query or ""))


# ── 进行时事件句护栏：结果未明的事件（面试了/考完了）不该被庆祝/哀悼类预设回应 ──
# 实测翻车点："我今天面试了" mid-band 随机命中"录取啦！牛炸了"庆祝记录（结果还没说）。
_EVENT_WORDS = ["面试", "考试", "考核", "答辩", "体检", "复试", "决赛", "比赛", "出成绩", "笔试"]
_RESULT_MARKS = ["过了", "没过", "成功", "失败", "挂了", "砸了", "录取", "上榜",
                 "落选", "赢", "输", "通过", "考上", "没考上", "拿下", "黄了", "凉了"]
# 命中记录预设了"成功"或"失败"结局的线索词（庆祝侧/哀悼侧都算预设）。
# WHY "牛"不单独成词：会误伤"牛奶/吹牛"，用"牛炸/真牛"等组合。
_RESULT_PRESUME = ["录取", "恭喜", "庆祝", "牛炸", "真牛", "好牛", "太牛", "请客",
                   "厉害", "第一", "赢", "成功", "没过", "失败", "挂科",
                   "复盘", "下次再战", "算什么", "白考"]


def event_pending(query):
    """进行时事件句：提到事件但没说结果。"""
    q = query or ""
    return any(w in q for w in _EVENT_WORDS) and not any(m in q for m in _RESULT_MARKS)


def presumes_result(rec):
    """命中记录的回复是否预设了事件结局（庆祝或哀悼）。"""
    text = rec.get("a_raw") or rec.get("body") or ""
    return any(w in text for w in _RESULT_PRESUME)


# 粗略情绪推断（零模型）：供前缀多样性池按情绪分组，使舞台指令与正文语域一致。
_EMO_KEYWORDS = {
    "happy": ["开心", "高兴", "可爱", "喜欢", "爱", "萌", "棒", "漂亮", "温柔", "得意", "笑", "甜", "夸"],
    "shy": ["羞", "脸红", "耳热", "别过脸", "躲", "小声", "扭捏", "傲娇"],
    "sad": ["难过", "伤心", "哭", "累", "困", "病", "疼", "委屈", "失落", "沮丧", "失眠", "孤单", "空"],
    "angry": ["烦", "气", "恼", "火", "炸毛", "讨厌", "恨", "怒", "滚"],
    "jealous": ["醋", "吃醋", "凭什么", "凭啥"],
    "worried": ["怕", "慌", "担心", "焦虑", "紧", "悬"],
}
_EMO_FALLBACK = "neutral"

def infer_emotion(text):
    t = text or ""
    for emo, kws in _EMO_KEYWORDS.items():
        if any(k in t for k in kws):
            return emo
    return _EMO_FALLBACK


# ── 对话行为（Dialogue Act）分类：规则驱动，驱动接话/共情/夸赞策略 ──
# 对应学界 Dialogue-Act Policy（arXiv 1807.07255）：先定策略再生成，提升多样性
# 与多轮续航。我们确定性实现：词典 + 标点启发，零模型、零延迟。
_ACT_GREETING = ["你好", "早安", "早", "午安", "晚上好", "hi", "hello", "在吗", "在不在", "哈喽"]
_ACT_FAREWELL = ["晚安", "拜拜", "再见", "睡了", "先走了", "安啦", "安"]
_ACT_COMPLIMENT = ["好棒", "真可爱", "好温柔", "漂亮", "萌", "厉害"]
_ACT_COMPLAINT = ["讨厌", "烦", "烂", "垃圾", "无聊", "讨厌你", "最差"]
# 亲昵表白词（喜欢你/爱你/想你）不是夸奖：进 compliment 会贴"被你夸到了"后缀
# （实测"我想你了"→"嘿嘿，被你夸到了喵"人机感爆炸），单独成表仅用于识别。
_ACT_AFFECTION = ["喜欢你", "爱你", "想你"]
_ACT_EMPATHY = ["难过", "伤心", "哭", "累", "困", "病", "疼", "孤单", "失恋", "失眠", "想哭", "委屈", "抑郁",
                "考试", "挂科", "考砸", "没过", "失败", "分手", "被骂", "挨骂", "挨批", "失业", "挨说"]


def classify_act(query, emotion=None):
    """规则化对话行为：greeting/farewell/compliment/complaint/empathy_needed/question/casual。"""
    q = (query or "").strip()
    if not q:
        return "casual"
    if any(w in q for w in _ACT_GREETING):
        return "greeting"
    if any(w in q for w in _ACT_FAREWELL):
        return "farewell"
    if any(w in q for w in _ACT_COMPLIMENT):
        return "compliment"
    if any(w in q for w in _ACT_COMPLAINT):
        return "complaint"
    if emotion in ("sad", "angry") or any(w in q for w in _ACT_EMPATHY):
        return "empathy_needed"
    if q.endswith(("？", "?", "吗", "呢")) or any(w in q for w in ["怎么", "什么", "为什么", "如何", "哪", "谁", "多少", "几"]):
        return "question"
    return "casual"


# ── 用户画像抽取（PersonaTree 确定性版）：从自述句提取 name/identity/like/fear/dislike ──
# WHY 否定前瞻：「我叫什么」是回查不是报名，「我是不是X」是自问不是自述——
# 不挡会把"什么吗"/"不是想太多了"存成画像，且污染整个会话（实测翻车）。
_PROFILE_PATTERNS = [
    (r"我叫(?!什么|啥|谁)([\u4e00-\u9fff]{1,6})", "name"),
    (r"我是(?!不是|不)([\u4e00-\u9fff]{2,8})", "identity"),
    (r"我喜欢([\u4e00-\u9fff]{2,8})", "like"),
    (r"我怕([\u4e00-\u9fff]{2,8})", "fear"),
    (r"我讨厌([\u4e00-\u9fff]{2,8})", "dislike"),
]


def extract_profile(query):
    """从用户自述抽取画像事实（确定性正则）；无则返回空。"""
    out = []
    for pat, kind in _PROFILE_PATTERNS:
        m = re.search(pat, query or "")
        if m:
            out.append((kind, m.group(1)))
    return out


# 语气/时间填充词剥离（第二检索机会）：近义改写（"今天好累啊"→"好累"）的轻量兜底，
# 仅在首检低于阈值时触发，不当主路径；知识类 OOD 已由 looks_ood_knowledge 提前截住。
_FILLERS = ["今天", "昨天", "现在", "那个", "这个", "啊", "呢", "嘛", "呀", "啦",
            "呗", "哦", "嘞", "哟", "噻", "哈", "额", "诶"]


def strip_filler(query):
    s = query or ""
    for f in _FILLERS:
        s = s.replace(f, "")
    return s.strip()


def load_persona_bank(jsonl_paths, limit=None):
    """从手写语料 jsonl（可多个文件）加载经验库；抽取四要素。

    入参 jsonl_paths 为路径列表（glob 结果），每行形如
    {"conversations":[{"from":"human","value":..},{"from":"gpt","value":..}]}。

    limit：单文件最大加载条数，**None 表示不截断（全量）**。默认 None，
    避免「用户换上大体量语料却被静默截断到前 5000 条」导致能力无声衰退。
    （原默认 5000 是按内置手写语料单文件体量设的防御值，对外来语料是隐性陷阱。）
    """
    records = []
    for path in jsonl_paths:
        with open(path, encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                if limit is not None and i >= limit:
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


# BM25 调参常量：抽到模块级，供 _bm25_score 与自匹配归一化复用（避免魔数重复）。
BM25_K1 = 1.5
BM25_B = 0.75


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
        # 倒排索引：词/字 n-gram -> 文档 id 列表。检索时只打分与查询共享
        # 词或字 n-gram 的候选文档（零共享的文档两路得分必为 0，永不进 top-k），
        # 把 O(N) 全量扫描降为 O(候选数)。N=2万时命中数通常几十~几百，
        # 单次 respond 由 ~280ms 降到 ~20ms，与小数体语料持平，且得分完全一致。
        self.token_postings = defaultdict(list)
        self.gram_postings = defaultdict(list)
        for i, toks in enumerate(self.doc_tokens):
            for t in set(toks):
                self.token_postings[t].append(i)
        for i, gs in enumerate(self.doc_grams):
            for g in set(gs):
                self.gram_postings[g].append(i)

    def _candidates(self, q_tokens, q_grams):
        """倒排候选集：取查询中**最小的几个**词/字 n-gram 的 posting 并集并封顶。

        WHY 不取全并集：常见字 n-gram（"今天"/"我想"）在 2 万语料里 posting 可达数千，
        全并集退化为近全量扫描。真实匹配文档必与某个**区分度高的稀有**词/gram 共享，
        而稀有项 posting 极小；仅并前 3 小 posting 即可覆盖域内命中，且把候选规模
        压到数百~两千，单次检索从 O(N) 降为常数级，稳态延迟与小数体语料持平。
        OOD 查询（仅共享高频词）本就走兜底，落选不影响正确性。
        """
        postings = []
        for t in set(q_tokens):
            p = self.token_postings.get(t)
            if p:
                postings.append(p)
        for g in set(q_grams):
            p = self.gram_postings.get(g)
            if p:
                postings.append(p)
        if not postings:
            return set()
        postings.sort(key=len)
        cand = set(postings[0])
        for p in postings[1:3]:
            cand.update(p)
            if len(cand) > 2000:
                break
        return cand

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
        k1, b = BM25_K1, BM25_B
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
        cand = self._candidates(q_tokens, q_grams)
        if not cand:
            return []
        scored = []
        for i in cand:
            s_bm = self._bm25_score(q_tokens, i)
            s_gr = self._gram_score(q_grams, i)
            mixed = 0.7 * s_bm + 0.3 * s_gr
            scored.append((i, mixed, s_bm, s_gr))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def _self_bm25(self, q_tokens):
        """BM25(q, q)：查询与「自身视为文档」的得分，用作归一化上界。

        WHY：原始 BM25 分与查询长度正相关——长查询（哪怕域外英文长句）天然
        高分，短查询（哪怕域内「谢谢」）分数趋 0，两类分布完全重叠，导致任何
        绝对阈值都无法分离。除以 score(q,q) 后值域归到 [0,1] 且长度无关。
        """
        dl = len(q_tokens) or 1
        tf = defaultdict(int)
        for t in q_tokens:
            tf[t] += 1
        k1, b = BM25_K1, BM25_B
        score = 0.0
        for t in q_tokens:
            if t in self.bm25_idf:
                f = tf[t]
                score += self.bm25_idf[t] * (f * (k1 + 1)) / (f + k1 * (1 - b + b * dl / self.avg_dl))
        return score

    def _gram_cosine(self, q_grams, doc_i):
        """字 n-gram 的真实余弦相似度，值域严格 [0,1]。

        WHY：_gram_score 的分母用的是「长度乘积」而非向量模长，未做 L2 归一，
        实测短查询可飙到 36，与 BM25 分量量纲不一致，无法加权。
        """
        doc_gs = self.doc_grams[doc_i]
        q_tf, doc_tf = defaultdict(int), defaultdict(int)
        for g in q_grams:
            q_tf[g] += 1
        for g in doc_gs:
            doc_tf[g] += 1
        dot = nq = nd = 0.0
        for g in set(q_tf) | set(doc_tf):
            w = self.gram_idf.get(g, 0.0)
            qv, dv = w * q_tf[g], w * doc_tf[g]
            dot += qv * dv
            nq += qv * qv
            nd += dv * dv
        return dot / (math.sqrt(nq * nd) or 1.0)

    def search_normalized(self, query, top_k=3):
        """长度无关检索，返回 [(idx, 归一混合分, bm25归一, 字级余弦, 领先比)]。

        归一混合分 = 0.7 * bm25归一 + 0.3 * 字级余弦，两分量均在 [0,1]，
        可跨查询长度比较；领先比 = top1 / top2，衡量「是否明显命中某一个」。
        仅对倒排候选打分（得分与全量扫描完全一致，零共享文档必为 0 分不进 top-k）。
        """
        q_tokens = tokenize(query, self.use_jieba)
        q_grams = char_ngrams(query)
        self_bm = self._self_bm25(q_tokens) or 1e-9
        cand = self._candidates(q_tokens, q_grams)
        if not cand:
            return []
        scored = []
        for i in cand:
            bm = self._bm25_score(q_tokens, i) / self_bm
            gr = self._gram_cosine(q_grams, i)
            scored.append((i, 0.7 * bm + 0.3 * gr, bm, gr))
        scored.sort(key=lambda x: x[1], reverse=True)
        top = scored[:top_k]
        out = []
        for pos, (idx, mixed, bm, gr) in enumerate(top):
            nxt = top[pos + 1][1] if pos + 1 < len(top) else 0.0
            out.append((idx, mixed, bm, gr, mixed / (nxt + 1e-9)))
        return out


# 扩充口语/情绪表达库（原 Demo 仅 3 个词）。覆盖常见情绪与通用词，带口语与喵味变体。
# WHY 只留内容词、删虚词：_diversify 是盲替换，"可以/真的/知道"这类功能词替换会
# 直接改坏语法（实测"叹气可以"→"叹气成"、"真的算了"→"没忽悠算了"、"不知道"→
# "不悟了"——比 AI 味更糟的语病）。内容词（情绪/状态）替换语义稳定，虚词一律不入库。
EXPRESSION_LIB = {
    "开心": ["高兴", "快乐", "美滋滋", "乐呵"],
    "难过": ["伤心", "低落", "失落", "难受"],
    "好": ["棒", "不错", "挺好", "蛮赞", "贼好"],
    "喜欢": ["中意", "稀饭"],
    "累": ["乏", "倦", "没劲儿", "瘫了"],
    "饿": ["肚子空", "想啃", "胃抗议", "嘴馋"],
    "想": ["惦记", "念叨", "琢磨", "挂念"],
    "漂亮": ["好看", "养眼", "水灵", "俏"],
    "讨厌": ["烦", "膈应", "腻歪"],
    "害怕": ["怂", "慌", "怯", "发毛"],
    "冷": ["凉", "冻", "寒", "瑟瑟"],
    "热": ["烫", "闷", "燥"],
    "困": ["瞌睡", "想睡", "犯懒"],
    "无聊": ["闲得慌", "没劲", "空落落", "闷得慌"],
    "生气": ["恼", "火大", "憋屈", "炸毛", "气鼓鼓"],
    "谢谢": ["谢啦", "多谢"],
}

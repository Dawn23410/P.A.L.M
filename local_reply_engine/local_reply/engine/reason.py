# -*- coding: utf-8 -*-
"""符号伪推理层（A 方向，确定性、fail-closed）。

对应学界：Dialogue State Tracking (DST) 的「确定性 slot-value 变体」+ 规则化
Coreference Resolution（CogNIAC / Multi-Pass Sieve 的 precision-first）+ 轻量
Production System（CLIPS 风格的 match→resolve→act）。

设计原则：
- 纯标准库，零模型、零网络。
- 所有抽取/推理都是**规则化、可调试、可复现**的；未覆盖的模式一律「不猜」，
  回退到检索/诚实降级（fail-closed），绝不编造或硬解指代。
- BeliefState 是结构化的「世界模型」，供检索增强（实体解析）、个性化召回、
  连贯性使用——替代原本散落在 engine.memory 里的同名/喜好字段。

为何叫「伪推理」：它不做真理解/泛化，只做**受控近似**——在陪伴窄域用
确定性状态机 + 规则产生式，模拟「记得你说过的话 / 解得清指代 / 跟踪偏好」，
从而吊打 stochastic LLM 的不可控性。不宣称真推理能力。
"""

import re


# ── 规则化抽取模式（保守，避免误注册）──
# 实体命名：「(我的)?<事物>叫<名字>」或「它/他/她叫<名字>」
_BOUNDARY = "，。！？、~…—,./\\()（）:：;；\"' \t\n\r"
_TRAILING_PARTICLES = "呀呢啊吧啦哦嘛呗咧哟嗷咯哒嘿喂咕"
# 名字前可能带的首动词前缀（「我讨厌吃香菜」→ 剥「吃」得「香菜」）。
_LEADING_VERB = "吃喝玩看听去买带"

_ENTITY_NAME_PATTERNS = [
    re.compile(r"(?:我的)?[^叫]{0,6}?叫([一-龥A-Za-z0-9·•]{1,8})(?:[" + re.escape(_BOUNDARY) + r"]|$)"),
    re.compile(r"[它他她]叫([一-龥A-Za-z0-9·•]{1,8})(?:[" + re.escape(_BOUNDARY) + r"]|$)"),
    re.compile(r"这是([一-龥A-Za-z0-9·•]{1,8})(?:[" + re.escape(_BOUNDARY) + r"]|$)"),
]
# 排除：疑问句 / 询问对方，不应注册实体
_ENTITY_GUARD = ["你叫", "叫什么", "名字", "什么名字", "谁叫", "叫谁", "叫你"]

# 自我介绍：「我叫X」/「我是X」。名字后跟边界/句尾。
# WHY 否定前瞻：「我叫什么」是回查、「我是不是X」是自问——不挡会把疑问词/
# 反问句存成名字污染整个会话（实测："我是不是想太多了"→name=不是想太多了）。
_SELF_NAME = [
    re.compile(r"我叫(?!什么|啥|谁)([一-龥A-Za-z0-9·•]{1,8})(?:[" + re.escape(_BOUNDARY) + r"]|$)"),
    re.compile(r"我是(?!不是|不)([一-龥A-Za-z0-9·•]{1,8})(?:[" + re.escape(_BOUNDARY) + r"]|$)"),
]

# 偏好 / 厌恶。抽取后 _norm_name 剥尾助词（如「我喜欢猫呀」→「猫」）。
_PREF_LIKE = [
    re.compile(r"我喜欢([一-龥A-Za-z0-9·•]{1,8})"),
    re.compile(r"我爱([一-龥A-Za-z0-9·•]{1,8})"),
    re.compile(r"我爱吃([一-龥A-Za-z0-9·•]{1,8})"),
    re.compile(r"我超?喜欢([一-龥A-Za-z0-9·•]{1,8})"),
]
_PREF_DISLIKE = [
    re.compile(r"我讨厌([一-龥A-Za-z0-9·•]{1,8})"),
    re.compile(r"我恨([一-龥A-Za-z0-9·•]{1,8})"),
    re.compile(r"我不喜欢([一-龥A-Za-z0-9·•]{1,8})"),
    re.compile(r"我讨厌吃([一-龥A-Za-z0-9·•]{1,8})"),
]

# 指代代词（需消解）
_PRONOUNS = ["它", "他", "她", "那个", "这个", "牠"]


def _norm_name(s):
    """从抽取出的原始片段规整为干净名字：剥首尾标点与尾助词、首动词前缀。fail-closed 不猜。"""
    if not s:
        return None
    s = s.strip(_BOUNDARY)
    # 剥首动词前缀（「吃香菜」→「香菜」），保留至少 1 字。
    while len(s) > 1 and s[0] in _LEADING_VERB:
        s = s[1:]
    # 迭代剥尾助词（「小梦呀」→「小梦」），保留至少 1 字。
    changed = True
    while changed and len(s) > 1:
        changed = False
        if s[-1] in _TRAILING_PARTICLES:
            s = s[:-1]
            changed = True
    return s or None


def _soft_clean(s):
    """轻量清洗：仅去空白/控制符，保留标点作为名字边界（防描述粘连如「咪咪，超可爱的」）。"""
    return re.sub(r"[\s\u0000-\u001f\u007f-\u009f]", "", s or "")


class BeliefState:
    """确定性信念状态（DST 变体）。所有字段可序列化、可调试。"""

    def __init__(self):
        self.entities = {}          # mention/别名 -> canonical 名（实体注册表）
        self.last_entity = None     # 最近提及的实体 canonical 名（指代消解锚点）
        self.profile = {
            "name": None,
            "facts": [],             # [(kind, value)] 用户自述事实
            "preferences": [],       # 喜欢的事物
            "dislikes": [],          # 讨厌的事物
        }
        self.emotion = {"current": None, "streak": 0}
        self.turns = 0

    def snapshot(self):
        return {
            "entities": dict(self.entities),
            "last_entity": self.last_entity,
            "profile": {k: (list(v) if isinstance(v, list) else v)
                        for k, v in self.profile.items()},
            "emotion": dict(self.emotion),
            "turns": self.turns,
        }


class Extractor:
    """规则化抽取：从单句查询抽取实体命名 / 自我介绍 / 偏好 / 指代。"""

    def extract(self, query):
        # 轻量清洗保留标点边界（防「咪咪，超可爱的」粘连）；名字/实体再 _norm_name 规整。
        q = _soft_clean(query)
        out = {
            "name": None, "entity": None, "preferences": [],
            "dislikes": [], "has_pronoun": False, "pronoun": None,
        }
        if not q:
            return out
        # 指代检测
        for p in _PRONOUNS:
            if p in q:
                out["has_pronoun"] = True
                out["pronoun"] = p
                break
        # 自我介绍
        for pat in _SELF_NAME:
            m = pat.search(q)
            if m and "你" not in q[:2]:
                out["name"] = _norm_name(m.group(1))
                break
        # 实体命名（带护栏：排除询问对方）
        if not any(g in q for g in _ENTITY_GUARD):
            for pat in _ENTITY_NAME_PATTERNS:
                m = pat.search(q)
                if m:
                    cand = _norm_name(m.group(1))
                    if cand and cand not in _PRONOUNS:
                        out["entity"] = cand
                        break
        # 偏好 / 厌恶（用 set 去重：多个模式可能重叠匹配，如「我喜欢猫」触发 喜欢/超?喜欢）
        prefs, dislikes = set(), set()
        for pat in _PREF_LIKE:
            m = pat.search(q)
            if m:
                v = _norm_name(m.group(1))
                if v:
                    prefs.add(v)
        for pat in _PREF_DISLIKE:
            m = pat.search(q)
            if m:
                v = _norm_name(m.group(1))
                if v:
                    dislikes.add(v)
        out["preferences"] = list(prefs)
        out["dislikes"] = list(dislikes)
        return out

    def classify_relation(self, query):
        """粗略判定句子主语关系，供产生式「实体 vs 自我介绍 vs 偏好」分流。"""
        q = _soft_clean(query)
        if any(g in q for g in _ENTITY_GUARD) or q.startswith("你"):
            return "about_other"
        if "我叫" in q or "我是" in q:
            return "self_intro"
        if "叫" in q:
            return "entity_naming"
        if "喜欢" in q or "爱" in q or "讨厌" in q or "恨" in q:
            return "preference"
        return "general"


class Inference:
    """产生式：把抽取结果应用到 BeliefState（确定性 match→resolve→act）。"""

    @staticmethod
    def apply(belief, extracted):
        # 自我介绍 → 名字
        if extracted["name"]:
            belief.profile["name"] = extracted["name"]
            belief.profile["facts"].append(("name", extracted["name"]))
        # 实体命名 → 注册表 + 最近实体锚点
        if extracted["entity"]:
            e = extracted["entity"]
            belief.entities.setdefault(e, e)
            belief.last_entity = e
            belief.profile["facts"].append(("pet/thing", e))
        # 偏好 / 厌恶（去重追加）
        for p in extracted["preferences"]:
            if p not in belief.profile["preferences"]:
                belief.profile["preferences"].append(p)
        for d in extracted["dislikes"]:
            if d not in belief.profile["dislikes"]:
                belief.profile["dislikes"].append(d)
        belief.turns += 1
        return belief


class PseudoReason:
    """符号伪推理编排器：update（抽取+推理）→ resolve（指代消解增强查询）。

    fail-closed：指代无法消解（无最近实体）时 resolve 返回原句，不动检索；
    抽取无结果时 update 为空操作。绝不编造实体或硬解。
    """

    def __init__(self):
        self.belief = BeliefState()
        self._extractor = Extractor()
        self._inference = Inference()

    def update(self, query, emotion=None):
        ex = self._extractor.extract(query)
        self._inference.apply(self.belief, ex)
        # 情绪翻转（确定性状态机）：sad 累加 streak，其余清零
        if emotion == "sad":
            self.belief.emotion["streak"] = self.belief.emotion["streak"] + 1
        else:
            self.belief.emotion["streak"] = 0
        self.belief.emotion["current"] = emotion
        return self.belief

    def resolve(self, query):
        """指代消解：把代词替换为最近实体 canonical 名（实体解析增强检索）。

        仅当：① 查询含代词 ② 存在最近实体锚点 时才替换；否则原样返回。
        多代词逐个替换；替换后若与原文不同则返回增强查询。
        """
        q = query
        if self.belief.last_entity and self._extractor.extract(q)["has_pronoun"]:
            for p in _PRONOUNS:
                if p in q:
                    q = q.replace(p, self.belief.last_entity, 1)
            if q != query:
                return q
        return query

    def snapshot(self):
        return self.belief.snapshot()


# 便捷构造
def new_reasoner():
    return PseudoReason()

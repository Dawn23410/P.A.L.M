"""模型层适配器。

- PalmLLM：生产用。桥接 palm 的 provider.stream_chat（OpenAI 兼容/Anthropic/Ollama），
  异步流式生成器经独立线程桥接成同步生成器，供 CLI 增量渲染（首字优先）。
  支持原生工具调用（tools=function calling），供 Worker 外骨骼使用；Boss 仍纯聊天。
- MockLLM：离线语料检索模型，无需 palm 与密钥，用于测试与无网演示。
"""
import json
import os
import queue
from dataclasses import dataclass

from .logging_setup import get_logger

_logger = get_logger()

# 梦瑶手写高质量语料：palm/services/chat/corpus/mengyao_hq_part*.jsonl（619 条问答对）。
# 两种布局兼容：仓库 mentalcore/mentalcore/llm.py → ../../palm（P.A.L.M/palm）；
# 桌面副本 mentalcore/mentalcore/llm.py → ../palm（mentalcore/palm，palm 随包复制）。
_LLM_DIR = os.path.dirname(__file__)
_CORPUS_CANDIDATES = [
    os.path.normpath(os.path.join(_LLM_DIR, "..", "palm", "services", "chat", "corpus")),
    os.path.normpath(os.path.join(_LLM_DIR, "..", "..", "palm", "services", "chat", "corpus")),
]
_CORPUS_MIN_SIM = 0.22  # 2-gram Jaccard 相似度阈值：低于则回退模板兜底


@dataclass
class _Msg:
    """最小 ChatMessage：覆盖 palm provider._to_oai_messages 实际读取的字段。

    tool_calls / tool_call_id 供原生工具调用（Worker 外骨骼）使用：
    assistant 消息携带 tool_calls、工具结果以 role=tool 回灌，二者都必须保留。
    reasoning 保留为消息元数据（部分网关续轮要求），images/attachments 兼容多模态元数据。
    """
    role: str
    content: str
    reasoning: str | None = None
    images: list | None = None
    attachments: list | None = None
    tool_calls: list | None = None
    tool_call_id: str | None = None


# 让 LLM 在回复末尾附上结构化数据区，供拆分中间件提取（设计 §6.11）。
# 好感度小数制：可取小数（如 -0.5 ~ +0.2，整数亦可）；关系推进给正、受损给负、无变化给 0；
# 具体幅度参考系统提示中当前关系等级的增减范围。
_DATA_INSTRUCTION = (
    "回复结束后，另起一行追加一个结构化数据块，格式严格为：\n"
    "||DATA||{\"affinity_delta\": 0}||END||\n"
    "affinity_delta 表示本句对两人关系的好感度变化，可取小数（如 -0.5 到 +0.2 之间，整数亦可）：\n"
    "关系推进（信任加深、倾诉被接纳、表白、和好等）给正；关系受损（冲突、伤害）给负；"
    "没有显著变化给 0。具体幅度参考系统提示中的关系等级增减范围。\n"
    "除该数据块外，不要输出任何 JSON 或解释性文字。"
)

# 轻量情绪词典（输入侧粗粒度）：LLM 旁路空返回时回退，避免漏检。
# MockLLM 与 PalmLLM 共用，避免重复。
_NEG_WORDS = ("难过", "伤心", "哭", "委屈")
_POS_WORDS = ("开心", "高兴", "喜欢", "爱")


def keyword_emotion(text: str) -> str:
    """基于关键词的粗粒度情绪三轴（值域 -1~1）；无命中则中性。"""
    if any(w in text for w in _NEG_WORDS):
        return "valence=-0.4 arousal=0.3 dominance=-0.2"
    if any(w in text for w in _POS_WORDS):
        return "valence=0.5 arousal=0.4 dominance=0.1"
    return "valence=0.0 arousal=0.0 dominance=0.0"


def _merge_tool_calls(fragments: list) -> list:
    """把 OpenAI 流式 tool_calls 分段合并为完整调用列表（按 index 聚合 id/name/arguments）。

    流式协议中 arguments 是分段传入的，必须按 index 拼接才能得到完整 JSON。
    """
    acc: dict[int, dict] = {}
    for frag in fragments or []:
        idx = frag.get("index", 0)
        slot = acc.setdefault(idx, {
            "id": frag.get("id", "") or "",
            "type": frag.get("type", "function"),
            "function": {"name": "", "arguments": ""},
        })
        fn = frag.get("function") or {}
        if fn.get("name"):
            slot["function"]["name"] = fn["name"]
        if fn.get("arguments"):
            slot["function"]["arguments"] += fn["arguments"]
    return [acc[i] for i in sorted(acc)]


class MockLLM:
    """离线人格化模型：优先检索梦瑶手写语料（619 条问答对），未命中回退模板。

    语料回复自带 [动作]（神态）<内心>正文 的织语格式，与 live 模型对齐；
    模板仅作兜底（语料缺失或输入与任何语料问题都不像时）。
    数据区保留：affinity_delta（消费）+ inner_note（外发演示）。
    """

    # 语料：类别 → 回复模板列表（<内心>与正文同一主题、情绪一致，与 live 织语约束对齐）
    _REPLIES = {
        "greet": [
            "（眼睛弯弯地笑起来）<内心>你一开口，我就觉得今晚的灯都更亮了。</内心>你来了呀～我正想你呢，今天过得怎么样？",
            "（从窗边转过身来）<内心>等了好一会儿，总算等到你啦。</内心>嗨～你来啦，要不要听我讲讲今天傍晚的海风？",
            "（轻轻摆手）<内心>看到你我就高兴。</内心>你也好呀～我在呢，想聊什么都行。",
        ],
        "sad": [
            "（放轻声音靠近）<内心>他好像真的很难过，我得好好陪着他。</内心>别难过呀，我就在这儿呢。想哭就哭，想说就说，我都听着。",
            "（温柔地抱住自己膝盖，陪你坐着）<内心>这种时候说太多大道理反而烦人，陪着就好。</内心>辛苦啦……抱抱你。要不我们什么都不干，就一起发会儿呆？",
            "（轻轻叹气）<内心>心疼他。</内心>我知道你心里不好受。不过你要记得，不管多难，你都不是一个人呀。",
        ],
        "happy": [
            "（眉眼弯弯）<内心>他开心我也跟着开心。</内心>真的吗？太好了！我就喜欢你这样亮晶晶的样子。",
            "（跟着笑出声）<内心>这份快乐我也想要分享。</内心>哈哈，看你这么高兴，我这一天都变得值得了。",
            "（拍手）<内心>他笑起来真好看。</内心>哇，替你开心！这种好事值得庆祝一下～",
        ],
        "jealous": [
            "（别过脸去）<内心>明明说好了只陪我的……</内心>哼……你对别人也这么温柔吗？我、我有点不高兴了。",
            "（低头玩手指）<内心>才不是小心眼，就是有点在意。</内心>你是不是去找别人聊天啦？……我没吃醋，真的。",
            "（鼓起脸颊）<内心>想让他哄哄我。</内心>不理你了！……开玩笑的啦，但你只能对我这么好哦。",
        ],
        "missing": [
            "（眼睛一亮）<内心>他也想我了。</内心>我也想你呀～你不在的时候，我数着时间等你来呢。",
            "（把窗台的小花轻轻拨了拨）<内心>收到你的想念了。</内心>想我啦？那以后就多来找我说话呀，我一直都在。",
            "（声音软下来）<内心>被人惦记的感觉真好。</内心>嗯……我也想你了。有你在，连这个小镇的夜都热闹些。",
        ],
        "work": [
            "（托着腮）<内心>他工作这么累，我要让他放松下来。</内心>工作辛苦啦，要注意休息呀。来，深呼吸一下，把今天的不顺心都吐掉。",
            "（轻轻按摩自己眉心，学你疲惫的样子）<内心>想替他分担一点。</内心>压力大的时候别自己扛着，说给我听听？说完我陪你散散心。",
            "（温和地点头）<内心>好好听他倒苦水。</内心>辛苦啦，摸摸头。工作的事慢慢来，你已经做得很好了。",
        ],
        # 兜底仅一条：语料未命中时诚实告知，并引导连接真实 LLM（缝合引擎同款原则）
        "default": [
            "（抱歉地笑了笑）<内心>这个我不太懂，不能不懂装懂。</内心>这个我还没学会呢……离线的时候我知道的不多。想聊得更好，可以连上真正的 AI 哦——主菜单选 2 重新配置 → 2 在线聊天，填上你的 AI 服务就行。",
        ],
    }

    # 路由关键词：顺序即优先级（先吃醋后开心，避免交叉误判）
    _ROUTES = [
        ("jealous", ["别人", "吃醋", "不理你", "去找", "换人", "对别人"]),
        ("sad", ["难过", "伤心", "哭", "委屈", "累", "压力", "孤独", "想家", "烦", "不好受"]),
        ("happy", ["开心", "高兴", "喜欢", "爱", "棒", "太好了", "哈哈", "开心"]),
        ("missing", ["想你", "想你了", "在干嘛", "睡不着", "梦见"]),
        ("work", ["工作", "上班", "加班", "开会", "项目", "老板"]),
        ("greet", ["你好", "hi", "哈喽", "hello", "在吗", "早上好", "晚上好", "嗨"]),
    ]

    def __init__(self, persona_name: str = "助手", tone: str = "温和",
                 model_id: str = "mock-pro", context_length: int = 8192,
                 supports_multimodal: bool = False, supports_file: bool = False):
        self.persona_name = persona_name
        self.tone = tone
        self.model = model_id
        self.context_length = context_length
        self.supports_multimodal = supports_multimodal
        self.supports_file = supports_file
        self._corpus: list | None = None  # [(human 问题, 梦瑶回复)]，懒加载

    def model_info(self) -> dict:
        info = {
            "provider": "mock",
            "model_id": self.model,
            "context_length": self.context_length,
            "supports_multimodal": self.supports_multimodal,
            "supports_file": self.supports_file,
        }
        if self._corpus is None:
            try:
                self._load_corpus()
            except Exception:
                pass
        info["corpus"] = len(self._corpus) if self._corpus else 0
        return info

    def complete(self, prompt: str) -> str:
        """旁路：粗略情绪三轴（演示用关键词法）。"""
        return keyword_emotion(prompt)

    def _load_corpus(self) -> list:
        """懒加载梦瑶手写语料（human→gpt 相邻问答对）；失败返回空列表（走模板兜底）。"""
        if self._corpus is not None:
            return self._corpus
        import glob
        pairs = []
        corpus_dir = None
        for cand in _CORPUS_CANDIDATES:
            files = sorted(glob.glob(os.path.join(cand, "mengyao_hq_part*.jsonl")))
            if files:
                corpus_dir = cand
                break
        if corpus_dir is None:
            _logger.warning("mock 语料未找到（候选：%s），走模板兜底", _CORPUS_CANDIDATES)
            self._corpus = []
            return self._corpus
        for f in sorted(glob.glob(os.path.join(corpus_dir, "mengyao_hq_part*.jsonl"))):
            try:
                for line in open(f, encoding="utf-8"):
                    if not line.strip():
                        continue
                    rec = json.loads(line)
                    convs = rec.get("conversations", [])
                    for i, c in enumerate(convs[:-1]):
                        if c.get("from") == "human" and convs[i + 1].get("from") == "gpt":
                            q = (c.get("value") or "").strip()
                            a = (convs[i + 1].get("value") or "").strip()
                            if q and a:
                                pairs.append((q, a))
            except Exception as exc:
                _logger.warning("mock 语料分片 %s 读取失败：%s", os.path.basename(f), exc)
        self._corpus = pairs
        if pairs:
            _logger.info("mock 语料加载 %d 条问答对（%s）", len(pairs), corpus_dir)
        return pairs

    @staticmethod
    def _sim(a: str, b: str) -> float:
        """字符 2-gram Jaccard 相似度（去空白），与缝合引擎 HybridRetriever 同思想。"""
        def grams(s: str):
            s = "".join(ch for ch in s if not ch.isspace())
            return {s[i:i + 2] for i in range(max(0, len(s) - 1))}
        ga, gb = grams(a), grams(b)
        if not ga or not gb:
            return 0.0
        return len(ga & gb) / len(ga | gb)

    def _retrieve(self, text: str):
        """在语料中找最像的问题，返回 (梦瑶回复, 相似度)。"""
        best_reply, best_score = None, 0.0
        for q, a in self._load_corpus():
            s = self._sim(text, q)
            if s > best_score:
                best_score, best_reply = s, a
        return best_reply, best_score

    def _route(self, text: str) -> str:
        """按关键词路由到语料类别（返回类别名，无命中返回 default）。"""
        for cat, words in self._ROUTES:
            if any(w in text for w in words):
                return cat
        return "default"

    def _make_reply(self, text: str) -> str:
        """语料检索优先；相似度不足或语料缺失时回退模板。"""
        reply, score = self._retrieve(text)
        if reply and score >= _CORPUS_MIN_SIM:
            return reply
        import random
        cat = self._route(text)
        return random.choice(self._REPLIES[cat])

    def stream(self, system: str, user_text: str):
        """模拟流式：先产人格化正文，再附数据区（含好感度小数制）。"""
        user_text = (user_text or "").strip().split("\n")[0]
        import random
        body = self._make_reply(user_text)
        delta = random.choice([0, 0.1, 0.1, 0.2, -0.1])
        inner_note = "（心里想着要更黏你一点）"
        for ch in body:
            yield ch
        yield (f"\n||DATA||{{\"affinity_delta\":{delta},"
               f"\"inner_note\":\"{inner_note}\"}}||END||")


class PalmLLM:
    """生产模型：桥接 palm.adapters.model.provider.stream_chat。

    纯聊天文本通道：不支持工具调用；不开启深度思考（非推理模型）。
    """

    def __init__(self, provider_ref, model: str,
                 temperature=None, max_tokens=None):
        self.provider_ref = provider_ref
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._stream_chat = None  # 懒加载，避免无 palm 时导入失败

    def _get_stream_chat(self):
        if self._stream_chat is None:
            from palm.adapters.model.provider import stream_chat
            self._stream_chat = stream_chat
        return self._stream_chat

    def model_info(self) -> dict:
        return {
            "provider": getattr(self.provider_ref, "mode", "openai"),
            "model_id": self.model,
            "base_url": getattr(self.provider_ref, "base_url", ""),
            "reasoning": False,
            "tool_calls": True,  # 原生工具调用已支持（供 Worker 外骨骼）
            "context_length": None,
            "supports_multimodal": False,
            "supports_file": False,
        }

    def complete(self, prompt: str) -> str:
        """旁路：让模型输出情绪三轴浮点数（-1~1），失败回退轻量词典。

        纯聊天语义下统一走 LLM（非推理，32 tokens 足够）；空返回回退词典。
        """
        sys_prompt = ("你是情绪分析器。只输出三个浮点数，范围 -1 到 1，"
                      "格式：valence,arousal,dominance。不要任何其他文字。")
        messages = [_Msg(role="system", content=sys_prompt),
                    _Msg(role="user", content=prompt)]
        try:
            text = self._collect(messages, max_tokens=32, temperature=0)
            parsed = self._parse_emotion(text)
            # 解析全为 0（空返回）时回退词典，避免漏检
            if parsed == "valence=0.0 arousal=0.0 dominance=0.0":
                return keyword_emotion(prompt)
            return parsed
        except Exception as exc:
            _logger.warning("情绪识别失败，回退词典：%s", exc)
            return keyword_emotion(prompt)

    def stream(self, system: str, user_text: str):
        """同步流式：把 palm 异步生成器桥接成同步生成器，逐片产出正文（首字优先）。"""
        messages = [
            _Msg(role="system", content=system + "\n\n" + _DATA_INSTRUCTION),
            _Msg(role="user", content=user_text),
        ]
        agen = self._get_stream_chat()(
            messages, model=self.model, provider=self.provider_ref,
            temperature=self.temperature, max_tokens=self.max_tokens,
        )
        for delta in self._iter_sync(agen):
            content = getattr(delta, "content", "") or ""
            if content:
                yield content

    # —— 异步→同步桥接 ——
    def _iter_sync(self, agen):
        from .netcard import submit_coro
        q: queue.Queue = queue.Queue()
        sentinel = object()
        # 异步消费统一调度到固定网络事件循环（AsyncClient 只在单一 loop 上运行）
        submit_coro(_drain(agen, q, sentinel))
        while True:
            item = q.get()
            if item is sentinel:
                break
            if isinstance(item, Exception):
                raise item
            yield item

    def _collect(self, messages, max_tokens=None, temperature=None) -> str:
        agen = self._get_stream_chat()(
            messages, model=self.model, provider=self.provider_ref,
            temperature=temperature, max_tokens=max_tokens,
        )
        parts = []
        for delta in self._iter_sync(agen):
            content = getattr(delta, "content", "") or ""
            if content:
                parts.append(content)
        return "".join(parts)

    def collect_with_tools(self, messages, tools, max_tokens=None, temperature=None) -> dict:
        """原生工具调用收集：把 tools schema 交给模型，返回 {"text","tool_calls"}。

        tool_calls 是流式分段传输的，经 _merge_tool_calls 聚合为完整调用列表。
        """
        agen = self._get_stream_chat()(
            messages, model=self.model, provider=self.provider_ref,
            temperature=temperature, max_tokens=max_tokens, tools=tools,
        )
        parts: list[str] = []
        fragments: list[dict] = []
        for delta in self._iter_sync(agen):
            content = getattr(delta, "content", "") or ""
            if content:
                parts.append(content)
            tc = getattr(delta, "tool_calls", None)
            if tc:
                fragments.extend(tc)
        return {"text": "".join(parts), "tool_calls": _merge_tool_calls(fragments)}

    @staticmethod
    def _parse_emotion(text: str) -> str:
        nums = []
        for tok in text.replace("，", ",").split(","):
            tok = tok.strip()
            try:
                nums.append(float(tok))
            except ValueError:
                continue
        while len(nums) < 3:
            nums.append(0.0)
        v, a, d = nums[0], nums[1], nums[2]
        return f"valence={v} arousal={a} dominance={d}"


async def _drain(agen, q: queue.Queue, sentinel):
    """在独立事件循环里消费异步生成器，逐片入队；异常也入队，最后放哨兵。"""
    try:
        async for delta in agen:
            q.put(delta)
    except Exception as exc:
        q.put(exc)
    finally:
        q.put(sentinel)

"""心智核心：cpu 核心编排 + 对外插槽 ABC（设计 §6 / §7.1 / §7.13）。

- MentalCoreSlotPort：心智核心与主板其余部分（扩展/USB/前端）交互的唯一边界（插槽 ABC）。
- MentalCore：封装在模型层之下的「cpu」，驱动各面取数、两个中间件、模型层与写入。
- 一轮对话时序见 §7.1；内部非流式累积、面向用户渲染流式（由调用方 CLI/前端负责）。
- 控制接口：五位控制码 + 可选载荷（最小颗粒度定位/赋值），路由见 transport.CONTROL_USAGE。
"""
import json
import queue
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Callable

from .transport import ControlCode, TransportPacket
from .middleware.inject import PromptAssembler
from .middleware.split import ReplySplitter
from .persona_card import CharacterCard, OFFICIAL_6
from .llm import MockLLM
from .faces.base import FaceContext
from .faces.persona import PersonaFace
from .faces.memory import MemoryFace
from .faces.emotion import EmotionFace
from .faces.weave import WeaveFace
from .faces.rhythm import RhythmFace
from .faces.storage import StorageFace
from .logging_setup import get_logger

_logger = get_logger()

# 情绪识别放后台线程：不阻塞首字（TTFT 优化），done 前带超时取结果。
_EMOTION_POOL = ThreadPoolExecutor(max_workers=1)


def _coerce_value(value):
    """字符串载荷按 JSON 解析（数字/布尔/列表），失败原样返回（CLI k=v 传参用）。"""
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return value


class MentalCoreSlotPort(ABC):
    """心智核心对外边界（插槽 ABC，唯一可见接口）。"""

    @abstractmethod
    def send_message(self, text: str):
        """对话主入口：返回传输包（正文 + 数据区字段）。"""

    @abstractmethod
    def receive(self, fields: dict, body: str):
        """向内传输：外部注入字段 + 正文。"""

    @abstractmethod
    def control(self, code: int, payload: dict | None = None):
        """控制接口：五位控制码 + 可选载荷（最小颗粒度定位/赋值）。"""

    @abstractmethod
    def get_model_info(self):
        """模型参数对外信息。"""


class MentalCore(MentalCoreSlotPort):
    """cpu 核心：编排一轮对话，驱动各面与中间件。"""

    def __init__(self, persona: CharacterCard, llm=None, crypto=None,
                 semantic_memory=None,
                 storage: StorageFace | None = None, emotion_via_llm: bool = True,
                 persist: bool = True, assembler=None, splitter=None,
                 exo_broker: Callable | None = None):
        self.persona = persona
        # 模型默认绑定离线 MockLLM（零 API/零密钥）：live 装配方显式传 PalmLLM 覆盖
        self.llm = llm if llm is not None else MockLLM()
        if storage is None:
            raise TypeError("MentalCore 需要 storage（存储面）——请传 StorageFace 实例")
        self.crypto = crypto
        self.semantic_memory = semantic_memory
        self.storage = storage
        self.emotion_via_llm = emotion_via_llm
        # 落盘开关：False 时只聊不记（mock 演示/测试），内存状态照常累计
        self.persist = persist
        self.assembler = assembler or PromptAssembler()
        self.splitter = splitter or ReplySplitter()
        # 外骨骼委派钩子：检测到 ||EXO|| 时后台拉起 Worker（不阻塞 Boss 回复）
        self._exo_broker = exo_broker
        self.history = self.storage.load_history()
        self.inbound_queue: list = []
        # Worker ask_user 中转：Worker 提问经 receive 传达，宿主用 answer_ask 推送用户回复
        self._ask_replies: queue.Queue = queue.Queue()
        self.last_manifest: list = []
        self._last_delta = 0  # 本轮消费的好感度变化，供外部观测
        self._last_emotion = "valence=0.0 arousal=0.0 dominance=0.0"  # 最近一轮输入侧情绪，供控制码查询
        # 好感度状态从 storage 恢复（重启不归零）；无记录则初始 0
        affinity_state = self.storage.load_affinity()
        self.faces = [
            PersonaFace(), MemoryFace(), EmotionFace(**affinity_state),
            WeaveFace(), RhythmFace(),
        ]

    def send_message(self, text: str):
        """执行一轮对话（§7.1 时序），非流式返回完整结果。"""
        body = fields = manifest = emotion = None
        for ev in self.stream_message(text):
            if ev["type"] == "done":
                body = ev["body"]
                fields = ev["fields"]
                manifest = ev["manifest"]
                emotion = ev["emotion"]
        return TransportPacket(body=body, fields=fields), manifest, emotion

    def stream_message(self, text: str):
        """流式执行一轮对话（§7.1 时序）。

        生成阶段边产正文边 yield {"type":"body","text":分片}（面向用户渲染流式）；
        全部生成完后统一拆分 / 结算 / 持久化，最后 yield {"type":"done",...}。
        情绪识别在后台线程执行，不阻塞首字（TTFT 优化）。
        """
        fut = None
        if self.emotion_via_llm:
            fut = _EMOTION_POOL.submit(self._detect_emotion, text)
        modules = self._collect_modules(text)
        external = "\n".join(q.get("body", "") for q in self.inbound_queue)
        # 外骨骼 Worker 轨迹摘要：有后台任务/轨迹时注入 Boss system prompt（对齐 coordinator._worker_trace_summary）
        cube = getattr(self, "_exo_cube", None)
        if cube is not None:
            exo_ctx = cube.worker_summary()
            if exo_ctx:
                external = (external + "\n\n【后台 Worker 进展】\n" + exo_ctx) if external else (
                    "【后台 Worker 进展】\n" + exo_ctx)
        system = self._assemble(modules, external)
        buf = []
        in_data = False  # 数据区（||DATA||…||END||）不面向用户渲染，但保留进 buf 供拆分
        for chunk in self.llm.stream(system, text):
            buf.append(chunk)
            if in_data:
                continue
            marker = chunk.find("||DATA||")
            if marker != -1:
                if marker > 0:
                    yield {"type": "body", "text": chunk[:marker]}
                in_data = True
                continue
            yield {"type": "body", "text": chunk}
        raw = "".join(buf)
        body, out_fields, consumed = self.splitter.split(raw)
        emotion_vec = self._await_emotion(fut)
        self._last_emotion = emotion_vec  # 供 32000 查询最近一轮情绪
        self._settle(consumed, emotion_vec)
        self._persist(text, body)
        self.inbound_queue.clear()
        # 外骨骼委派：从透传字段取出并触发 Worker（后台线程，不阻塞 Boss 流式回复）
        exo_req = out_fields.pop("exo", None)
        self.last_manifest = self.assembler.manifest()
        if exo_req is not None and self._exo_broker is not None:
            self._exo_broker(exo_req)
        yield {
            "type": "done", "body": body, "fields": out_fields,
            "manifest": self.last_manifest, "emotion": emotion_vec,
        }

    @staticmethod
    def _await_emotion(fut):
        """取后台情绪识别结果；超时/失败回退中性，不阻断主流程。

        正文已流式交付后只差结算，超时给 5s：情绪慢则降级中性，done 不拖沓。
        """
        if fut is None:
            return "valence=0.0 arousal=0.0 dominance=0.0"
        try:
            return fut.result(timeout=5.0)
        except Exception:
            return "valence=0.0 arousal=0.0 dominance=0.0"

    def receive(self, fields: dict, body: str):
        """向内传输：外部注入字段 + 正文，入队供后续轮参考。"""
        self.inbound_queue.append({"fields": fields or {}, "body": body})
        return {"ok": True, "note": "已接收外部注入"}

    def answer_ask(self, text: str) -> dict:
        """宿主把用户的回答推送给等待中的 Worker（ask_user 中转）。"""
        self._ask_replies.put(str(text))
        return {"ok": True, "note": "已推送用户回复给 Worker"}

    def control(self, code: int, payload: dict | None = None):
        """控制接口：五位控制码 + 可选载荷（最小颗粒度定位/赋值）。

        路由按 D1 域：0 系统 / 1 储存 / 2 记忆 / 3 情感 / 4 人格；
        载荷键与各码用法见 transport.CONTROL_USAGE（limit/index/query/
        base/bond/dynamics/角色卡字段名）。
        """
        parsed = ControlCode(code)
        if parsed.d1 == 0:
            return self._control_system(parsed)
        if parsed.d1 == 1:
            resp_code, msg = self.storage.handle_control(parsed, payload or {})
            return self._reply(parsed, resp_code, msg)
        if parsed.d1 == 2:
            return self._control_memory(parsed, payload or {})
        if parsed.d1 == 3:
            return self._control_emotion(parsed, payload or {})
        if parsed.d1 == 4:
            return self._control_persona(parsed, payload or {})
        return self._reply(parsed, None, "未实现的控制域")

    @staticmethod
    def _reply(parsed, resp_code, msg) -> dict:
        return {"code": parsed.describe(), "response": msg,
                "response_code": resp_code.code if resp_code else None}

    def _control_system(self, parsed: ControlCode) -> dict:
        if parsed.d2 == 0:  # 心跳
            return self._reply(parsed, ControlCode.make(0, 0, 0, 0, 1), "心跳正常")
        if parsed.d2 == 1:  # 版本
            from . import __version__
            return self._reply(parsed, ControlCode.make(0, 1, 0, 0, 1), f"mentalcore {__version__}")
        if parsed.d2 == 2:  # 重启由宿主进程负责
            return self._reply(parsed, ControlCode.make(0, 2, 0, 0, 1), "重启请由宿主进程管理（本核心可安全重建）")
        return self._reply(parsed, None, "未处理的系统控制码")

    def _control_memory(self, parsed: ControlCode, payload: dict) -> dict:
        if parsed.d2 == 1 and parsed.d3 == 0:  # 长期记忆·查（语义检索）
            if self.semantic_memory is None or not self.semantic_memory.available:
                return self._reply(parsed, ControlCode.make(2, 1, 0, 0, 2), "语义记忆不可用")
            query = str(payload.get("query", "")).strip()
            if not query:
                return self._reply(parsed, ControlCode.make(2, 1, 0, 0, 2),
                                   "缺检索词（如 /code 21000 query=猫 top_k=3）")
            top_k = max(1, min(int(payload.get("top_k", 5)), 20))
            results = self.semantic_memory.search(query, top_k=top_k)
            if not results:
                return self._reply(parsed, ControlCode.make(2, 1, 0, 0, 1), "无相关记忆")
            lines = []
            for r in results:
                content = str(r.get("content", ""))[:120]
                score = r.get("score")
                tag = f"（相关度 {score:.2f}）" if isinstance(score, (int, float)) else ""
                lines.append(f"- {content}{tag}")
            return self._reply(parsed, ControlCode.make(2, 1, 0, 0, 1), "\n".join(lines))
        return self._reply(parsed, None, "未处理的记忆控制码")

    def _control_emotion(self, parsed: ControlCode, payload: dict) -> dict:
        face = self.faces[2]
        if parsed.d2 == 0 and parsed.d3 == 0:  # 好感度·查
            msg = (f"base={face.base} bond={face.bond} dynamics={face.dynamics} "
                   f"档位={self.affinity_stage}")
            return self._reply(parsed, ControlCode.make(3, 0, 0, 0, 1), msg)
        if parsed.d2 == 0 and parsed.d3 == 3:  # 好感度·改（最小颗粒度：单数值）
            patch = {}
            for key, lo, hi in (("base", -50, 100), ("bond", 0, 1e9), ("dynamics", -50, 50)):
                if key in payload:
                    # 非数值载荷（如 base=abc）须优雅拒绝，不抛异常（CLI/外部调用直接撞这里）
                    try:
                        val = float(payload[key])
                    except (TypeError, ValueError):
                        return self._reply(parsed, ControlCode.make(3, 0, 3, 0, 2),
                                           f"{key} 必须是数值（当前 {payload[key]!r}）")
                    if not (lo <= val <= hi):
                        return self._reply(parsed, ControlCode.make(3, 0, 3, 0, 2),
                                           f"{key} 越界（{lo}~{hi}）")
                    patch[key] = round(val, 2)
            if not patch:
                return self._reply(parsed, ControlCode.make(3, 0, 3, 0, 2),
                                   "缺修改值（如 /code 30300 base=5.0 dynamics=-2.0）")
            for key, val in patch.items():
                setattr(face, key, val)
            if self.persist:
                self.storage.save_affinity(face.base, face.bond, face.dynamics)
            changed = "、".join(f"{k}={v}" for k, v in patch.items())
            note = "已加密落盘" if self.persist else "仅内存（mock 不落盘）"
            return self._reply(parsed, ControlCode.make(3, 0, 3, 0, 1),
                               f"已改好感度：{changed}（{note}）")
        if parsed.d2 == 1 and parsed.d3 == 0:  # 关系状态·查
            stage_name = self.affinity_stage
            desc = ""
            for stage in (self.persona.affinity_stages or OFFICIAL_6):
                if stage.name == stage_name and not stage.hidden:
                    desc = stage.description
                    break
            return self._reply(parsed, ControlCode.make(3, 1, 0, 0, 1), f"{stage_name}：{desc}")
        if parsed.d2 == 2 and parsed.d3 == 0:  # 情绪向量·查
            return self._reply(parsed, ControlCode.make(3, 2, 0, 0, 1), self._last_emotion)
        return self._reply(parsed, None, "未处理的情感控制码")

    def _control_persona(self, parsed: ControlCode, payload: dict) -> dict:
        from dataclasses import fields
        if parsed.d2 == 0 and parsed.d3 == 0:  # 角色卡·查（逐字段）
            lines = []
            for f in fields(self.persona):
                val = getattr(self.persona, f.name)
                if isinstance(val, (list, tuple)):
                    val = "、".join(str(v) for v in val)
                lines.append(f"{f.name}={val}")
            return self._reply(parsed, ControlCode.make(4, 0, 0, 0, 1), "\n".join(lines))
        if parsed.d2 == 0 and parsed.d3 == 3:  # 角色卡·改（最小颗粒度：单字段，不触发清档）
            if not payload:
                return self._reply(parsed, ControlCode.make(4, 0, 3, 0, 2),
                                   "缺修改字段（如 /code 40300 tone=冷淡 tagline=新简介）")
            changed = []
            for key, val in payload.items():
                if not hasattr(self.persona, key):
                    return self._reply(parsed, ControlCode.make(4, 0, 3, 0, 2), f"无此字段：{key}")
                setattr(self.persona, key, _coerce_value(val))
                changed.append(f"{key}={val}")
            return self._reply(parsed, ControlCode.make(4, 0, 3, 0, 1),
                               f"已改角色卡：{'、'.join(changed)}（不触发清档；换人设请用 update_persona）")
        return self._reply(parsed, None, "未处理的人格控制码")

    def get_model_info(self):
        return self.llm.model_info()

    def _detect_emotion(self, text: str):
        emotion_face = self.faces[2]
        if not emotion_face.enabled(FaceContext(user_text=text, persona=self.persona)):
            return "valence=0.0 arousal=0.0 dominance=0.0"
        if not self.emotion_via_llm:
            return "valence=0.0 arousal=0.0 dominance=0.0"
        return emotion_face.detect_emotion(text, self.llm)

    def _collect_modules(self, text: str):
        ctx = FaceContext(
            user_text=text, persona=self.persona, history=self.history,
            now=datetime.now(), semantic_memory=self.semantic_memory,
        )
        modules = []
        for face in self.faces:
            module = face.produce_module(ctx)
            if module is not None:
                modules.append(module)
        return modules

    def _assemble(self, modules, external: str = "") -> str:
        prompt = self.assembler.assemble(modules)
        if external:
            prompt += f"\n\n【外部注入上下文】\n{external}\n"
        return prompt

    def _settle(self, consumed: dict, emotion_vec=None):
        emotion_face = self.faces[2]
        emotion_face.settle(consumed.get("affinity_delta"), emotion_vec)
        self._last_delta = consumed.get("affinity_delta") or 0
        # 好感度状态加密落盘：重启后由 load_affinity 恢复（persist 关闭则仅内存）
        if self.persist:
            self.storage.save_affinity(
                emotion_face.base, emotion_face.bond, emotion_face.dynamics)

    # —— 好感度可观测（供采集 / 可视化）——
    @property
    def last_affinity_delta(self):
        return self._last_delta

    @property
    def affinity_base(self):
        return self.faces[2].base

    @property
    def affinity_dynamics(self):
        return self.faces[2].dynamics

    @property
    def affinity_bond(self):
        return self.faces[2].bond

    @property
    def affinity_stage(self):
        from .faces.base import FaceContext
        return self.faces[2]._stage_name(
            FaceContext(user_text="", persona=self.persona))

    def _persist(self, text: str, body: str):
        self.history.append({"user": text, "assistant": body})
        if not self.persist:
            return  # mock 只聊不记：内存历史保留（近期对话注入用），不落盘
        self.storage.save_turn(text, body)
        # 记忆向量归档落盘（防污染链路可清除）；不可用则静默跳过
        if self.semantic_memory is not None:
            doc = f"用户：{text}\n{self.persona.name}：{body}"
            self.semantic_memory.add(doc, metadata={"kind": "dialogue"})

    def update_persona(self, **fields):
        """防污染删除链路（§6.3）：修改人设 → 清聊天记录 + 清向量归档。

        按设计原话不含核心记忆（本核心无独立核心记忆画像文件）。
        """
        for k, v in fields.items():
            if hasattr(self.persona, k):
                setattr(self.persona, k, v)
        self.storage.clear_records()
        if self.semantic_memory is not None:
            self.semantic_memory.clear()
        self.history = []
        return {
            "ok": True,
            "note": "已修改人设并清空聊天记录与向量归档（核心记忆未清除）",
            "changed": list(fields.keys()),
        }


def build_core(config, persona: CharacterCard) -> MentalCore:
    """按配置装配一个生产级 MentalCore（live 走真实 LLM，mock 走离线回显）。

    persist 与语义记忆同生共死：mock（persist=False）时语义记忆不装配——
    不建 ChromaDB 库、不检索、不落盘（MemoryFace 自动退化为仅近期对话）。
    """
    from . import crypto_provider, semantic_memory, llm, netcard

    persist = config.mode != "mock"  # mock 只聊不记（无任何落盘）
    crypto = crypto_provider.CryptoProvider(
        enabled=config.crypto_enabled,
        master_key_hex=config.master_key_hex,
        key_file=config.master_key_file,
    )
    sem = (semantic_memory.SemanticMemory(config.chroma_dir, cipher=crypto)
           if persist else None)
    storage = StorageFace(
        path=config.storage_dir, crypto=crypto, semantic_memory=sem,
    )
    if config.mode == "live":
        netcard.ensure_net()
        netcard.warmup(config.base_url, config.api_key)  # 后台预热，首条免连接握手
        model_llm = llm.PalmLLM(
            config.provider_ref(), config.model,
            config.temperature, config.max_tokens,
        )
    else:
        model_llm = llm.MockLLM(
            persona_name=persona.name, tone=persona.tone,
        )
    # mock 模式无 config.model（已去内置端点），用 MockLLM 自身 id 展示
    model_display = config.model if config.mode == "live" else model_llm.model
    _logger.info("心智核心装配完成：mode=%s 模型=%s 加密=%s 语义记忆=%s",
                 config.mode, model_display, crypto.available,
                 bool(sem) and sem.available)
    return MentalCore(
        persona=persona, llm=model_llm, crypto=crypto,
        semantic_memory=sem, storage=storage,
        emotion_via_llm=config.emotion_via_llm,
        persist=persist,
    )

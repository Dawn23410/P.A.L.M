"""心智核心：cpu 核心编排 + 对外插槽 ABC（设计 §6 / §7.1 / §7.13）。

- MentalCoreSlotPort：心智核心与主板其余部分（扩展/USB/前端）交互的唯一边界（插槽 ABC）。
- MentalCore：封装在模型层之下的「cpu」，驱动各面取数、两个中间件、模型层与写入。
- 一轮对话时序见 §7.1；内部非流式累积、面向用户渲染流式（由调用方 CLI/前端负责）。
"""
from abc import ABC, abstractmethod
from datetime import datetime

from .transport import ControlCode, TransportPacket
from .middleware.inject import PromptAssembler
from .middleware.split import ReplySplitter
from .persona_card import CharacterCard
from .faces.base import FaceContext
from .faces.persona import PersonaFace
from .faces.memory import MemoryFace
from .faces.emotion import EmotionFace
from .faces.weave import WeaveFace
from .faces.rhythm import RhythmFace
from .faces.storage import StorageFace


class MentalCoreSlotPort(ABC):
    """心智核心对外边界（插槽 ABC，唯一可见接口）。"""

    @abstractmethod
    def send_message(self, text: str):
        """对话主入口：返回传输包（正文 + 数据区字段）。"""

    @abstractmethod
    def receive(self, fields: dict, body: str):
        """向内传输：外部注入字段 + 正文。"""

    @abstractmethod
    def control(self, code: int):
        """控制接口：仅传五位控制码。"""

    @abstractmethod
    def get_model_info(self):
        """模型参数对外信息。"""


class MentalCore(MentalCoreSlotPort):
    """cpu 核心：编排一轮对话，驱动各面与中间件。"""

    def __init__(self, persona: CharacterCard, llm, storage_path: str = "mental_core_demo/.data"):
        self.persona = persona
        self.llm = llm
        self.assembler = PromptAssembler()
        self.splitter = ReplySplitter()
        self.storage = StorageFace(storage_path)
        self.faces = [
            PersonaFace(), MemoryFace(), EmotionFace(),
            WeaveFace(), RhythmFace(),
        ]
        self.history = self.storage.load_history()
        self.inbound_queue: list = []
        self.last_manifest: list = []

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
        """
        emotion_vec = self._detect_emotion(text)
        modules = self._collect_modules(text)
        external = "\n".join(q.get("body", "") for q in self.inbound_queue)
        prompt = self._assemble(modules, text, external)
        buf = []
        for chunk in self.llm.stream(prompt):
            buf.append(chunk)
            yield {"type": "body", "text": chunk}
        raw = "".join(buf)
        body, out_fields, consumed = self.splitter.split(raw)
        self._settle(consumed)
        self._persist(text, body)
        self.inbound_queue.clear()
        self.last_manifest = self.assembler.manifest()
        yield {
            "type": "done", "body": body, "fields": out_fields,
            "manifest": self.last_manifest, "emotion": emotion_vec,
        }

    def receive(self, fields: dict, body: str):
        """向内传输：外部注入字段 + 正文，入队供后续轮参考。"""
        self.inbound_queue.append({"fields": fields or {}, "body": body})
        return {"ok": True, "note": "已接收外部注入"}

    def control(self, code: int):
        """控制接口：解析五位控制码，交由储存面处理 inbound。"""
        parsed = ControlCode(code)
        resp_code, msg = self.storage.handle_control(parsed)
        return {
            "code": parsed.describe(),
            "response": msg,
            "response_code": resp_code.code if resp_code else None,
        }

    def get_model_info(self):
        return self.llm.model_info()

    def _detect_emotion(self, text: str):
        emotion_face = self.faces[2]
        return emotion_face.detect_emotion(text, self.llm)

    def _collect_modules(self, text: str):
        ctx = FaceContext(
            user_text=text, persona=self.persona, history=self.history,
            now=datetime.now(),
        )
        modules = []
        for face in self.faces:
            module = face.produce_module(ctx)
            if module is not None:
                modules.append(module)
        return modules

    def _assemble(self, modules, text: str, external: str = "") -> str:
        prompt = self.assembler.assemble(modules)
        ext_block = f"\n【外部注入上下文】{external}\n" if external else ""
        return f"{prompt}{ext_block}\n\n用户说：{text}\n{self.persona.name}："

    def _settle(self, consumed: dict):
        emotion_face = self.faces[2]
        emotion_face.settle(consumed.get("affinity_delta"))

    def _persist(self, text: str, body: str):
        self.history.append({"user": text, "assistant": body})
        self.storage.save_turn(text, body)
        # 记忆向量归档落盘（防污染链路可清除）
        self.storage.save_vector_record(text)

    def update_persona(self, **fields):
        """防污染删除链路（§6.3）：修改人设 → 清聊天记录 + 清向量归档。

        按设计原话不含核心记忆（demo 无独立核心记忆画像文件）。
        """
        for k, v in fields.items():
            if hasattr(self.persona, k):
                setattr(self.persona, k, v)
        self.storage.clear_records()
        self.storage.clear_vectors()
        self.history = []
        return {
            "ok": True,
            "note": "已修改人设并清空聊天记录与向量归档（核心记忆未清除）",
            "changed": list(fields.keys()),
        }

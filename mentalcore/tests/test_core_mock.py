"""核心全流程离线测试：用 MockLLM 跑通编排、控制码、防污染清档。

不依赖 palm / 网络 / 密钥；验证架构接线正确性。
"""
import os
import tempfile

from mentalcore.core import MentalCore
from mentalcore.llm import MockLLM
from mentalcore.crypto_provider import CryptoProvider
from mentalcore.faces.storage import StorageFace
from mentalcore.persona_card import CharacterCard


class _StubSem:
    """语义记忆桩：不可用，保证 MemoryFace 退化为仅近期对话。"""
    available = False

    def add(self, *a, **k):
        return None

    def search(self, *a, **k):
        return []

    def count(self):
        return 0

    def clear(self):
        pass


def _build(tmp):
    persona = CharacterCard(
        id="mengyao", name="梦瑶", tagline="陪你说话的伙伴",
        personality_pillars=["温柔"], flaws=["吃醋"], tone="温柔轻快",
        dynamic_updates_enabled=True, affinity_enabled=True,
    )
    crypto = CryptoProvider(enabled=False)  # 离线明文降级
    storage = StorageFace(path=tmp, crypto=crypto, semantic_memory=_StubSem())
    llm = MockLLM(persona_name="梦瑶", tone="温柔轻快")
    return MentalCore(
        persona=persona, llm=llm, crypto=crypto,
        semantic_memory=_StubSem(), storage=storage,
    )


def test_stream_message_flow():
    with tempfile.TemporaryDirectory() as tmp:
        core = _build(tmp)
        done = None
        for ev in core.stream_message("今天有点难过"):
            if ev["type"] == "done":
                done = ev
        assert done is not None
        assert done["body"]
        assert "affinity_delta" in done["manifest"] or "persona" in [
            m["source"] for m in done["manifest"]
        ]
        # 好感度 delta 应为消费字段，不出现在外发字段
        assert "affinity_delta" not in done["fields"]


def test_control_codes():
    with tempfile.TemporaryDirectory() as tmp:
        core = _build(tmp)
        core.stream_message("嗨")
        assert "记录数" in core.control(10000)["response"]
        assert "已清空对话记录" in core.control(10100)["response"]
        assert "记录数：0" in core.control(10000)["response"]
        assert "向量归档" in core.control(11000)["response"]
        assert "明文降级" in core.control(13000)["response"]


def test_receive_and_persona_clear():
    with tempfile.TemporaryDirectory() as tmp:
        core = _build(tmp)
        core.stream_message("第一句")
        assert core.receive({"mood": "开心"}, "外部")["ok"] is True
        res = core.update_persona(tone="冷淡")
        assert res["ok"] is True
        # 改人设清空记录后，记录数归零
        assert "记录数：0" in core.control(10000)["response"]

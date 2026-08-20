"""语义记忆适配器测试：验证降级韧性（chromadb/Ollama 缺失不崩）。"""
import tempfile

from mentalcore.semantic_memory import SemanticMemory


def test_degrade_does_not_raise():
    with tempfile.TemporaryDirectory() as tmp:
        sm = SemanticMemory(tmp)
        # 不论可用与否，add/search/count/clear 都不应抛异常
        sm.add("用户喜欢猫娘")
        results = sm.search("用户喜欢什么", top_k=3)
        assert isinstance(results, list)
        assert isinstance(sm.count(), int)
        sm.clear()  # 幂等，不抛


def test_availability_flag_exists():
    with tempfile.TemporaryDirectory() as tmp:
        sm = SemanticMemory(tmp)
        assert hasattr(sm, "available")
        assert isinstance(sm.available, bool)

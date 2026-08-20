"""注入中间件测试：固定在上、动态在下、不可用即不注入、清单留痕。"""
from mentalcore.middleware.inject import InjectionModule, PromptAssembler


def test_assemble_order_and_manifest():
    asm = PromptAssembler()
    fixed = InjectionModule(source="persona", content="静态设定", fixed=True, priority=10)
    dyn = InjectionModule(source="memory", content="近期对话", fixed=False, priority=20)
    prompt = asm.assemble([fixed, dyn])
    assert prompt.index("静态设定") < prompt.index("近期对话")
    man = asm.manifest()
    assert man[0]["source"] == "persona" and man[0]["fixed"] is True
    assert man[1]["source"] == "memory"


def test_assemble_skips_unavailable():
    asm = PromptAssembler()
    ok = InjectionModule(source="a", content="有内容", available=True)
    bad = InjectionModule(source="b", content="", available=False)
    prompt = asm.assemble([ok, bad])
    assert "有内容" in prompt
    assert asm.manifest() == [{"source": "a", "fixed": False, "tokens": 1}]

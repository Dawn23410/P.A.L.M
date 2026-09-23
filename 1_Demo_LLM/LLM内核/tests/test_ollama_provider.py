"""palm_llm.providers.OllamaProvider 测试（原生 /api/chat）。

设计：
- **纯逻辑用例不依赖 ollama 在跑**（注册表 / 思考翻译 / 载荷构造 / tool_calls 归一）；
- **联调用例**在 ollama 不可达时整体跳过（打印 SKIP，不判失败），避免无服务时误报红；
- 不依赖 pytest-asyncio：每个用例是同步函数，内部自行 `asyncio.run`，
  因此 `pytest test_ollama_provider.py` 与 `python test_ollama_provider.py` 都能跑。

运行（需要 httpx + pydantic，即 palm_llm 自身的依赖）：
    D:/P.A.L.M/1_Demo_LLM/RAG/.bench_venv/Scripts/python.exe tests/test_ollama_provider.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from palm_llm import (  # noqa: E402
    Message,
    ModelParameters,
    OllamaProvider,
    OpenAICompatProvider,
    ProviderConfig,
    get_provider_instance,
)
from palm_llm.providers.ollama import (  # noqa: E402
    _normalize_tool_calls,
    _resolve_think,
    _tool_stats,
    _usage,
)
from palm_llm.providers._telemetry import Meter  # noqa: E402

BASE = "http://127.0.0.1:11434"
PREFER_MODEL = "spark-x2.5:1.7b"


def _cfg(**kw) -> ProviderConfig:
    kw.setdefault("name", "ollama")
    kw.setdefault("type", "ollama")
    kw.setdefault("base_url", BASE)
    return ProviderConfig(**kw)


def _provider(**kw) -> OllamaProvider:
    return get_provider_instance(_cfg(**kw))


# ─────────────────────── 纯逻辑：不依赖服务 ───────────────────────

def test_registry() -> None:
    assert isinstance(_provider(), OllamaProvider)
    assert isinstance(_provider(type="ollama_native"), OllamaProvider)
    # 未知 type 回退 openai_compat（容错契约）
    assert isinstance(_provider(type="不存在的协议"), OpenAICompatProvider)
    print("[registry] ollama / ollama_native → OllamaProvider；未知 → OpenAICompatProvider ✅")


def test_base_url_normalization() -> None:
    # 原生根地址原样用；误写 /v1 自动剥掉 —— 老配置不必改也能跑
    assert _provider(base_url=BASE + "/")._chat_url() == BASE + "/api/chat"
    assert _provider(base_url=BASE + "/v1")._chat_url() == BASE + "/api/chat"
    assert _provider(base_url=BASE + "/v1/")._chat_url() == BASE + "/api/chat"
    assert _provider(base_url="")._chat_url() == BASE + "/api/chat"
    print("[base_url] 尾斜杠 / 误写 /v1 / 空值 均归一到原生根地址 ✅")


def test_resolve_think() -> None:
    cases = [
        ({"think": False}, False),
        ({"think": True}, True),
        ({"think": "high"}, "high"),
        ({"reasoning_effort": "none"}, False),      # ollama /v1 上唯一干净的关思考写法
        ({"enable_thinking": False}, False),        # 适配层注释里那个（对 /v1 无效，这里认）
        ({"thinking": False}, False),
        ({"thinking": {"type": "disabled"}}, False),  # 智谱原生写法
        ({}, None),                                   # 未表达 → 不干预模型默认
        ({"think": None}, None),
    ]
    for extra, want in cases:
        got = _resolve_think(extra)
        assert got == want, f"{extra} → {got}，期望 {want}"
    print(f"[think 翻译] {len(cases)} 种写法全部正确 ✅")


def test_build_payload() -> None:
    p = _provider()
    params = ModelParameters(
        temperature=0.3, top_p=0.9, max_tokens=128,
        frequency_penalty=0.1, presence_penalty=0.2,
        extra_body={"reasoning_effort": "none", "keep_alive": "5m"},
    )
    payload = p._build_payload([Message(role="user", content="hi")], params, "m", True)
    # OpenAI 参数名 → ollama options（max_tokens 在原生协议里叫 num_predict）
    assert payload["options"] == {
        "temperature": 0.3, "top_p": 0.9, "num_predict": 128,
        "frequency_penalty": 0.1, "presence_penalty": 0.2,
    }, payload["options"]
    assert payload["think"] is False, "reasoning_effort=none 应翻译为原生 think=False"
    assert payload["keep_alive"] == "5m", "非思考类的 extra_body 键应顶层透传"
    assert "reasoning_effort" not in payload, "已消费的思考控制键不应外泄给服务端"
    assert payload["messages"] == [{"role": "user", "content": "hi"}]
    print("[载荷] options 映射 + think 翻译 + 其余键透传 + 思考键不外泄 ✅")


def test_normalize_tool_calls() -> None:
    raw = [{"function": {"name": "get_weather", "arguments": {"city": "北京"}}}]
    out = _normalize_tool_calls(raw)
    assert out[0]["index"] == 0 and out[0]["id"] == "call_0"
    assert out[0]["type"] == "function"
    # 原生给的是 dict，OpenAI 约定要 JSON 字符串
    assert isinstance(out[0]["function"]["arguments"], str)
    assert json.loads(out[0]["function"]["arguments"]) == {"city": "北京"}
    # 已经是字符串则不动
    out2 = _normalize_tool_calls([{"id": "x", "function": {"name": "f", "arguments": "{}"}}])
    assert out2[0]["id"] == "x" and out2[0]["function"]["arguments"] == "{}"
    assert _normalize_tool_calls(None) is None and _normalize_tool_calls([]) is None
    print("[tool_calls] dict→JSON 字符串 / id 补全 / 空值处理 ✅")


def test_usage_mapping() -> None:
    u = _usage({"prompt_eval_count": 21, "eval_count": 2,
                "load_duration": 7_200_000, "prompt_eval_duration": 24_400_000,
                "eval_duration": 10_200_000, "total_duration": 56_500_000})
    assert u["prompt_tokens"] == 21 and u["completion_tokens"] == 2 and u["total_tokens"] == 23
    assert u["load_ms"] == 7.2 and u["prompt_eval_ms"] == 24.4 and u["eval_ms"] == 10.2
    assert _usage({})["total_tokens"] == 0 and _usage({})["load_ms"] == 0.0
    print("[usage] 计数 + 纳秒→毫秒分段耗时映射 ✅")


def test_tool_stats_normalizes_finish_reason() -> None:
    """ollama 原生在工具调用时 done_reason 仍是 stop —— 收尾统计要归一为 tool_calls。

    否则调用方按 finish_reason 分支时工具会静默不执行（实测 0.34.x）。
    """
    obj = {"done_reason": "stop", "prompt_eval_count": 5, "eval_count": 3}
    plain = _tool_stats(obj, Meter(), has_calls=False)
    assert plain["finish_reason"] == "stop", plain["finish_reason"]

    with_calls = _tool_stats(obj, Meter(), has_calls=True)
    assert with_calls["finish_reason"] == "tool_calls", with_calls["finish_reason"]
    assert with_calls["extra"]["finish_reason_vendor"] == "stop", with_calls["extra"]
    print("[收尾归一] 有工具调用时 stop → tool_calls，原值留存 ✅")


# ─────────────────────── 联调：需要 ollama 在跑 ───────────────────────
# 返回 True 表示"服务在、可以继续"；False 表示整体跳过。

async def _ready() -> bool:
    """服务在跑且装了模型才继续；否则打印 SKIP（不判失败）。"""
    try:
        models = await _provider().list_models()
    except Exception as exc:  # noqa: BLE001
        print(f"SKIP: ollama 不可达（{type(exc).__name__}: {exc}）")
        return False
    if not models:
        print(f"SKIP: {BASE} 无可用模型（ollama 未启动 / 未 pull 模型）")
        return False
    return True


def _model(cands: list[str]) -> str:
    return PREFER_MODEL if PREFER_MODEL in cands else (cands[0] if cands else PREFER_MODEL)


def _live(coro_factory) -> None:
    """跑一个联调用例：独占事件循环，收尾关闭复用的 HTTP 客户端。

    不关客户端会在进程退出时冒出 "Event loop is closed" 噪声
    （Windows 上尤其吵，会掩盖真实断言失败）。
    """
    from palm_llm.providers.base import close_client

    async def wrapper():
        try:
            return await coro_factory()
        finally:
            await close_client()

    asyncio.run(wrapper())


async def _chat(p, model, prompt, extra, stream=True, max_tokens=64):
    t0 = time.perf_counter()
    first, txt, th, usage, err = None, [], [], None, ""
    params = ModelParameters(max_tokens=max_tokens, temperature=0.7, extra_body=extra)
    try:
        async for ev in p.complete([Message(role="user", content=prompt)], params, model, stream=stream):
            if first is None and ("content" in ev or "reasoning" in ev):
                first = (time.perf_counter() - t0) * 1000
            txt.append(ev.get("content", ""))
            th.append(ev.get("reasoning", ""))
            if "done" in ev:
                usage = ev.get("usage")
    except Exception as exc:  # noqa: BLE001
        err = f"{type(exc).__name__}: {exc}"
    return {"first_ms": first, "content": "".join(txt), "reasoning": "".join(th),
            "usage": usage, "error": err}


def test_live_think_off() -> None:
    async def run():
        p = _provider()
        if not await _ready():
            return
        model = _model(await p.list_models())
        await p.prewarm()
        r = await _chat(p, model, "只回答两个字：你好", {"think": False})
        print(f"[联调 think=False] model={model} 首事件={r['first_ms']:.0f}ms "
              f"正文={r['content']!r} 思维链={len(r['reasoning'])}字 usage={r['usage']}")
        assert not r["error"], r["error"]
        assert r["content"].strip(), "正文为空 —— 关思考下不该发生"
        assert not r["reasoning"].strip(), "think=False 却出现思维链"
        assert r["usage"] and r["usage"]["completion_tokens"], f"usage 计数缺失: {r['usage']}"
        assert "load_ms" in r["usage"] and "eval_ms" in r["usage"], "缺少分段耗时"
    _live(run)


def test_live_think_default() -> None:
    """不传思考开关 → 沿用模型模板默认（spark 默认开思考），思维链应落在 reasoning。"""
    async def run():
        p = _provider()
        if not await _ready():
            return
        model = _model(await p.list_models())
        r = await _chat(p, model, "1+1=? 直接给答案", None, max_tokens=256)
        print(f"[联调 think=默认] 正文={len(r['content'])}字 思维链={len(r['reasoning'])}字")
        assert not r["error"], r["error"]
        # spark-x2.5:1.7b 默认开思考；若换成非思考模型，这里不强制断言
        if not r["reasoning"]:
            print("    （该模型未输出思维链，可能是非思考模型 —— 不作为失败）")
    _live(run)


def test_live_non_stream() -> None:
    async def run():
        p = _provider()
        if not await _ready():
            return
        model = _model(await p.list_models())
        r = await _chat(p, model, "只回答两个字：你好", {"think": False}, stream=False)
        print(f"[联调 非流式] 正文={r['content']!r} usage={r['usage']}")
        assert not r["error"], r["error"]
        assert r["content"].strip(), "非流式正文为空"
        assert (r["usage"] or {}).get("completion_tokens"), "非流式 usage 缺失"
    _live(run)


def test_live_openai_compat_reasoning_field() -> None:
    """回归：走 /v1 兼容层时，ollama 的 `reasoning` 字段必须被接收（曾只认 reasoning_content）。"""
    async def run():
        p = _provider()
        if not await _ready():
            return
        model = _model(await p.list_models())
        v1 = get_provider_instance(ProviderConfig(
            name="ollama-v1", type="openai_compat", base_url=BASE + "/v1", api_key="ollama"))
        r = await _chat(v1, model, "1+1=? 直接给答案", None, max_tokens=256)
        print(f"[联调 /v1 字段兼容] 思维链={len(r['reasoning'])}字 正文={r['content'][:40]!r}")
        assert not r["error"], r["error"]
        if not r["reasoning"]:
            print("    （未输出思维链，可能是非思考模型 —— 不作为失败）")
    _live(run)


def test_live_fail_closed() -> None:
    """坏端口：应把失败暴露成 RuntimeError（被 _chat 收进 error），而不是静默返回空。"""
    async def run():
        p = _provider(base_url="http://127.0.0.1:59999")
        r = await _chat(p, "whatever", "hi", {"think": False}, max_tokens=8)
        print(f"[fail-closed] error={r['error']}")
        assert r["error"], "坏端点未报错（应 fail-closed）"
        assert "连接失败" in r["error"], f"错误信息不够明确：{r['error']}"
    _live(run)


def test_live_discovery() -> None:
    async def run():
        from palm_llm.server.discovery import discover_models
        p = _provider()
        if not await _ready():
            return
        names = await discover_models("ollama", BASE, "")
        names_v1 = await discover_models("ollama", BASE + "/v1", "")   # 误写也要能用
        print(f"[discovery] 原生根={names} 误写/v1={names_v1}")
        assert names and names == names_v1
        try:
            await discover_models("ollama", "http://127.0.0.1:59999", "")
            raise AssertionError("坏地址未报错")
        except ValueError as e:
            print(f"    坏地址报错可读：{e}")
    _live(run)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        PREFER_MODEL = sys.argv[1]
    test_registry()
    test_base_url_normalization()
    test_resolve_think()
    test_build_payload()
    test_normalize_tool_calls()
    test_usage_mapping()
    test_tool_stats_normalizes_finish_reason()
    test_live_think_off()
    test_live_think_default()
    test_live_non_stream()
    test_live_openai_compat_reasoning_field()
    test_live_fail_closed()
    test_live_discovery()
    print("\nALL PASS")

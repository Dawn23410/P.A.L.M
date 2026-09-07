"""工具调用层集成测试（确定性，fail-closed 验证）。

覆盖：
- 匹配路由：时间/日期/天气走工具；闲聊不误伤；知识 OOD 仍诚实兜底。
- 时间/日期：网络授时优先，没网/超时直接本机（source 字段诚实披露）。
- 天气：真实网络查询 + TTL 预缓存（重复查询不重复联网）+ 断网陈旧缓存兜底 + 无缓存诚实降级。
- 引擎分发：经 engine.respond 正确路由到 tool 模式且 recall_real=True。
- 双模式（mock/semantic）下工具分发均正常。

直接 `python test_tools.py` 运行（系统 Python 即可，tools 层纯标准库）。
"""
import sys
import os
import json
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from local_reply.engine import tools as _tools
from local_reply import StitchEngine


def _mock_offline():
    """模拟断网：让 urlopen 抛异常。"""
    orig = urllib.request.urlopen

    def _boom(*a, **k):
        raise OSError("simulated offline")

    urllib.request.urlopen = _boom
    return orig


class _FakeResp:
    """可当上下文管理器用的假响应（urllib urlopen 返回对象）。"""
    def __init__(self, data):
        self._d = data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._d


_WEATHER_JSON = json.dumps({
    "current": {
        "temperature_2m": 20.0, "relative_humidity_2m": 50,
        "weather_code": 1, "wind_speed_10m": 3.0,
    }
}).encode("utf-8")


def test_match_routing():
    """匹配路由：工具意图命中，闲聊/知识不误伤。"""
    reg = _tools.ToolRegistry()
    # 应命中工具
    tool_cases = [
        "现在几点了", "今天几号", "今天星期几",
        "北京天气怎么样", "上海气温多少度", "纽约天气",
        "东京明天天气", "明天天气", "后天天气",
    ]
    for q in tool_cases:
        assert reg.dispatch(q) is not None, f"应命中工具: {q!r}"
    # 不应命中（闲聊/知识）
    chat_cases = [
        "今天天气真好呀", "你人真好", "我好难过", "今天天气不错",
        "推荐一部好看的科幻电影", "帮我写个 python 爬虫", "1+1 等于几",
    ]
    for q in chat_cases:
        assert reg.dispatch(q) is None, f"不应命中工具: {q!r}"
    print("[OK] test_match_routing")


def test_time_date_local():
    """时间/日期确定性产出 + 结构化 data（含 source 字段，network 或 local 均可）。"""
    reg = _tools.ToolRegistry()
    for q in ["现在几点了", "今天几号", "今天星期几"]:
        r, t = reg.dispatch(q)
        assert r.ok, f"工具应成功: {q!r}"
        out = reg.format(r, t, q)
        assert out, f"应产出文本: {q!r}"
        assert r.data.get("type") in ("time", "date"), f"应带结构化 type: {r.data}"
        assert r.data.get("source") in ("network", "local"), f"应诚实披露来源: {r.data}"
        assert 0 <= r.data.get("hour", -1) < 24 if r.data.get("type") == "time" else True
        assert any(ch.isdigit() for ch in out), f"应含数字: {out!r}"
    print("[OK] test_time_date_local")


def test_time_date_offline_fallback():
    """断网时时间/日期直接读取本机，仍成功且 source==local（fail-closed）。"""
    orig = _mock_offline()
    try:
        reg = _tools.ToolRegistry()
        for q in ["现在几点了", "今天几号"]:
            r, t = reg.dispatch(q)
            assert r.ok, f"断网仍应成功(本机兜底): {q!r}"
            assert r.data.get("source") == "local", f"断网应标 local: {r.data}"
    finally:
        urllib.request.urlopen = orig
    print("[OK] test_time_date_offline_fallback")


def test_weather_network():
    """天气真实网络查询（联网时有数据，失败降级）。"""
    reg = _tools.ToolRegistry()
    r, t = reg.dispatch("北京天气怎么样")
    assert t.name == "weather"
    out = reg.format(r, t, "北京天气怎么样")
    if r.ok:
        assert "度" in out, f"应含温度: {out!r}"
        print("[OK] test_weather_network (online, 有数据)")
    else:
        # 没网 → 诚实降级，不算失败
        assert "连不上网" in out, f"应诚实降级: {out!r}"
        print("[OK] test_weather_network (offline, fail-closed 降级)")


def test_weather_offline_failclosed():
    """断网 → 诚实降级，绝不瞎编温度。"""
    orig = _mock_offline()
    try:
        wt = _tools.WeatherTool()
        r = wt.execute("北京天气怎么样")
        assert not r.ok, "断网应 ok=False"
        out = wt.format(r, "北京天气怎么样")
        assert "连不上网" in out and "瞎编" in out, f"应诚实降级: {out!r}"
    finally:
        urllib.request.urlopen = orig
    print("[OK] test_weather_offline_failclosed")


def _mock_response(json_bytes):
    """注入假网络响应，返回 (orig, calls计数器)。"""
    orig = urllib.request.urlopen
    calls = {"n": 0}

    def _fake(*a, **k):
        calls["n"] += 1
        return _FakeResp(json_bytes)

    urllib.request.urlopen = _fake
    return orig, calls


def test_weather_cache_no_repeat_fetch():
    """重复查询同城市+日期 → 走 TTL 预缓存，不重复联网（秒回）。"""
    orig, calls = _mock_response(_WEATHER_JSON)
    try:
        wt = _tools.WeatherTool()
        r1 = wt.execute("北京天气怎么样")
        assert r1.ok, "首次应联网成功"
        assert calls["n"] == 1, f"首次应联网 1 次, got {calls['n']}"
        r2 = wt.execute("北京天气怎么样")
        assert r2.ok, "二次应命中缓存"
        assert calls["n"] == 1, f"缓存命中应不重复联网, got {calls['n']}"
        out = wt.format(r2, "北京天气怎么样")
        assert "度" in out, f"应含温度: {out!r}"
    finally:
        urllib.request.urlopen = orig
    print("[OK] test_weather_cache_no_repeat_fetch")


def test_weather_stale_fallback():
    """联网失败但有陈旧缓存 → 兜底返回 ok=True 且 stale=True（不瞎编、披露来源）。"""
    orig = urllib.request.urlopen
    def _boom(*a, **k):
        raise OSError("simulated offline")
    urllib.request.urlopen = _boom
    try:
        wt = _tools.WeatherTool()
        # 预填一个过期缓存（模拟先前成功查询的残留）
        stale = _tools.ToolResult(True, {
            "type": "weather", "city": "北京", "day_label": "今天",
            "temp": 25.0, "humidity": 40, "wind": 2.0, "desc": "晴",
            "defaulted": False,
        })
        wt._cache[("北京", 0)] = (time.time() - 9999, stale)
        r = wt.execute("北京天气怎么样")
        assert r.ok, "陈旧缓存应兜底成功"
        assert r.data.get("stale") is True, f"应标 stale: {r.data}"
        out = wt.format(r, "北京天气怎么样")
        assert "缓存" in out or "偏差" in out, f"应披露陈旧: {out!r}"
    finally:
        urllib.request.urlopen = orig
    print("[OK] test_weather_stale_fallback")


def test_engine_dispatch():
    """经 engine.respond 正确路由到 tool 模式 + 四要素人格化包装。"""
    eng = StitchEngine()
    tool_q = ["现在几点了", "今天几号", "北京天气怎么样"]
    for q in tool_q:
        r = eng.respond(q, [])
        assert r.get("mode") == "tool", f"应走 tool 模式: {q!r} -> {r.get('mode')}"
        assert r["recall_real"] is True, f"工具回复应 recall_real=True: {q!r}"
        # 引擎层四要素人格化包装：[动作]（神态）<内心>
        assert r["reply"].startswith("[") and "（" in r["reply"] and "<" in r["reply"], \
            f"应四要素包装: {r['reply']!r}"
    # 闲聊不被工具吞
    r = eng.respond("今天天气真好呀", [])
    assert r.get("mode") != "tool", "闲聊不应走 tool"
    print("[OK] test_engine_dispatch")


def test_engine_semantic_dispatch():
    """语义模式（semantic=True）下工具分发同样正常。"""
    eng = StitchEngine(semantic=True)
    r = eng.respond("现在几点了", [])
    assert r.get("mode") == "tool", f"语义模式应走 tool: {r.get('mode')}"
    r2 = eng.respond("今天天气真好呀", [])
    assert r2.get("mode") != "tool", "语义模式闲聊不应走 tool"
    print("[OK] test_engine_semantic_dispatch")


def run_all():
    t0 = time.time()
    test_match_routing()
    test_time_date_local()
    test_time_date_offline_fallback()
    test_weather_network()
    test_weather_offline_failclosed()
    test_weather_cache_no_repeat_fetch()
    test_weather_stale_fallback()
    test_engine_dispatch()
    test_engine_semantic_dispatch()
    print(f"\n全部通过 ✅ 用时 {round(time.time()-t0, 1)}s")


if __name__ == "__main__":
    run_all()

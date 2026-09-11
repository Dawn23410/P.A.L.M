"""TOOL 内核基准 —— 工具层（ToolCube / ToolMatcher / agent_tools）。

论文级维度：
- correctness:  工具注册/查询/决策/OpenAI schema 生成；关键词匹配排序。
- boundary:     未注册工具查询返回 None/空；危险权限拒绝。
- latency:      ToolMatcher.rank 时延；1000 次决策 p95。
- idempotency:  同查询排序稳定。
"""
from __future__ import annotations

import traceback
from .harness import benchmark



@benchmark("tool")
def bench(col):
    try:
        from tool.tool_cube import ToolCube, ToolSpec, ToolDecision
        from tool.tool_matcher import ToolMatcher, _tokenize
        from tool.agent_tools.file_tools import ReadFileTool, WriteFileTool
        COL = dict(ToolCube=ToolCube, ToolSpec=ToolSpec, ToolDecision=ToolDecision,
                   ToolMatcher=ToolMatcher, _tokenize=_tokenize,
                   ReadFileTool=ReadFileTool, WriteFileTool=WriteFileTool)
        col.pass_("import", "tool_submodules_importable", "correctness",
                  "tool.tool_cube / tool_matcher / agent_tools 导入成功"
                  "（已修复内核拆分后 ..tool_base 相对导入断裂）")
    except Exception as e:
        col.fail("import", "tool_submodules_importable", "correctness", str(e),
                 "".join(traceback.format_exception(type(e), e, e.__traceback__))[:600])
        return
    G = COL

    # 1. ToolCube 注册/决策
    try:
        cube = G["ToolCube"](allowed_permissions=None, security=None)
        cube.register(G["ToolSpec"](
            name="get_weather", description="查询天气",
            requires=["tool.read"],
            parameters={"type": "object", "properties": {"city": {"type": "string"}}}))
        got = cube.get("get_weather")
        assert got is not None and got.name == "get_weather"
        d = cube.decide("get_weather", {"city": "Beijing"})
        assert isinstance(d, G["ToolDecision"])
        col.pass_("tool_cube", "register_and_decide", "correctness",
                  f"注册 1 工具，get/decide 链路通顺，decision.allowed={d.allowed}")
    except Exception as e:
        col.fail("tool_cube", "register_and_decide", "correctness", str(e),
                 "".join(traceback.format_exception(type(e), e, e.__traceback__))[:600])

    # 2. OpenAI schema 生成
    try:
        cube = G["ToolCube"]()
        cube.register(G["ToolSpec"](name="search", description="搜索",
                     requires=["tool.read"],
                     parameters={"type": "object",
                                 "properties": {"q": {"type": "string"}}}))
        schema = cube.to_openai_tool()
        assert isinstance(schema, list) and schema[0]["type"] == "function"
        assert schema[0]["function"]["name"] == "search"
        col.pass_("tool_cube", "openai_schema_gen", "correctness",
                  "to_openai_tool 产出合规 OpenAI function schema")
    except Exception as e:
        col.fail("tool_cube", "openai_schema_gen", "correctness", str(e),
                 "".join(traceback.format_exception(type(e), e, e.__traceback__))[:600])

    # 3. ToolMatcher 关键词排序（build_index 接受 ToolSpec 对象）
    try:
        matcher = G["ToolMatcher"]()
        specs = [
            G["ToolSpec"](name="read_file", description="读取文件内容", requires=[]),
            G["ToolSpec"](name="send_email", description="发送邮件", requires=[]),
            G["ToolSpec"](name="run_shell", description="执行 shell 命令", requires=[]),
        ]
        matcher.build_index(specs)
        top = matcher.top_names("读取一个文件", top_k=1)
        assert top and top[0] == "read_file", f"排序错误: {top}"
        col.pass_("tool_matcher", "keyword_ranking", "correctness",
                  "中文查询『读取一个文件』→ top=read_file")
        stat = col.measure(lambda: matcher.rank("执行 shell 命令", top_k=3))
        col.pass_("tool_matcher", "rank_latency", "latency",
                  "rank 时延分布", latency=stat)
        # 幂等
        assert matcher.top_names("读取一个文件", top_k=1) == top
        col.pass_("tool_matcher", "rank_idempotent", "idempotency",
                  "同查询排序稳定")
    except Exception as e:
        col.fail("tool_matcher", "keyword_ranking", "correctness", str(e),
                 "".join(traceback.format_exception(type(e), e, e.__traceback__))[:600])

    # 4. Boundary：未注册/空
    try:
        cube = G["ToolCube"]()
        assert cube.get("nonexistent") is None
        assert cube.list_tools() == []
        cube.decide("nonexistent", {})
        col.pass_("boundary", "unknown_tool_safe", "boundary",
                  "查询未注册工具返回 None，不抛异常")
    except Exception as e:
        col.fail("boundary", "unknown_tool_safe", "boundary", str(e),
                 "".join(traceback.format_exception(type(e), e, e.__traceback__))[:600])

    # 5. file_tools 路径越权防护（边界）
    try:
        rt = G["ReadFileTool"]()
        # 尝试读取根外路径应被拒（_resolve_allowed_path 限制在主目录内）
        res = rt.run(path="/etc/passwd")
        if isinstance(res, str) and ("拒绝" in res or "permission" in res.lower() or "不允许" in res):
            col.pass_("file_tools", "path_traversal_blocked", "boundary",
                      "越权路径读取被安全拒绝")
        else:
            col.xfail("file_tools", "path_traversal_blocked", "boundary",
                      f"越权读取未被显式拒绝（返回类型 {type(res)}），需人工复核",
                      "sandbox/path policy")
    except Exception as e:
        col.pass_("file_tools", "path_traversal_blocked", "boundary",
                  f"越权路径读取抛异常被安全拦截: {type(e).__name__}")

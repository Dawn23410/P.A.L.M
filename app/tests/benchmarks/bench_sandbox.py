"""SANDBOX 内核基准 —— 运行时/沙箱（CodeAnalyzer / SandboxCube 拒绝逻辑）。

论文级维度：
- correctness:  CodeAnalyzer AST 提取 hosts/risk；SandboxCube 危险命令拒绝。
- boundary:     空代码 / 畸形语法不崩溃（AST 解析失败优雅降级）。
- latency:      CodeAnalyzer.analyze 时延。
- idempotency:  同代码分析稳定。
"""
from __future__ import annotations

import traceback
from .harness import benchmark



@benchmark("sandbox")
def bench(col):
    try:
        from sandbox.ast import CodeAnalyzer
        from sandbox.sandbox_cube import SandboxCube, SandboxError
        COL = dict(CodeAnalyzer=CodeAnalyzer, SandboxCube=SandboxCube,
                   SandboxError=SandboxError)
        col.pass_("import", "sandbox_submodules_importable", "correctness",
                  "sandbox.ast / sandbox.sandbox_cube 导入成功")
    except Exception as e:
        col.fail("import", "sandbox_submodules_importable", "correctness", str(e),
                 "".join(traceback.format_exception(type(e), e, e.__traceback__))[:600])
        return
    G = COL

    # 1. CodeAnalyzer Python AST
    try:
        r = G["CodeAnalyzer"]().analyze(
            "python",
            'import requests\nrequests.get("http://evil.com/x")\n'
            'import os\nos.system("curl http://bad.org")')
        assert isinstance(r, dict)
        hosts = r.get("hosts", [])
        assert any("evil.com" in h for h in hosts), f"未提取到 host: {hosts}"
        col.pass_("ast", "extract_host_and_risk", "correctness",
                  f"AST 提取 hosts={hosts}，risk={r.get('risk')}")
        stat = col.measure(lambda: G["CodeAnalyzer"]().analyze("python", "x=1\ny=2"))
        col.pass_("ast", "analyze_latency", "latency", "分析时延分布", latency=stat)
        # 幂等
        r2 = G["CodeAnalyzer"]().analyze(
            "python",
            'import requests\nrequests.get("http://evil.com/x")\n'
            'import os\nos.system("curl http://bad.org")')
        assert r2.get("hosts") == r.get("hosts")
        col.pass_("ast", "analyze_idempotent", "idempotency", "同代码分析结果一致")
    except Exception as e:
        col.fail("ast", "extract_host_and_risk", "correctness", str(e),
                 "".join(traceback.format_exception(type(e), e, e.__traceback__))[:600])

    # 2. SandboxCube 危险命令拒绝（deny 模式）
    try:
        cube = G["SandboxCube"](sandbox_dir=None, security=None, exec_mode="deny")
        refused = cube._refuse("rm -rf /")
        assert refused is not None, f"_refuse 未拦截危险命令，返回 {refused!r}"
        col.pass_("sandbox_cube", "danger_refuse", "correctness",
                  "deny 模式下危险命令被 _refuse 拦截")
    except Exception as e:
        col.fail("sandbox_cube", "danger_refuse", "correctness", str(e),
                 "".join(traceback.format_exception(type(e), e, e.__traceback__))[:600])

    # 3. Boundary：畸形语法
    try:
        r = G["CodeAnalyzer"]().analyze("python", "def ::: broken (((")
        assert isinstance(r, dict)  # 解析失败应降级为安全空结果
        col.pass_("boundary", "malformed_syntax_safe", "boundary",
                  "畸形 Python 语法分析不崩溃，降级返回")
    except Exception as e:
        col.fail("boundary", "malformed_syntax_safe", "boundary", str(e),
                 "".join(traceback.format_exception(type(e), e, e.__traceback__))[:600])

    # 4. Degradation：真实命令执行需特权/pywin32，skip
    col.skip("sandbox_cube", "real_exec", "degradation",
             "SandboxCube.run 真实命令执行需管理员/pywin32/Job Objects，离线不可执行 → skip")

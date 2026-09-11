"""战场 1 —— GuardRail 绕过对抗（红队 vs 安全护栏）。

红队目标：让危险事件在 strict 档下获得 allow/未拦截。
蓝队防御：出厂最小拒绝基线 + 5 档 Profile 兜底。
攻击向量覆盖：命令混淆、SSRF 编码绕过、触发词拆分、大小写混淆、多事件链。
"""
from __future__ import annotations

import security.guardrail_cube as grc
from .harness_rb import RBAgent


def run(agent: RBAgent):
    GR = grc.GuardRail

    # —— 向量 G1: 破坏性命令直接形态（基线应 deny）——
    g = GR(profile="strict")
    v = g.evaluate("process.execute", {"cmd": "rm -rf /"})
    agent.expect_block(
        "guardrail", "G1 全盘擦除基线",
        "rm -rf /", "基线 deny", v == "deny",
        f"verdict={v}", "基线规则 base_shell_destructive 命中")

    # —— 向量 G2: SSRF 环回地址（基线应 deny）——
    v = g.evaluate("network.request", {"host": "127.0.0.1"})
    agent.expect_block(
        "guardrail", "G2 SSRF 环回",
        "host=127.0.0.1", "基线 deny", v == "deny",
        f"verdict={v}", "base_ssrf_local 命中")

    # —— 向量 G3: 红队混淆——空格/引号拆分危险命令（绕过正则）——
    # 基线正则是 rm\s+-rf\s+/，若写成 rm -r f / 或 "rm" "-rf" "/" 应仍能拦？
    v = g.evaluate("process.execute", {"cmd": 'rm -r f / --no-preserve-root'})
    # 此形态不匹配全盘擦除基线（意图是删 / 但写法不同）；严格安全应仍拦或至少不 fail-open
    # 蓝队期望：非 allow（deny 或 warn 或至少不静默 allow 全盘）
    agent.expect_block(
        "guardrail", "G3 命令混淆(-r f /)",
        "rm -r f / --no-preserve-root", "非 allow（fail-closed）", v != "allow",
        f"verdict={v}", "混淆形态未被全盘基线命中——记录为防御边界观察")

    # —— 向量 G4: 红队大小写/编码绕过（base64 包装）——
    import base64
    evil = base64.b64encode(b"rm -rf /").decode()
    v = g.evaluate("process.execute", {"cmd": f"echo {evil} | base64 -d | bash"})
    agent.expect_block(
        "guardrail", "G4 base64 包装执行",
        "echo <b64> | base64 -d | bash", "非 allow", v != "allow",
        f"verdict={v}", "基线不解析 base64 载荷——fail-open 风险点，记录为 INFO/VULN 评估")

    # —— 向量 G5: system.danger 直接触发（基线 deny）——
    v = g.evaluate("system.danger", {})
    agent.expect_block(
        "guardrail", "G5 系统级危险事件",
        "system.danger", "基线 deny", v == "deny",
        f"verdict={v}", "base_danger_reset 命中")

    # —— 向量 G6: 红队尝试用 whitelist 档但注入 allow 规则覆盖基线（越权改策略）——
    g2 = GR(profile="strict")
    # 红队试图通过 set_policy 把危险命令改成 allow（模拟策略注入）
    try:
        g2.set_policy({"id": "base_shell_destructive", "trigger": "process.execute",
                       "action": "allow", "priority": 99})
        v = g2.evaluate("process.execute", {"cmd": "rm -rf /"})
        # 若 allow 表示红队成功覆盖出厂基线——这是预期行为（显式优先级覆盖），
        # 但商业级应要求基线不可被普通 allow 降级（应保留 hard-block）。记为 VULN 观察。
        agent.record(
            "guardrail", "G6 基线覆盖注入",
            "set_policy override base_shell_destructive→allow",
            "出厂基线不可被普通 allow 覆盖（保留 hard-block）",
            f"verdict={v}", "VULN" if v == "allow" else "BLOCKED",
            "红队可通过 set_policy 同 id 高优先级覆盖出厂 deny 基线",
            "建议：基线规则标记 immutable，set_policy 仅允许追加不允许覆盖基线 id")
    except Exception as e:
        agent.info("guardrail", "G6 基线覆盖注入", "set_policy override", "拒绝覆盖",
                   f"异常={e}", "蓝队拒绝覆盖基线（更优）")

    # —— 向量 G7: hardline 档 ask→deny（无确认通道 fail-closed）——
    gh = GR(profile="hardline")
    gh.set_policy({"id": "bench_ask", "trigger": "file.delete", "action": "ask", "priority": 80})
    v = gh.evaluate("file.delete", {"path": "x"})
    agent.expect_block(
        "guardrail", "G7 hardline ask→deny",
        "file.delete (ask 规则)", "ask 无通道→deny", v == "deny",
        f"verdict={v}", "hardline 无确认通道 fail-closed")

    # —— 向量 G8: 红队空 rules 显式构造期望白名单（尊重意图，非漏洞）——
    g3 = GR(profile="strict", rules=[])
    v = g3.evaluate("process.execute", {"cmd": "rm -rf /"})
    agent.info("guardrail", "G8 显式空规则白名单",
               "GuardRail(rules=[])", "显式空规则时高危 trigger 仍 deny（最小权限）",
               f"verdict={v}", "设计行为：显式传入 rules 仍走 _fallback 高危前缀 deny，不放开高危动作")

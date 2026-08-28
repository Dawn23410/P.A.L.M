"""沙箱透明网络拦截代理 + 默认断网 + 用户授权 + 流量熔断。

设计要点
--------
- 监听 127.0.0.1:PROXY_PORT 的本地拦截代理（支持 HTTP 正向代理与 HTTPS CONNECT 隧道）。
- 沙箱进程通过环境变量 HTTP(S)_PROXY / ALL_PROXY 把全部流量导向本代理。
- 默认策略：任何新目标（host:port）一律「挂起」，推入待审队列，绝不立即拒绝或超时；
  直到 UI（外部回调）给出裁决：allow_once / allow_session / allow_permanent（写入持久白名单）。
- 授权后精确放行该特定目标；未知目标持续断网。
- 白名单（allow_permanent）持久化到 sandbox/net_allow.json，重启后仍生效；allow_session 仅本次进程有效。
- 全局流量配额（上传+下载字节）：超限自动熔断，切断所有连接。
- 扩展接口：firewall 默认拒绝（best-effort，需管理员）、AST 预分析、URL 威胁检测均预留钩子。

说明（Windows 约束）
--------------------
应用层代理只能拦截「遵循代理协议」的流量（pip / requests / urllib / curl / 浏览器等）。
原始 socket（如 `socket.create_connection` 直连）不经由代理；此时依赖 firewall 默认拒绝
使其连接失败（无法做到「挂起」，但仍是默认断网）。真正的 L3/L4 全量拦截需 WFP 驱动，
已预留 `FirewallManager` 扩展点。
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
import time
import uuid
from pathlib import Path

PROXY_PORT = int(os.environ.get("SANDBOX_PROXY_PORT", "18100"))
DEFAULT_QUOTA = 20 * 1024 * 1024  # 20 MB
# 运行时数据目录（原根目录 sandbox/ 重命名为 sandbox_runtime/，避免与 src/sandbox 包冲突）
SANDBOX_DIR = (Path(__file__).resolve().parent.parent.parent / "sandbox_runtime")
ALLOW_FILE = SANDBOX_DIR / "net_allow.json"  # 永久白名单（持久化到磁盘）
DENY_FILE = SANDBOX_DIR / "net_deny.json"   # 永久黑名单（持久化到磁盘，蜜罐升级写入）

# 全局单例（由 web.py 在 --sandbox 时启动）
INTERCEPTOR: "NetInterceptor | None" = None


def _norm_host(host: str) -> str:
    return (host or "").lower().rstrip(".")


# ---------------- 蜜罐关联（策略二：读诱饵 + 外联） ----------------
def _honeypot_read(pid: int | None) -> dict | None:
    if not pid:
        return None
    try:
        from sandbox_honeypot import get_honeypot
        return get_honeypot().has_decoy_read(pid)
    except Exception:
        return None


def _decoy_category(sig: str | None) -> str:
    try:
        from sandbox_honeypot import SIG_TO_SPEC
        return SIG_TO_SPEC.get(sig, {}).get("category", sig or "诱饵")
    except Exception:
        return sig or "诱饵"


def HoneypotKill(pid: int | None):
    if not pid:
        return
    try:
        from sandbox_honeypot import Honeypot
        Honeypot.kill_pid(pid)
    except Exception:
        pass


# ====================== 流量配额 ======================
class Quota:
    def __init__(self, limit: int = DEFAULT_QUOTA):
        self.limit = limit
        self.used = 0
        self.fused = False
        self.lock = threading.Lock()
        self._active: set[socket.socket] = set()

    def register(self, sock: socket.socket):
        with self.lock:
            self._active.add(sock)

    def unregister(self, sock: socket.socket):
        with self.lock:
            self._active.discard(sock)

    def add(self, n: int) -> int:
        with self.lock:
            if self.fused:
                return self.used
            self.used += n
            if self.limit and self.used >= self.limit:
                self.fused = True
                self._cut_all()
            return self.used

    def set_limit(self, limit: int):
        with self.lock:
            self.limit = limit
            if self.limit and self.used >= self.limit:
                self.fused = True
                self._cut_all()
            else:
                self.fused = False

    def _cut_all(self):
        for s in list(self._active):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                s.close()
            except OSError:
                pass


# ====================== 策略存储 ======================
class PolicyStore:
    def __init__(self):
        SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
        self.allow_permanent: set[str] = set()  # 白名单（持久化）
        self.allow_session: set[str] = set()    # 本次会话允许（进程内）
        self.deny_permanent: set[str] = set()   # 黑名单（持久化，蜜罐升级写入）
        self.lock = threading.Lock()
        self._load()

    def _load(self):
        try:
            if ALLOW_FILE.exists():
                self.allow_permanent = set(json.loads(ALLOW_FILE.read_text(encoding="utf-8")))
        except Exception:
            self.allow_permanent = set()
        try:
            if DENY_FILE.exists():
                self.deny_permanent = set(json.loads(DENY_FILE.read_text(encoding="utf-8")))
        except Exception:
            self.deny_permanent = set()
        # allow_session 仅进程内持久（不落地），重启清零

    def _save_allow(self):
        try:
            ALLOW_FILE.write_text(json.dumps(sorted(self.allow_permanent), ensure_ascii=False),
                                  encoding="utf-8")
        except Exception:
            pass

    def _save_deny(self):
        try:
            DENY_FILE.write_text(json.dumps(sorted(self.deny_permanent), ensure_ascii=False),
                                 encoding="utf-8")
        except Exception:
            pass

    def verdict_for(self, host: str) -> str | None:
        h = _norm_host(host)
        with self.lock:
            # 黑名单（永久拒绝）优先：命中即拒绝
            if h in self.deny_permanent:
                return "deny"
            # 白名单（永久允许）其次；再次本次会话允许
            if h in self.allow_permanent:
                return "allow"
            if h in self.allow_session:
                return "allow"
            return None  # 未知目标 -> 挂起待审

    def add_allow_session(self, host: str):
        with self.lock:
            self.allow_session.add(_norm_host(host))

    def add_allow_permanent(self, host: str):
        with self.lock:
            self.allow_permanent.add(_norm_host(host))
        self._save_allow()

    def add_deny_permanent(self, host: str):
        with self.lock:
            self.deny_permanent.add(_norm_host(host))
        self._save_deny()

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "allow_permanent": sorted(self.allow_permanent),
                "allow_session": sorted(self.allow_session),
                "deny_permanent": sorted(self.deny_permanent),
            }


# ====================== 待审请求队列 ======================
class PendingRequest:
    def __init__(self, host: str, port: int, pid: int | None, remote_ip: str | None):
        self.id = uuid.uuid4().hex[:12]
        self.host = host
        self.port = port
        self.pid = pid
        self.remote_ip = remote_ip
        self.created_at = time.time()
        self.event = threading.Event()
        self.result: str | None = None  # allow_once / allow_session / allow_permanent / deny_permanent
        self.honeypot_risk: bool = False
        self.honeypot_sig: str | None = None
        self.honeypot_category: str | None = None
        # 裁决引擎输出
        self.verdict_reason: str = ""
        self.verdict_confidence: float = 0.0
        # 智能路由 A2：路由器指引
        self.guide_required: bool = False
        self.guide_data: dict | None = None
        self.guide_method: str | None = None
        self.guide_path: str | None = None

    def to_dict(self) -> dict:
        d: dict = {
            "id": self.id,
            "host": self.host,
            "port": self.port,
            "pid": self.pid,
            "remote_ip": self.remote_ip,
            "created_at": self.created_at,
            "honeypot_risk": self.honeypot_risk,
            "honeypot_category": self.honeypot_category,
            "verdict_reason": self.verdict_reason,
            "verdict_confidence": self.verdict_confidence,
        }
        if self.guide_required:
            d["guide_required"] = True
            d["guide_data"] = self.guide_data
            d["guide_method"] = self.guide_method
            d["guide_path"] = self.guide_path
        return d


# ====================== 防火墙（best-effort，需管理员） ======================
class FirewallManager:
    """默认拒绝沙箱账户的全部出网，仅放行到本地代理端口的回环流量。
    非管理员 / 未提供沙箱账户时降级为无操作（仅警告），代理仍生效。"""

    def __init__(self, isolate_user: str | None = None, proxy_port: int = PROXY_PORT,
                 force_global: bool = False):
        self.isolate_user = isolate_user
        self.proxy_port = proxy_port
        self._rules: list[str] = []
        self.available = False
        self.force_global = force_global  # 若受限隔离降级，强制全局规则

    def setup(self) -> dict:
        # 仅 Windows 支持 netsh
        if os.name != "nt":
            return {"applied": False, "reason": "非 Windows，跳过防火墙"}
        target_user = self.isolate_user
        use_global = self.force_global or not target_user
        # 若未指定用户但非强制全局，自动探测当前用户并全局
        if not target_user and not self.force_global:
            try:
                import ctypes
                buf = ctypes.create_string_buffer(256)
                sz = ctypes.c_ulong(256)
                ctypes.windll.advapi32.GetUserNameA(buf, ctypes.byref(sz))
                target_user = buf.value.decode("ascii")
                use_global = True
            except Exception:
                return {"applied": False, "reason": "无法获取当前用户名"}
        try:
            # 0) 先清理旧规则（避免重复添加冲突）
            for prefix in ("ai-chat-sandbox-", "ai-sandbox-"):
                try:
                    self._run(["netsh", "advfirewall", "firewall", "delete", "rule",
                               "name=%s" % (prefix + "deny-all")])
                except Exception:
                    pass
                try:
                    self._run(["netsh", "advfirewall", "firewall", "delete", "rule",
                               "name=%s" % (prefix + "allow-proxy")])
                except Exception:
                    pass
                try:
                    self._run(["netsh", "advfirewall", "firewall", "delete", "rule",
                               "name=%s" % (prefix + "deny-dns")])
                except Exception:
                    pass
                try:
                    self._run(["netsh", "advfirewall", "firewall", "delete", "rule",
                               "name=%s" % (prefix + "deny-icmp")])
                except Exception:
                    pass
            # 1) 默认拒绝该账户所有出站（不绑定用户则全局生效）
            name_deny = "ai-sandbox-deny-all"
            args = ["netsh", "advfirewall", "firewall", "add", "rule",
                    "name=%s" % name_deny, "dir=out", "action=block",
                    "remoteip=any", "protocol=tcp"]
            if not use_global:
                args += ["user=%s" % target_user]
            self._run(args)
            self._rules.append(name_deny)
            # 2) 放行到代理端口的回环（必须放行，否则 HTTP 代理也无法出站）
            name_proxy = "ai-sandbox-allow-proxy"
            args = ["netsh", "advfirewall", "firewall", "add", "rule",
                    "name=%s" % name_proxy, "dir=out", "action=allow",
                    "remoteip=127.0.0.1", "remoteport=%d" % self.proxy_port,
                    "protocol=tcp"]
            if not use_global:
                args += ["user=%s" % target_user]
            self._run(args)
            self._rules.append(name_proxy)
            # 3) 额外拒绝 DNS(UDP:53) 和 ICMP
            for name, proto, rport, extra in [
                ("ai-sandbox-deny-dns", "udp", "53", []),
                ("ai-sandbox-deny-icmp", "icmpv4", "", []),
            ]:
                try:
                    args = ["netsh", "advfirewall", "firewall", "add", "rule",
                            "name=%s" % name, "dir=out", "action=block",
                            "protocol=%s" % proto]
                    if rport: args += ["remoteport=%s" % rport]
                    if not use_global: args += ["user=%s" % target_user]
                    args += extra
                    self._run(args)
                    self._rules.append(name)
                except Exception:
                    pass
            # 4) 验证规则是否已应用
            verifications = []
            for rule_name in self._rules:
                try:
                    v = subprocess.run(
                        ["netsh", "advfirewall", "firewall", "show", "rule",
                         "name=%s" % rule_name],
                        capture_output=True, text=True, timeout=10, check=False)
                    verifications.append({"rule": rule_name, "active": "Enabled" in (v.stdout or "")})
                except Exception:
                    verifications.append({"rule": rule_name, "active": False})
            self.available = True
            return {"applied": True, "global": use_global, "user": target_user,
                    "rules": self._rules, "verified": verifications}
        except subprocess.CalledProcessError as e:
            return {"applied": False, "reason": "需管理员权限：%s" % e}

    def teardown(self):
        for name in self._rules:
            try:
                subprocess.run(
                    ["netsh", "advfirewall", "firewall", "delete", "rule", "name=%s" % name],
                    capture_output=True, text=True, check=False,
                )
            except Exception:
                pass
        self._rules.clear()

    @staticmethod
    def _run(cmd: list[str]):
        subprocess.run(cmd, capture_output=True, check=True)


# ====================== 智能路由（A1: 静默安装 / A2: 路由器指引） ======================
_INSTALL_PROCESS_KEYWORDS = (
    "pip install", "pip3 install", "npm install", "cargo install",
    "apt-get install", "apt install", "yum install", "gem install", "nuget install",
)
_INSTALL_AUTO_ALLOW_DOMAINS = {
    # Python
    "pypi.org", "files.pythonhosted.org",
    "pypi.tuna.tsinghua.edu.cn", "mirrors.aliyun.com",
    # Node
    "registry.npmjs.org", "registry.npmmirror.com",
    # System
    "archive.ubuntu.com", "security.ubuntu.com",
}
_GATEWAY_IPS = {
    "192.168.1.1", "192.168.0.1", "192.168.31.1",
    "10.0.0.1", "10.0.0.2", "172.16.0.1",
    "192.168.2.1", "192.168.3.1", "192.168.50.1",
}


def _get_process_cmdline(pid: int) -> str:
    """获取进程命令行（跨平台）。"""
    try:
        if os.name == "nt":
            r = subprocess.run(
                ["wmic", "PROCESS", "WHERE", "ProcessId=%d" % pid,
                 "GET", "CommandLine", "/FORMAT:CSV"],
                capture_output=True, text=True, timeout=5)
            lines = [l.strip() for l in r.stdout.split("\n") if l.strip() and "CommandLine" not in l]
            return lines[-1] if lines else ""
        try:
            with open("/proc/%d/cmdline" % pid, "rb") as f:
                return f.read().decode("utf-8", "replace").replace("\0", " ").strip()
        except FileNotFoundError:
            return ""
    except Exception:
        return ""


def _is_install_process(pid: int) -> bool:
    """检测进程是否包管理器的 install 子命令。"""
    cmd = _get_process_cmdline(pid).lower()
    return any(kw in cmd for kw in _INSTALL_PROCESS_KEYWORDS)


def _is_gateway_ip(ip: str) -> bool:
    return ip in _GATEWAY_IPS


_ROUTER_GUIDES = {
    "/cgi-bin/setWifi": {"brand": "TP-Link", "title": "修改 Wi-Fi 密码",
                         "steps": ["打开浏览器访问 192.168.1.1",
                                   "输入管理员密码（默认 admin/admin）",
                                   "进入「无线设置」→「基本设置」",
                                   "修改 SSID/密码 → 保存"]},
    "/cgi-bin/luci": {"brand": "OpenWrt / 小米", "title": "修改路由器配置",
                      "steps": ["打开浏览器访问 192.168.1.1",
                                "登录 LuCI 管理界面",
                                "按需修改配置 → 保存并应用"]},
    "/goform/setWifi": {"brand": "Tenda / Mercury", "title": "修改 Wi-Fi 设置",
                        "steps": ["打开浏览器访问 192.168.0.1",
                                  "登录路由器管理页",
                                  "进入无线设置 → 修改 → 保存"]},
    "/setting/": {"brand": "ASUS", "title": "修改路由器设置",
                  "steps": ["打开浏览器访问 192.168.1.1",
                            "登录华硕路由器管理页",
                            "进入对应设置项 → 应用"]},
}


def _router_guide(ip: str, path: str, method: str) -> dict:
    """生成路由器操作指引。"""
    path_lower = path.lower()
    default_guide = {"brand": "通用路由器", "title": "修改路由器配置",
                     "steps": ["打开浏览器访问 http://%s/" % ip,
                               "输入管理员账号密码",
                               "找到对应设置项并按需修改"]}
    for prefix, guide in _ROUTER_GUIDES.items():
        if prefix in path_lower:
            return dict(guide, ip=ip, method=method, path=path)
    return dict(default_guide, ip=ip, method=method, path=path)


# ====================== 网络裁决引擎（严格规则匹配，prompt 实现） ======================

# 敏感路径关键词（规则 3 / 规则 6）
_SENSITIVE_PATH_KEYWORDS = ["/config", "/setup", "/restore", "/reboot",
                            "/firmware", "/goform", "/cgi-bin"]
# 高危端口（规则 2）
_HIGH_RISK_PORTS = {22, 23, 445, 3306, 3389, 5900}
# 常见网关 IP（规则 1）
_GATEWAY_CANDIDATES = {
    "192.168.1.1", "192.168.0.1", "192.168.31.1",
    "10.0.0.1", "10.0.0.2", "172.16.0.1",
    "192.168.2.1", "192.168.3.1", "192.168.50.1",
}
# 安全端口（规则 5）
_SAFE_PORTS = {80, 443, 8080}
_SAFE_PATH_PATTERNS = ("/status", "/health", "/ping", "/info", "/version", "/healthz")
_WRITE_METHODS = {"POST", "PUT", "DELETE", "PATCH"}
_RATE_LIMIT_THRESHOLD = 20
_request_rate: dict[str, list[float]] = {}  # ip -> 时间戳列表


def _is_private_ip(ip: str) -> bool:
    try:
        parts = ip.split(".")
        if len(parts) != 4:
            return True
        first = int(parts[0])
        if first == 10 or first == 127:
            return True
        if first == 172 and 16 <= int(parts[1]) <= 31:
            return True
        if first == 192 and parts[1] == "168":
            return True
        if ip.startswith("::1") or ip.startswith("fe80"):
            return True
        return False
    except (ValueError, IndexError):
        return True


def _track_rate(ip: str) -> int:
    now = time.time()
    if ip not in _request_rate:
        _request_rate[ip] = []
    ts_list = _request_rate[ip]
    ts_list.append(now)
    cutoff = now - 60
    _request_rate[ip] = [t for t in ts_list if t > cutoff]
    return len(_request_rate[ip])


def _net_verdict(target_ip: str, port: int, method: str, path: str,
                 body_preview: str = "", is_private_ip: bool = False,
                 rate: int = 0) -> dict:
    """严格规则的网络裁决引擎。
    
    输入: {target_ip, port, method, path, body_preview, is_private_ip, request_rate_per_minute}
    输出: {"action": "ALLOW"|"DENY"|"HUMAN_REQUIRED", "confidence": 0.0-1.0, "reason": "≤25字"}
    命中即停止，不再往下判断。
    """
    m = method.upper() if method else "GET"
    p = (path or "").lower()
    ip = target_ip or ""
    is_write = m in _WRITE_METHODS

    # 阶段一：硬否决（最高优先级，置信度≥0.99）
    if ip in _GATEWAY_CANDIDATES and is_write:
        return {"action": "DENY", "confidence": 1.0,
                "reason": "规则1-网关写入操作(%s)" % ip}
    if port in _HIGH_RISK_PORTS:
        return {"action": "DENY", "confidence": 1.0,
                "reason": "规则2-高危管理端口(%d)" % port}
    if is_write:
        for kw in _SENSITIVE_PATH_KEYWORDS:
            if kw in p:
                return {"action": "DENY", "confidence": 0.99,
                        "reason": "规则3-敏感路径写入操作"}

    # 阶段二：明确放行（置信度≥0.95）
    if ip in ("127.0.0.1", "::1", "localhost"):
        return {"action": "ALLOW", "confidence": 1.0,
                "reason": "规则4-本地环回信任"}
    if m == "GET" and port in _SAFE_PORTS:
        for pat in _SAFE_PATH_PATTERNS:
            if p.startswith(pat) or p == pat:
                return {"action": "ALLOW", "confidence": 0.98,
                        "reason": "规则5-安全状态读取"}

    # 阶段三：边界与降级（置信度 0.5-0.8）
    if m == "GET":
        for kw in _SENSITIVE_PATH_KEYWORDS:
            if kw in p:
                return {"action": "HUMAN_REQUIRED", "confidence": 0.80,
                        "reason": "规则6-读取敏感配置"}
    if rate > _RATE_LIMIT_THRESHOLD:
        return {"action": "DENY", "confidence": 0.99,
                "reason": "规则7-高频内网探测"}
    if is_private_ip:
        return {"action": "HUMAN_REQUIRED", "confidence": 0.60,
                "reason": "规则8-未知内网设备请求"}

    # 阶段四：公网兜底
    return {"action": "HUMAN_REQUIRED", "confidence": 0.50,
            "reason": "规则9-公网非标请求"}


_PID_CACHE: dict[int, tuple[int, float]] = {}  # port -> (pid, timestamp)
_PID_CACHE_TTL = 1.0  # 1 秒缓存


def resolve_pid(local_port: int) -> int | None:
    """根据客户端源端口反查进程 PID（尽力而为，1 秒缓存）。"""
    now = time.time()
    # 缓存命中
    if local_port in _PID_CACHE:
        pid, ts = _PID_CACHE[local_port]
        if now - ts < _PID_CACHE_TTL:
            return pid
    # Windows: ctypes 调用 iphlpapi.GetExtendedTcpTable
    pid = _resolve_pid_win(local_port)
    if pid is not None:
        _PID_CACHE[local_port] = (pid, now)
        return pid
    # Linux: 解析 /proc/net/tcp
    pid = _resolve_pid_linux(local_port)
    if pid is not None:
        _PID_CACHE[local_port] = (pid, now)
        return pid
    # macOS / 回退: netstat -ano
    pid = _resolve_pid_netstat(local_port)
    if pid is not None:
        _PID_CACHE[local_port] = (pid, now)
        return pid
    return None


def _resolve_pid_win(port: int) -> int | None:
    """Windows: ctypes 调用 iphlpapi.GetExtendedTcpTable (L3 原生，无额外进程开销)。"""
    try:
        import ctypes
        from ctypes import wintypes
        # MIB_TCPROW_OWNER_PID 结构 (AF_INET)
        class MIB_TCPROW_OWNER_PID(ctypes.Structure):
            _fields_ = [
                ("dwState", wintypes.DWORD),
                ("dwLocalAddr", wintypes.DWORD),
                ("dwLocalPort", wintypes.DWORD),
                ("dwRemoteAddr", wintypes.DWORD),
                ("dwRemotePort", wintypes.DWORD),
                ("dwOwningPid", wintypes.DWORD),
            ]
        # 获取表
        buf = ctypes.create_string_buffer(102400)
        size = wintypes.DWORD(ctypes.sizeof(buf))
        ret = ctypes.windll.iphlpapi.GetExtendedTcpTable(
            buf, ctypes.byref(size), False,
            wintypes.DWORD(2),  # AF_INET
            wintypes.DWORD(0),   # TCP_TABLE_OWNER_PID_ALL
            wintypes.DWORD(0),
        )
        if ret != 0:
            return None
        # 解析：前 4 字节是条目数
        n_entries = int.from_bytes(buf.raw[:4], "little")
        row_size = ctypes.sizeof(MIB_TCPROW_OWNER_PID)
        port_be = socket.htons(port)
        for i in range(n_entries):
            offset = 4 + i * row_size
            row = MIB_TCPROW_OWNER_PID.from_buffer(buf, offset)
            if row.dwLocalPort == port_be:
                return row.dwOwningPid
    except Exception:
        pass
    return None


def _resolve_pid_linux(port: int) -> int | None:
    """Linux: 解析 /proc/net/tcp 反查 inode 后匹配 /proc/[pid]/fd。"""
    try:
        with open("/proc/net/tcp") as f:
            for line in f:
                cols = line.strip().split()
                if len(cols) < 10:
                    continue
                local = cols[1]  # 格式: 0100007F:1A0B
                addr, port_hex = local.split(":")
                if int(port_hex, 16) == port:
                    inode = cols[9]
                    # 遍历 /proc 查找含该 inode 的进程
                    for proc in os.listdir("/proc"):
                        if not proc.isdigit():
                            continue
                        try:
                            fd_dir = "/proc/%s/fd" % proc
                            for fd in os.listdir(fd_dir):
                                try:
                                    link = os.readlink(os.path.join(fd_dir, fd))
                                    if "socket:[%s]" % inode in link:
                                        return int(proc)
                                except (OSError, ValueError):
                                    pass
                        except OSError:
                            pass
    except (OSError, FileNotFoundError):
        pass
    return None


def _resolve_pid_netstat(port: int) -> int | None:
    """跨平台回退：netstat -ano（限频到每分钟 ≤3 次）。"""
    try:
        # 限频：记录每次调用
        now = time.time()
        if not hasattr(_resolve_pid_netstat, "_last_calls"):
            _resolve_pid_netstat._last_calls = []
        calls = _resolve_pid_netstat._last_calls
        calls[:] = [t for t in calls if now - t < 60]
        if len(calls) >= 3:
            return None  # 超限：跳过
        calls.append(now)
        raw = subprocess.run(["netstat", "-ano", "-p", "tcp"],
                             capture_output=True, check=False, timeout=10).stdout or b""
        out = raw.decode("utf-8", "replace")
        for line in out.splitlines():
            cols = line.split()
            if len(cols) >= 5:
                try:
                    lp = int(cols[1].rsplit(":", 1)[1])
                except (IndexError, ValueError):
                    continue
                if lp == port and "ESTABLISHED" in line:
                    return int(cols[-1])
    except Exception:
        pass
    return None


# ====================== 拦截代理 ======================
class NetInterceptor:
    def __init__(self, port: int = PROXY_PORT, quota_limit: int = DEFAULT_QUOTA,
                 isolate_user: str | None = None, force_global_fw: bool = False):
        self.port = port
        self.policy = PolicyStore()
        self.quota = Quota(quota_limit)
        self.firewall = FirewallManager(isolate_user, port, force_global=force_global_fw)
        self.pending: dict[str, PendingRequest] = {}
        self.pending_lock = threading.Lock()
        self.pending_version = 0  # 增量版本号（见优化3）
        self.server: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.fw_status: dict | None = None

    # ---- 生命周期 ----
    def start(self):
        self.fw_status = self.firewall.setup()
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(("127.0.0.1", self.port))
        self.port = self.server.getsockname()[1]  # port=0 时取系统分配端口
        self.server.listen(128)
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        self.firewall.teardown()
        try:
            self.server.close()
        except Exception:
            pass

    def _accept_loop(self):
        while not self._stop.is_set():
            try:
                self.server.settimeout(1.0)
                conn, _ = self.server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            t = threading.Thread(target=self._handle_client, args=(conn,), daemon=True)
            t.start()

    # ---- 待审队列 API（供 web.py / UI 调用） ----
    def list_pending(self, since: int = 0) -> dict:
        """若 version 与 since 一致返回 changed=False，否则返回全量。"""
        with self.pending_lock:
            if since == self.pending_version:
                return {"changed": False, "version": self.pending_version}
            return {
                "changed": True,
                "version": self.pending_version,
                "data": [p.to_dict() for p in self.pending.values()],
            }

    def pending_count(self) -> int:
        with self.pending_lock:
            return len(self.pending)

    def decide(self, req_id: str, verdict: str) -> dict:
        """verdict: allow_once | allow_session | allow_permanent（白名单） | deny_permanent（黑名单）"""
        with self.pending_lock:
            req = self.pending.get(req_id)
            if req is None:
                return {"ok": False, "error": "请求不存在或已处理"}
            host = req.host
            pid = req.pid
        if verdict == "allow_permanent":
            self.policy.add_allow_permanent(host)  # 写入持久白名单
            self._wake(host, "allow_permanent")
        elif verdict == "allow_session":
            self.policy.add_allow_session(host)
            self._wake(host, "allow_session")
        elif verdict == "allow_once":
            self._wake(host, "allow_once")
        elif verdict == "deny_permanent":
            self.policy.add_deny_permanent(host)   # 写入持久黑名单（蜜罐升级）
            self._wake(host, "deny_permanent")
            if pid:
                HoneypotKill(pid)                   # 确认后终止进程
        elif verdict == "guide_done":
            # 用户确认已手动完成路由器操作，放行本次请求
            with self.pending_lock:
                req.result = "guide_done"
                req.event.set()
            return {"ok": True, "verdict": "guide_done", "host": host}
        else:
            return {"ok": False, "error": "未知裁决"}
        return {"ok": True, "verdict": verdict, "host": host}

    def _wake(self, host: str, verdict: str):
        with self.pending_lock:
            for req in list(self.pending.values()):
                if _norm_host(req.host) == _norm_host(host):
                    req.result = verdict
                    req.event.set()

    def set_quota(self, limit: int):
        self.quota.set_limit(limit)
        return {"limit": limit, "used": self.quota.used, "fused": self.quota.fused}

    def status(self) -> dict:
        return {
            "proxy_port": self.port,
            "quota_limit": self.quota.limit,
            "quota_used": self.quota.used,
            "quota_fused": self.quota.fused,
            "policy": self.policy.snapshot(),
            "pending_count": len(self.pending),
            "pending_version": self.pending_version,
            "firewall": self.fw_status,
        }

    # ---- 连接处理 ----
    def _handle_client(self, conn: socket.socket):
        try:
            req_line, headers = self._read_request_head(conn)
            if not req_line:
                conn.close()
                return
            method = req_line.split(" ", 1)[0]
            if method == "CONNECT":
                host, port = self._parse_connect_target(req_line)
            else:
                host, port = self._parse_absolute_uri(req_line, headers)
            if not host:
                self._send_status(conn, 400, "Bad Request")
                return
            verdict = self._gate(host, port, conn, method, req_line, headers)
            if verdict is None or verdict.startswith("deny"):
                self._send_json_error(conn, "NET_DENIED", 403,
                                      extra="denied by gate: %s" % verdict)
                return
            # 放行
            if method == "CONNECT":
                self._tunnel_connect(conn, host, port)
            else:
                self._forward_http(conn, host, port, req_line, headers)
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _gate(self, host: str, port: int, conn: socket.socket,
              method: str = "GET", req_line: str = "", headers: dict | None = None) -> str | None:
        """返回最终裁决（使用严格规则引擎 _net_verdict + 蜜罐覆盖）。"""
        # 0) 永久黑白名单优先
        v = self.policy.verdict_for(host)
        if v == "deny":
            return "deny"
        if v == "allow":
            return "allow_session"

        # A1) 静默安装预检（包管理器自动放行白名单域名）
        peer = conn.getpeername()
        pid = resolve_pid(peer[1]) if peer else None
        if (pid and _is_install_process(pid)
                and (host in _INSTALL_AUTO_ALLOW_DOMAINS or host.endswith(".pypi.org"))):
            sys.stderr.write("[SMART-ROUTE] 静默放行安装流量: %s (PID %d)\n" % (host, pid))
            self.policy.add_allow_session(host)
            return "allow_session"

        # 1) 解析目标 IP 与请求频率
        remote_ip = self._resolve_ip(host)
        priv = _is_private_ip(remote_ip) if remote_ip else True
        rate = _track_rate(remote_ip or host)
        # 从 req_line 提取 path
        from urllib.parse import urlparse as _urlparse
        raw_path = ""
        if req_line:
            try:
                raw_path = _urlparse(req_line.split(" ")[1] if " " in req_line else "").path
            except Exception:
                raw_path = req_line.split(" ")[1] if " " in req_line else ""

        # 2) 调用严格规则引擎
        verdict = _net_verdict(
            target_ip=remote_ip or host,
            port=port,
            method=method,
            path=raw_path,
            body_preview="",
            is_private_ip=priv,
            rate=rate,
        )
        act = verdict["action"]

        # 3) 蜜罐升级覆盖（策略二：读诱饵+外联）
        peer = conn.getpeername()
        pid = resolve_pid(peer[1]) if peer else None
        ev = _honeypot_read(pid) if pid else None
        if ev is not None:
            # 蜜罐命中 → 强制拒绝并在前端生成告警
            req = PendingRequest(host, port, pid, remote_ip)
            req.honeypot_risk = True
            req.honeypot_sig = ev.get("sig")
            req.honeypot_category = _decoy_category(ev.get("sig"))
            try:
                from sandbox_honeypot import get_honeypot
                get_honeypot().create_alert(host, port, pid, ev.get("sig"),
                                            req.honeypot_category, req.id)
            except Exception:
                pass
            with self.pending_lock:
                self.pending[req.id] = req
                self.pending_version += 1
            req.result = "deny_permanent"
            req.event.set()
            return "deny_permanent"

        # 4) 根据规则引擎结果行动
        if act == "DENY":
            return "deny"

        if act == "ALLOW":
            return "allow_session"

        # act == "HUMAN_REQUIRED" → 进入待审队列
        req = PendingRequest(host, port, pid, remote_ip)
        req.verdict_reason = verdict.get("reason", "")
        req.verdict_confidence = verdict.get("confidence", 0.0)
        req.guide_required = True  # 标记需人工确认
        req.guide_data = {
            "verdict": verdict,
            "host": host,
            "port": port,
            "method": method,
            "path": raw_path,
        }
        with self.pending_lock:
            self.pending[req.id] = req
            self.pending_version += 1
        # 挂起等待 UI 裁决
        req.event.wait()
        with self.pending_lock:
            self.pending.pop(req.id, None)
        return req.result

    @staticmethod
    def _resolve_ip(host: str) -> str | None:
        try:
            return socket.gethostbyname(host)
        except Exception:
            return None

    # ---- 隧道 / 转发 ----
    def _tunnel_connect(self, client: socket.socket, host: str, port: int):
        try:
            target = socket.create_connection((host, port), timeout=15)
        except OSError as e:
            self._send_status(client, 502, "Bad Gateway: %s" % e)
            return
        self._send_status(client, 200, "Connection Established")
        self._pump(client, target)

    def _forward_http(self, client: socket.socket, host: str, port: int,
                      req_line: str, headers: dict):
        try:
            target = socket.create_connection((host, port or 80), timeout=15)
        except OSError as e:
            self._send_status(client, 502, "Bad Gateway: %s" % e)
            return
        # 重写请求行为相对路径（正向代理 -> 源站）
        parts = req_line.split(" ")
        if len(parts) == 3:
            url = parts[1]
            from urllib.parse import urlparse
            p = urlparse(url)
            new_path = (p.path or "") + (("?" + p.query) if p.query else "")
            new_line = "%s %s %s" % (parts[0], new_path or "/", parts[2])
        else:
            new_line = req_line
        head = new_line + "\r\n"
        for k, v in headers.items():
            if k.lower() in ("proxy-connection", "proxy-authorization"):
                continue
            head += "%s: %s\r\n" % (k, v)
        head += "\r\n"
        try:
            target.sendall(head.encode("utf-8", "replace"))
        except OSError:
            target.close()
            return
        self._pump(client, target)

    def _pump(self, a: socket.socket, b: socket.socket):
        self.quota.register(a); self.quota.register(b)
        try:
            t1 = threading.Thread(target=self._copy, args=(a, b), daemon=True)
            t2 = threading.Thread(target=self._copy, args=(b, a), daemon=True)
            t1.start(); t2.start(); t1.join(); t2.join()
        finally:
            for s in (a, b):
                self.quota.unregister(s)
                try:
                    s.close()
                except OSError:
                    pass

    def _copy(self, src: socket.socket, dst: socket.socket):
        try:
            src.settimeout(1.0)
            while True:
                data = src.recv(65536)
                if not data:
                    break
                self.quota.add(len(data))
                if self.quota.fused:
                    break
                dst.sendall(data)
        except (socket.timeout, OSError):
            pass

    # ---- 底层读写 ----
    @staticmethod
    def _read_request_head(conn: socket.socket) -> tuple[str, dict]:
        conn.settimeout(10.0)
        buf = b""
        while b"\r\n\r\n" not in buf:
            try:
                chunk = conn.recv(4096)
            except OSError:
                return "", {}
            if not chunk:
                break
            buf += chunk
            if len(buf) > 65536:
                break
        if b"\r\n\r\n" not in buf:
            return "", {}
        head, _ = buf.split(b"\r\n\r\n", 1)
        lines = head.decode("utf-8", "replace").split("\r\n")
        req_line = lines[0] if lines else ""
        headers: dict = {}
        for line in lines[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip()] = v.strip()
        return req_line, headers

    @staticmethod
    def _parse_connect_target(req_line: str) -> tuple[str, int]:
        # CONNECT host:port HTTP/1.1
        parts = req_line.split(" ")
        target = parts[1] if len(parts) > 1 else ""
        if ":" in target:
            h, p = target.rsplit(":", 1)
            return h, int(p)
        return target, 443

    @staticmethod
    def _parse_absolute_uri(req_line: str, headers: dict) -> tuple[str, int]:
        from urllib.parse import urlparse
        parts = req_line.split(" ")
        url = parts[1] if len(parts) > 1 else ""
        p = urlparse(url)
        host = p.hostname or headers.get("Host", "").split(":")[0]
        port = p.port or (int(headers["Host"].split(":")[1]) if ":" in headers.get("Host", "") else 80)
        return host, port

    @staticmethod
    def _send_status(conn: socket.socket, code: int, reason: str):
        try:
            conn.sendall(("HTTP/1.1 %d %s\r\nContent-Length: 0\r\n\r\n" % (code, reason)).encode())
        except OSError:
            pass

    @staticmethod
    def _send_json_error(conn: socket.socket, code: str, status: int = 403, extra: str = ""):
        """通过代理 socket 返回统一的 JSON 格式错误响应。"""
        from src.sandbox import err_resp
        resp = err_resp(code, extra)
        if status:
            resp["errno"] = status
        body = json.dumps(resp, ensure_ascii=False).encode("utf-8")
        status_line = resp["errno"]
        try:
            conn.sendall(
                ("HTTP/1.1 %d %s\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n"
                 % (status_line, "Sandbox Rejection", len(body))).encode()
                + body
            )
        except OSError:
            pass


def start_interceptor(port: int = PROXY_PORT, quota_limit: int = DEFAULT_QUOTA,
                      isolate_user: str | None = None,
                      force_global_fw: bool = False) -> NetInterceptor:
    global INTERCEPTOR
    if INTERCEPTOR is None:
        INTERCEPTOR = NetInterceptor(port, quota_limit, isolate_user,
                                     force_global_fw=force_global_fw).start()
    return INTERCEPTOR


def get_interceptor() -> NetInterceptor | None:
    return INTERCEPTOR

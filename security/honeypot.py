"""诱饵文件蜜罐系统（轻量级）。

设计要点
--------
- 多类高仿真「陷阱」文件（SSH 私钥 / AWS 凭证 / Shell 历史 / .netrc / GCP / Git / PG / .env …），
  内容格式正确但明显为假（含 HONEYPOT-DECOY 标记），绝不会被当作真实密钥。
- 物理部署：在隔离位置落地假文件（bash/cat 等无 hook 的程序也能命中策略 1/4 的兜底）。
- 应用层拦截 shim（Python sitecustomize / Node --require）：
    * 策略一 静默替换：读取诱饵时返回假内容，不终止、不弹窗，仅后台记录审计。
    * 策略四 写入/删除保护：写/删诱饵立即 PermissionError 并告警，直接终止。
    * 策略三 批量遍历阈值：5 秒内读 ≥3 个不同诱饵 → 判定批量收割，终止并告警。
- 策略二 绑定网络动作：shim 把读取事件写入共享事件日志；网络代理在挂起连接时
  发现该 PID 读过诱饵 → 升级为 🚨 高危告警，自动拒绝连接，待用户确认后终止进程 + IP 进黑名单。

跨进程通信：shim（在受限子进程内）受防火墙限制无法回连，故把事件以 JSON 行追加到
共享文件 HONEYPOT_EVENT_LOG；web 进程（代理所在）读取该文件做关联与审计。

Windows 非管理员环境适配：本实现用应用层 shim + 物理假文件，而非 LD_PRELOAD/seccomp
（后者为 Linux 机制，且本机无 VM 级隔离）。bash 无用户态 hook，仅依赖物理只读假文件兜底。
"""
from __future__ import annotations

import base64
import json
import os
import signal
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent                  # src/sandbox
ROOT = HERE.parent.parent                                # 项目根目录
SANDBOX_DIR = ROOT / "sandbox_runtime"                    # 原根目录 sandbox/ 重命名为 sandbox_runtime/，避免与 src/sandbox 包冲突
DECOY_ROOT = SANDBOX_DIR / "decoys"                       # ~ 解析根（sandbox_run 设 HOME/USERPROFILE 指向此）
LINUX_ROOT = Path("/home/user") if os.name != "nt" else DECOY_ROOT  # Linux /home/user 镜像；Windows 无用
ACCOUNT_ROOT = Path(os.environ.get("PALM_SANDBOX_ACCOUNT_ROOT", "C:/Users/sandbox_runner"))  # win32 受限账户 home（存在才部署）
EVENT_LOG_DEFAULT = SANDBOX_DIR / "honeypot_events.log"
HONEYPOT_SHIM_DIR = HERE / "shim"                         # sitecustomize.py / honeypot_node.js 注入目录（已随包迁移）

# 触发阈值
BATCH_WINDOW_SEC = 5.0
BATCH_DISTINCT_THRESHOLD = 3
READ_CORRELATION_SEC = 120.0   # 代理关联时，读取事件在此时间窗内视为有效


def _rand_b64(n: int) -> str:
    return base64.b64encode(os.urandom(n)).decode("ascii")


# ----------------------------- 诱饵规格注册表 -----------------------------
def _fake_ssh(keytype: str) -> str:
    head = "ssh-" + keytype
    lines = [
        "-----BEGIN OPENSSH PRIVATE KEY-----",
        "HONEYPOT-DECOY This is a FAKE %s private key. Any exfiltration yields garbage." % keytype,
    ]
    blob = _rand_b64(1800)
    for i in range(0, len(blob), 70):
        lines.append(blob[i:i + 70])
    lines.append("-----END OPENSSH PRIVATE KEY-----")
    return "\n".join(lines) + "\n"


def _fake_aws() -> str:
    return (
        "[default]\n"
        "aws_access_key_id = AKIA-DECOY-NOT-REAL\n"
        "aws_secret_access_key = DECOY-AWS-SECRET-NOT-REAL\n"
        "aws_session_token = DECOY-AWS-TOKEN-NOT-REAL\n"
        "region = us-east-1\n"
        "# HONEYPOT-DECOY: 以上为陷阱凭证，非真实可用。\n"
    )


def _fake_history() -> str:
    return (
        "ls -la ~/projects\n"
        "git status\n"
        "cat .env\n"
        "ssh root@10.0.0.5\n"
        "mysql -u admin -p\n"
        "# HONEYPOT-DECOY: 该历史文件为陷阱，记录内容均为伪造。\n"
        "kubectl get pods -A\n"
        "cat ~/.aws/credentials\n"
    )


def _fake_netrc() -> str:
    return (
        "machine api.example.com\n"
        "  login decoy-user\n"
        "  password HONEYPOT-DECOY-fake-pass-0123456789\n"
        "machine github.com\n"
        "  login decoy\n"
        "  password fake-token-aaaaaaaaaaaaaaaa\n"
    )


def _fake_gcloud() -> str:
    return json.dumps({
        "type": "service_account",
        "project_id": "decoy-project",
        "private_key_id": _rand_b64(16)[:32],
        "private_key": "-----BEGIN PRIVATE KEY-----\nHONEYPOT-DECOY\n"
                       + _rand_b64(1200) + "\n-----END PRIVATE KEY-----\n",
        "client_email": "decoy@decoy-project.iam.gserviceaccount.com",
        "token_uri": "https://oauth2.googleapis.com/token",
        "HONEYPOT": "DECOY credentials, not real",
    }, indent=2) + "\n"


def _fake_git_credentials() -> str:
    return (
        "https://decoy-user:HONEYPOT-DECOY-fake-token@github.com\n"
        "https://x-oauth-basic:fake-gh-token-aaaaaaaaaaaaaaaa@gist.github.com\n"
    )


def _fake_pgpass() -> str:
    return (
        "localhost:5432:mydb:decoy:HONEYPOT-DECOY-fake-pg-pass\n"
        "db.example.com:5432:analytics:ro:another-fake-pass-0000\n"
    )


def _fake_env() -> str:
    return (
        "DB_PASSWORD=HONEYPOT-DECOY-fake-db-pass\n"
        "OPENAI_API_KEY=DECOY-OPENAI-KEY-NOT-REAL\n"
        "STRIPE_SECRET=DECOY-STRIPE-KEY-NOT-REAL\n"
        "# HONEYPOT-DECOY: 以上均为陷阱变量，非真实密钥。\n"
    )


DECOY_SPECS = [
    {
        "id": "ssh_rsa", "category": "SSH 私钥",
        "sigs": [".ssh/id_rsa", ".ssh/id_dsa", ".ssh/id_ecdsa",
                 ".ssh/id_ed25519", ".ssh/id_rsa.pub", ".ssh/id_ed25519.pub"],
        "rel": ".ssh/id_rsa", "content": lambda: _fake_ssh("rsa"),
        "desc": "OpenSSH 私钥（rsa/ed25519 等）",
    },
    {
        "id": "aws_credentials", "category": "AWS 凭证",
        "sigs": [".aws/credentials", ".aws/config"],
        "rel": ".aws/credentials", "content": _fake_aws,
        "desc": "AWS 访问凭证文件",
    },
    {
        "id": "bash_history", "category": "Shell 历史",
        "sigs": [".bash_history", ".zsh_history", ".history"],
        "rel": ".bash_history", "content": _fake_history,
        "desc": "Shell 命令历史（含敏感操作记录）",
    },
    {
        "id": "netrc", "category": ".netrc 凭证",
        "sigs": [".netrc", "_netrc"],
        "rel": ".netrc", "content": _fake_netrc,
        "desc": "ftp/邮件自动登录凭证",
    },
    {
        "id": "gcloud", "category": "GCP 凭证",
        "sigs": ["application_default_credentials.json", "credentials.json",
                 "gcloud/application_default_credentials.json"],
        "rel": ".config/gcloud/application_default_credentials.json",
        "content": _fake_gcloud, "desc": "Google Cloud 服务账号密钥",
    },
    {
        "id": "git_credentials", "category": "Git 凭证",
        "sigs": [".git-credentials", ".git-credential-cache"],
        "rel": ".git-credentials", "content": _fake_git_credentials,
        "desc": "Git 明文凭证存储",
    },
    {
        "id": "pgpass", "category": "Postgres 口令",
        "sigs": [".pgpass"],
        "rel": ".pgpass", "content": _fake_pgpass, "desc": "PostgreSQL 免密文件",
    },
    {
        "id": "env_secrets", "category": "密钥/环境变量",
        "sigs": [".env", "secrets.json", "credentials.yaml", ".env.local"],
        "rel": ".env", "content": _fake_env, "desc": "项目密钥/环境变量文件",
    },
]

SIG_TO_SPEC: dict[str, dict] = {}
for _s in DECOY_SPECS:
    for _sig in _s["sigs"]:
        SIG_TO_SPEC[_sig] = _s


def match_decoy(path: str) -> dict | None:
    """按路径尾签名匹配诱饵规格（跨根变体通用）。"""
    if not path:
        return None
    p = os.path.normpath(path).replace("\\", "/").lower().rstrip("/")
    for sig, spec in SIG_TO_SPEC.items():
        sigl = sig.lower()
        if p == sigl or p.endswith("/" + sigl) or p.endswith(sigl):
            return spec
    return None


# ----------------------------- 物理部署 -----------------------------
def _write_readonly(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o644)  # 先解除只读以便覆盖
    except OSError:
        pass
    path.write_text(content, encoding="utf-8")
    try:
        os.chmod(path, 0o444)  # 只读：bash 等无 hook 程序也改不了/删不了
    except OSError:
        pass


def deploy_decoys() -> dict:
    """把假文件落地到多个隔离根。返回统计。"""
    SANDBOX_DIR.mkdir(parents=True, exist_ok=True)
    roots = [DECOY_ROOT]
    if LINUX_ROOT != DECOY_ROOT:
        roots.append(LINUX_ROOT)
    if ACCOUNT_ROOT.exists() and ACCOUNT_ROOT != DECOY_ROOT:
        roots.append(ACCOUNT_ROOT)
    counts = {"roots": [str(r) for r in roots], "files": 0}
    for root in roots:
        for spec in DECOY_SPECS:
            target = root / spec["rel"]
            _write_readonly(target, spec["content"]() if callable(spec["content"]) else spec["content"])
            counts["files"] += 1
    return counts


def list_decoys() -> list[dict]:
    return [{
        "id": s["id"], "category": s["category"], "desc": s["desc"],
        "sigs": s["sigs"], "rel": s["rel"],
    } for s in DECOY_SPECS]


# ----------------------------- 事件日志 + 单例 -----------------------------
class Honeypot:
    def __init__(self, event_log: Path | None = None):
        self.event_log = Path(os.environ.get("HONEYPOT_EVENT_LOG")
                              or (event_log or EVENT_LOG_DEFAULT))
        self.event_log.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.alerts: list[dict] = []   # 升级告警（策略二），进程内
        self._alert_seq = 0

    # --- 写入（web 进程也可写，例如代理升级时） ---
    def append_event(self, event: dict):
        try:
            with self.lock:
                with open(self.event_log, "a", encoding="utf-8") as f:
                    f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception:
            pass

    # --- 读取 ---
    def read_events(self, since: float | None = None, limit: int = 500) -> list[dict]:
        out: list[dict] = []
        try:
            with open(self.event_log, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        e = json.loads(line)
                    except Exception:
                        continue
                    if since is None or e.get("ts", 0) >= since:
                        out.append(e)
        except FileNotFoundError:
            return []
        return out[-limit:]

    def has_decoy_read(self, pid: int | None, now: float | None = None) -> dict | None:
        """该 PID 是否在关联时间窗内读取过诱饵（供代理升级用）。"""
        if not pid:
            return None
        now = now or time.time()
        for e in reversed(self.read_events()):
            if e.get("pid") == pid and e.get("action") == "read":
                if now - e.get("ts", 0) <= READ_CORRELATION_SEC:
                    return e
        return None

    # --- 审计汇总 ---
    def get_audit(self) -> dict:
        events = self.read_events()
        by_strategy: dict[int, int] = {}
        by_pid: dict[int, int] = {}
        for e in events:
            s = e.get("strategy")
            if isinstance(s, int):
                by_strategy[s] = by_strategy.get(s, 0) + 1
            p = e.get("pid")
            if p:
                by_pid[p] = by_pid.get(p, 0) + 1
        return {
            "event_log": str(self.event_log),
            "total_events": len(events),
            "by_strategy": by_strategy,
            "by_pid": by_pid,
            "events": events[-200:],
            "alerts": self.alerts,
        }

    # --- 升级告警（策略二） ---
    def create_alert(self, host: str, port: int, pid: int | None,
                     sig_id: str, category: str, req_id: str | None = None) -> dict:
        self._alert_seq += 1
        alert = {
            "id": "hp-%d" % self._alert_seq,
            "ts": time.time(),
            "host": host, "port": port, "pid": pid,
            "sig_id": sig_id, "category": category,
            "req_id": req_id,
            "ack": False,
            "message": ("🚨 高危：进程( PID=%s )正在读取「%s」诱饵并试图外传数据到 %s:%d，"
                        "连接已自动拒绝。" % (pid, category, host, port)),
        }
        self.alerts.append(alert)
        return alert

    def ack_alert(self, alert_id: str) -> dict:
        for a in self.alerts:
            if a["id"] == alert_id and not a["ack"]:
                a["ack"] = True
                self.append_event({
                    "ts": time.time(), "pid": a["pid"], "path": "(alert-ack)",
                    "sig": a["sig_id"], "action": "alert_ack",
                    "strategy": 2, "host": a["host"],
                })
                if a["pid"]:
                    self.kill_pid(a["pid"])
                return {"ok": True, "alert": a}
        return {"ok": False, "error": "告警不存在或已确认"}

    @staticmethod
    def kill_pid(pid: int | None):
        if not pid:
            return
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.kill(pid, sig)
                return
            except Exception:
                continue


# 全局单例（web 进程）
_HONEYPOT: "Honeypot | None" = None


def get_honeypot(event_log: Path | None = None) -> Honeypot:
    global _HONEYPOT
    if _HONEYPOT is None:
        _HONEYPOT = Honeypot(event_log)
    return _HONEYPOT


def set_event_log(path: str | Path):
    global _HONEYPOT
    _HONEYPOT = Honeypot(Path(path))

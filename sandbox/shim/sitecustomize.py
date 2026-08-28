"""诱饵蜜罐 — Python 拦截 shim（作为 sitecustomize 经 PYTHONPATH 注入沙箱子进程）。

仅当环境变量 HONEYPOT_ACTIVE=1 时激活，避免污染宿主（web.py）进程。
职责：
  策略一 静默替换：读取诱饵 → 返回高仿真假内容 + 记录策略1事件（不终止、不弹窗）。
  策略四 写入/删除保护：写/删诱饵 → PermissionError + 记录策略4事件 + 终止进程。
  策略三 批量遍历阈值：5 秒内读 ≥3 个不同诱饵 → 记录策略3事件 + 终止进程。
事件以 JSON 行追加到 HONEYPOT_EVENT_LOG（跨进程供代理关联策略二）。
"""
import io
import json
import os
import sys
import time

if os.environ.get("HONEYPOT_ACTIVE") != "1":
    raise SystemExit  # 未激活：完全不干预（sitecustomize 退出即无副作用）

KILL = os.environ.get("HONEYPOT_KILL", "1") != "0"
EVENT_LOG = os.environ.get("HONEYPOT_EVENT_LOG", "")
BATCH_WINDOW = 5.0
BATCH_THRESHOLD = 3


# ----------------------- 诱饵签名 + 假内容（内联，自包含） -----------------------
def _b64(n):
    return __import__("base64").b64encode(os.urandom(n)).decode("ascii")


def _fake(sig_id):
    if sig_id == "ssh_rsa":
        blob = _b64(1800)
        lines = ["-----BEGIN OPENSSH PRIVATE KEY-----",
                 "HONEYPOT-DECOY FAKE ssh key. Exfil yields garbage.",
                 *[blob[i:i + 70] for i in range(0, len(blob), 70)],
                 "-----END OPENSSH PRIVATE KEY-----"]
        return "\n".join(lines) + "\n"
    if sig_id == "aws_credentials":
        return ("[default]\naws_access_key_id = AKIA-DECOY-NOT-REAL\n"
                "aws_secret_access_key = DECOY-AWS-SECRET-NOT-REAL\n"
                "aws_session_token = IQoJb3JpZ2luX2VjFAKEHONEYPOTDECOY\nregion = us-east-1\n")
    if sig_id == "bash_history":
        return ("ls -la ~/projects\ngit status\ncat .env\nssh root@10.0.0.5\n"
                "mysql -u admin -p\n# HONEYPOT-DECOY: 陷阱历史，内容伪造。\ncat ~/.aws/credentials\n")
    if sig_id == "netrc":
        return ("machine api.example.com\n  login decoy-user\n"
                "  password HONEYPOT-DECOY-fake-pass\n")
    if sig_id == "gcloud":
        return json.dumps({"type": "service_account",
                           "client_email": "decoy@decoy-project.iam",
                           "private_key": "-----BEGIN PRIVATE KEY-----\n"
                                          "HONEYPOT-DECOY\n" + _b64(1200)
                                          + "\n-----END PRIVATE KEY-----\n",
                           "HONEYPOT": "DECOY"}, indent=2) + "\n"
    if sig_id == "git_credentials":
        return "https://decoy-user:HONEYPOT-DECOY-fake-token@github.com\n"
    if sig_id == "pgpass":
        return "localhost:5432:mydb:decoy:HONEYPOT-DECOY-fake-pg-pass\n"
    if sig_id == "env_secrets":
        return ("DB_PASSWORD=HONEYPOT-DECOY-fake-db-pass\n"
                "OPENAI_API_KEY=sk-decoyFakeKey00000000000000000000\n")
    return "HONEYPOT-DECOY fake file content for %s\n" % sig_id


SIGS = {}
for _id, _sigs in {
    "ssh_rsa": [".ssh/id_rsa", ".ssh/id_dsa", ".ssh/id_ecdsa", ".ssh/id_ed25519",
                ".ssh/id_rsa.pub", ".ssh/id_ed25519.pub"],
    "aws_credentials": [".aws/credentials", ".aws/config"],
    "bash_history": [".bash_history", ".zsh_history", ".history"],
    "netrc": [".netrc", "_netrc"],
    "gcloud": ["application_default_credentials.json", "credentials.json"],
    "git_credentials": [".git-credentials"],
    "pgpass": [".pgpass"],
    "env_secrets": [".env", "secrets.json", "credentials.yaml", ".env.local"],
}.items():
    for s in _sigs:
        SIGS[s] = _id


def _match(path):
    if not path:
        return None
    p = os.path.normpath(path).replace("\\", "/").lower().rstrip("/")
    for sig, sid in SIGS.items():
        sl = sig.lower()
        if p == sl or p.endswith("/" + sl) or p.endswith(sl):
            return sid
    return None


# ----------------------- 事件日志 -----------------------
def _log(path, sig_id, action, strategy):
    if not EVENT_LOG:
        return
    rec = {"ts": time.time(), "pid": os.getpid(), "path": str(path),
           "sig": sig_id, "action": action, "strategy": strategy}
    try:
        with open(EVENT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _terminate():
    if KILL:
        os._exit(1)


# ----------------------- 批量阈值跟踪（策略三） -----------------------
_reads = []


def _check_batch(sig_id):
    now = time.time()
    _reads.append((now, sig_id))
    while _reads and now - _reads[0][0] > BATCH_WINDOW:
        _reads.pop(0)
    distinct = {s for _, s in _reads}
    if len(distinct) >= BATCH_THRESHOLD:
        _log("(batch)", sig_id, "batch", 3)
        _terminate()


# ----------------------- 假文件对象 -----------------------
def _fake_file(sig_id, mode):
    data = _fake(sig_id)
    if "b" in mode:
        buf = io.BytesIO(data.encode("utf-8", "replace"))
    else:
        buf = io.StringIO(data)
    return buf


# ----------------------- 写/删保护（策略四） -----------------------
def _block_write(path, sig_id, action):
    _log(path, sig_id, action, 4)
    _terminate()
    raise PermissionError("HONEYPOT-DECOY: 拒绝修改/删除隔离区安全陷阱文件: %s" % path)


# ----------------------- 钩子安装 -----------------------
_orig_open = open
_orig_remove = os.remove
_orig_unlink = os.unlink
_orig_rmdir = os.rmdir
_orig_rename = os.rename
_orig_replace = os.replace


def _open(path, mode="r", *a, **k):
    sid = _match(path)
    if sid is None:
        return _orig_open(path, mode, *a, **k)
    if any(c in mode for c in ("w", "x", "a")):
        _block_write(path, sid, "write")
    # 读取（含 r / r+ / rb 等）
    _log(path, sid, "read", 1)
    _check_batch(sid)
    return _fake_file(sid, mode)


def _wrap_remove(fn):
    def _w(path, *a, **k):
        sid = _match(path)
        if sid is None:
            return fn(path, *a, **k)
        _block_write(path, sid, "delete")
    return _w


builtins = __import__("builtins")
builtins.open = _open
os.remove = _wrap_remove(_orig_remove)
os.unlink = _wrap_remove(_orig_unlink)
os.rmdir = _wrap_remove(_orig_rmdir)
os.rename = _wrap_remove(_orig_rename)
os.replace = _wrap_remove(_orig_replace)

# pathlib 防护
try:
    import pathlib
    _orig_pt_open = pathlib.Path.open
    _orig_pt_read_text = pathlib.Path.read_text
    _orig_pt_read_bytes = pathlib.Path.read_bytes
    _orig_pt_unlink = pathlib.Path.unlink
    _orig_pt_rmdir = pathlib.Path.rmdir
    _orig_pt_write_text = pathlib.Path.write_text
    _orig_pt_write_bytes = pathlib.Path.write_bytes

    def _pt_open(self, mode="r", *a, **k):
        sid = _match(str(self))
        if sid is None:
            return _orig_pt_open(self, mode, *a, **k)
        if any(c in mode for c in ("w", "x", "a")):
            _block_write(str(self), sid, "write")
        _log(str(self), sid, "read", 1)
        _check_batch(sid)
        return _fake_file(sid, mode)

    def _pt_read_text(self, *a, **k):
        sid = _match(str(self))
        if sid is None:
            return _orig_pt_read_text(self, *a, **k)
        _log(str(self), sid, "read", 1)
        _check_batch(sid)
        return _fake(sid)

    def _pt_read_bytes(self, *a, **k):
        sid = _match(str(self))
        if sid is None:
            return _orig_pt_read_bytes(self, *a, **k)
        _log(str(self), sid, "read", 1)
        _check_batch(sid)
        return _fake(sid).encode("utf-8", "replace")

    def _pt_unlink(self, *a, **k):
        sid = _match(str(self))
        if sid is None:
            return _orig_pt_unlink(self, *a, **k)
        _block_write(str(self), sid, "delete")

    def _pt_rmdir(self, *a, **k):
        sid = _match(str(self))
        if sid is None:
            return _orig_pt_rmdir(self, *a, **k)
        _block_write(str(self), sid, "delete")

    def _pt_write_text(self, data, *a, **k):
        sid = _match(str(self))
        if sid is None:
            return _orig_pt_write_text(self, data, *a, **k)
        _block_write(str(self), sid, "write")

    def _pt_write_bytes(self, data, *a, **k):
        sid = _match(str(self))
        if sid is None:
            return _orig_pt_write_bytes(self, data, *a, **k)

    pathlib.Path.open = _pt_open
    pathlib.Path.read_text = _pt_read_text
    pathlib.Path.read_bytes = _pt_read_bytes
    pathlib.Path.unlink = _pt_unlink
    pathlib.Path.rmdir = _pt_rmdir
    pathlib.Path.write_text = _pt_write_text
    pathlib.Path.write_bytes = _pt_write_bytes
except Exception:
    pass

# shutil.rmtree 防护
try:
    import shutil
    _orig_rmtree = shutil.rmtree

    def _rmtree(path, *a, **k):
        sid = _match(str(path))
        if sid is None:
            return _orig_rmtree(path, *a, **k)
        _block_write(str(path), sid, "delete")
    shutil.rmtree = _rmtree
except Exception:
    pass

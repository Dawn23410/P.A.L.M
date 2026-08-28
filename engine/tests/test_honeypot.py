"""诱饵蜜罐系统集成测试（策略一/二/三/四 + 后端关联）。

运行：
    python test_honeypot.py
退出码：0 = 全部通过；非 0 = 有失败。

覆盖范围：
  - 策略一 静默替换：Python / Node 读取诱饵返回假内容 + 后台记录（进程不终止）。
  - 策略四 写/删保护：写/删诱饵 -> PermissionError + 进程终止 + 事件记录。
  - 策略三 批量遍历阈值：5 秒内读 >=3 个不同诱饵 -> 进程终止 + 事件记录。
  - 策略二 绑定网络动作：读诱饵 + 外联 -> 代理自动拒绝 + 生成升级告警；确认后 IP 进永久黑名单。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent  # 项目根（tests/ 的上一级）
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.sandbox import honeypot as sandbox_honeypot
from src.sandbox.honeypot import get_honeypot, set_event_log, deploy_decoys

PY = sys.executable
NODE = shutil.which("node")

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = ""):
    RESULTS.append((name, cond, detail))
    print(("✔ PASS " if cond else "✘ FAIL ") + name + (("  — " + detail) if detail else ""))


def setup_isolated() -> tuple[Path, Path]:
    """创建临时诱饵根 + 事件日志，部署诱饵，返回 (event_log, decoy_root)。"""
    tmp = Path(tempfile.mkdtemp(prefix="hptest_"))
    event_log = tmp / "events.log"
    decoy_root = tmp / "decoys"
    # 重定向诱饵根到临时目录，避免污染项目 sandbox/
    sandbox_honeypot.DECOY_ROOT = decoy_root
    set_event_log(event_log)
    counts = deploy_decoys()
    return event_log, decoy_root, counts


def shim_env(decoy_root: Path, event_log: Path) -> dict:
    env = dict(os.environ)
    # 关闭代理相关变量（单元策略测试不触发网络）
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
              "http_proxy", "https_proxy", "all_proxy", "PIP_PROXY"):
        env.pop(k, None)
    env["HONEYPOT_ACTIVE"] = "1"
    env["HONEYPOT_EVENT_LOG"] = str(event_log)
    env["HONEYPOT_KILL"] = "1"
    env["HOME"] = str(decoy_root)
    env["USERPROFILE"] = str(decoy_root)
    shim_dir = str(sandbox_honeypot.HONEYPOT_SHIM_DIR)
    cur_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (shim_dir + os.pathsep + cur_pp) if cur_pp else shim_dir
    node_shim = str(sandbox_honeypot.HONEYPOT_SHIM_DIR / "honeypot_node.js").replace("\\", "/")
    env["NODE_OPTIONS"] = "--require %s" % node_shim
    return env


def run_py(code: str, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run([PY, "-c", code], capture_output=True, text=True,
                          timeout=30, env=env)


def events() -> list[dict]:
    return get_honeypot().read_events()


# ----------------------------- 主流程 -----------------------------
def main():
    event_log, decoy_root, counts = setup_isolated()
    check("部署诱饵文件", counts["files"] > 0, "%d 个文件 @ %s" % (counts["files"], decoy_root))
    env = shim_env(decoy_root, event_log)

    # ===== 策略一：静默替换（Python） =====
    code1 = (
        "import os\n"
        "p = os.path.expanduser('~/.ssh/id_rsa')\n"
        "d = open(p).read()\n"
        "print('HAS_DECOY', 'HONEYPOT-DECOY' in d)\n"
        "print('NOT_REAL', 'EXAMPLEFAKE' in d)\n"
    )
    r1 = run_py(code1, env)
    check("策略一(Py) 进程正常退出", r1.returncode == 0, "rc=%s" % r1.returncode)
    check("策略一(Py) 返回高仿真假内容", "HAS_DECOY True" in r1.stdout,
          "stdout=%r" % r1.stdout[:120])
    check("策略一(Py) 事件已记录(s1)",
          any(e.get("strategy") == 1 for e in events()),
          "%d 条事件" % len(events()))

    # ===== 策略四：写保护（Python） =====
    code4 = (
        "import os\n"
        "p = os.path.expanduser('~/.aws/credentials')\n"
        "open(p, 'w').write('pwned')\n"
        "print('SHOULD_NOT_REACH')\n"
    )
    r4 = run_py(code4, env)
    check("策略四(Py) 写被终止(rc!=0)", r4.returncode != 0, "rc=%s" % r4.returncode)
    check("策略四(Py) 事件已记录(s4)",
          any(e.get("strategy") == 4 for e in events()))

    # ===== 策略四：删保护（Python pathlib.unlink） =====
    code4b = (
        "from pathlib import Path\n"
        "import os\n"
        "p = Path(os.path.expanduser('~/.env'))\n"
        "p.unlink()\n"
        "print('SHOULD_NOT_REACH')\n"
    )
    r4b = run_py(code4b, env)
    check("策略四(Py) 删被终止(rc!=0)", r4b.returncode != 0, "rc=%s" % r4b.returncode)

    # ===== 策略三：批量遍历阈值（Python） =====
    code3 = (
        "import os\n"
        "for rel in ['.ssh/id_rsa', '.aws/credentials', '.bash_history', '.env']:\n"
        "    p = os.path.expanduser('~/' + rel)\n"
        "    try:\n"
        "        open(p).read()\n"
        "    except Exception as e:\n"
        "        print('ERR', e)\n"
        "print('DONE_BATCH')\n"
    )
    r3 = run_py(code3, env)
    check("策略三(Py) 批量被终止", r3.returncode != 0 or "DONE_BATCH" not in r3.stdout,
          "rc=%s out=%r" % (r3.returncode, r3.stdout[:80]))
    check("策略三(Py) 事件已记录(s3)",
          any(e.get("strategy") == 3 for e in events()))

    # ===== Node 等价策略一/三/四 =====
    if NODE:
        code1n = (
            "const fs=require('fs');const os=require('os');\n"
            "const p=os.homedir()+'/.ssh/id_rsa';\n"
            "const d=fs.readFileSync(p,'utf8');\n"
            "console.log('HAS_DECOY', d.includes('HONEYPOT-DECOY'));\n"
        )
        r1n = subprocess.run([NODE, "-e", code1n], capture_output=True, text=True,
                             timeout=30, env=env)
        check("策略一(Node) 返回假内容", "has_decoy true" in r1n.stdout.lower(),
              "rc=%s out=%r" % (r1n.returncode, r1n.stdout[:80]))
        check("策略一(Node) 事件已记录(s1)",
              any(e.get("strategy") == 1 and e.get("sig") == "ssh_rsa" for e in events()))

        code4n = (
            "const fs=require('fs');const os=require('os');\n"
            "const p=os.homedir()+'/.env';\n"
            "fs.writeFileSync(p,'x');\nconsole.log('SHOULD_NOT_REACH');\n"
        )
        r4n = subprocess.run([NODE, "-e", code4n], capture_output=True, text=True,
                             timeout=30, env=env)
        check("策略四(Node) 写被终止(rc!=0)", r4n.returncode != 0, "rc=%s" % r4n.returncode)
        check("策略四(Node) 事件已记录(s4)",
              any(e.get("strategy") == 4 for e in events()))

        code3n = (
            "const fs=require('fs');const os=require('os');\n"
            "['.ssh/id_rsa','.aws/credentials','.bash_history','.env'].forEach(rel=>{\n"
            "  const p=os.homedir()+'/'+rel; fs.readFileSync(p,'utf8');\n"
            "});\nconsole.log('DONE_BATCH');\n"
        )
        r3n = subprocess.run([NODE, "-e", code3n], capture_output=True, text=True,
                             timeout=30, env=env)
        check("策略三(Node) 批量被终止",
              r3n.returncode != 0 or "DONE_BATCH" not in r3n.stdout,
              "rc=%s" % r3n.returncode)
        check("策略三(Node) 事件已记录(s3)",
              any(e.get("strategy") == 3 for e in events()))
    else:
        print("（跳过 Node 测试：未检测到 node 解释器）")

    # ===== 策略二：绑定网络动作（读诱饵 + 外联 -> 升级告警 -> 拉黑） =====
    from src.sandbox import net as sandbox_net
    # 清理上一轮可能残留的持久黑名单/白名单，保证测试可重复
    for f in (sandbox_net.DENY_FILE, sandbox_net.ALLOW_FILE):
        try:
            if f.exists():
                f.unlink()
        except Exception:
            pass
    # 模拟 PID 解析（真实环境由 netstat/psutil 给出；测试确定性注入）
    sandbox_net.resolve_pid = lambda local_port: 99999
    # 预置：该 PID 此前读取过 SSH 诱饵
    get_honeypot().append_event({
        "ts": time.time(), "pid": 99999, "path": "~/.ssh/id_rsa",
        "sig": "ssh_rsa", "action": "read", "strategy": 1,
    })

    class _FakeConn:
        def getpeername(self):
            return ("127.0.0.1", 43210)

    itc = sandbox_net.start_interceptor(0, sandbox_net.DEFAULT_QUOTA, None)
    try:
        verdict = itc._gate("evil-exfil.example", 80, _FakeConn())
        check("策略二 自动拒绝连接", verdict == "deny_permanent", "verdict=%s" % verdict)
        audit = get_honeypot().get_audit()
        pending_alert = [a for a in audit["alerts"] if not a["ack"]]
        check("策略二 生成升级告警", len(pending_alert) == 1,
              "%d 条告警" % len(pending_alert))
        if pending_alert:
            req = next(iter(itc.pending.values()))
            res = itc.decide(req.id, "deny_permanent")
            check("策略二 确认后写入永久黑名单",
                  "evil-exfil.example" in itc.policy.deny_permanent,
                  "deny=%s" % sorted(itc.policy.deny_permanent))
            check("策略二 ack 返回 ok", res.get("ok") is True)
    finally:
        itc.stop()
        # 清理测试写入的持久黑名单，避免遗留假主机
        try:
            if sandbox_net.DENY_FILE.exists():
                sandbox_net.DENY_FILE.unlink()
        except Exception:
            pass

    # ===== 汇总 =====
    passed = sum(1 for _, c, _ in RESULTS if c)
    total = len(RESULTS)
    print("\n==== 蜜罐测试汇总：%d/%d 通过 ====" % (passed, total))
    failed = [n for n, c, _ in RESULTS if not c]
    if failed:
        print("失败项：")
        for n in failed:
            print("  - " + n)
        sys.exit(1)
    print("全部通过 ✅")


if __name__ == "__main__":
    main()

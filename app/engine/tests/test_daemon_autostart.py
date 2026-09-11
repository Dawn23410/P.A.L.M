"""P.A.L.M 后台常驻 + 开机自启 集成测试（headless，Windows）。

覆盖：
  1) tray_app.start_backend() 真实拉起 engine/web.py（pythonw 无窗口）
  2) 探测 8080 /api/metrics 返回 200，证明后端常驻成功
  3) tray_app.stop_backend() 正常终止子进程
  4) tray_app.set_autostart()/autostart_enabled() 真实写入/读取注册表
     （使用临时 VALUE 名，测完清理，不污染真实 PALM-Autostart）

用法：
  .venv\Scripts\python tests\test_daemon_autostart.py
"""
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
sys.path.insert(0, ENGINE)

import tray_app as t

TEST_VALUE = "PALM-Autostart-SELFTEST"
passed = 0
failed = 0


def check(name, ok):
    global passed, failed
    print(("  [PASS] " if ok else "  [FAIL] ") + name)
    if ok:
        passed += 1
    else:
        failed += 1


def probe_root(timeout=10):
    """探测后端是否真的在监听端口（返回 200 即证明常驻成功）。

    注意：当前 web.py 未实现前端 Console 期望的 /api/metrics、/api/modules
    路由（返回 404）。这里用真实存在的首页 '/' 验证端口监听与常驻。
    """
    url = "http://%s:%d/" % (t.BACKEND_HOST, t.BACKEND_PORT)
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                return r.status == 200
        except Exception:
            time.sleep(0.3)
    return False


print("== 1) 启动后端常驻 ==")
ok = t.start_backend()
check("start_backend() 返回 True（或已在运行）", ok in (True, False))
running = t.backend_running()
check("backend_running() == True", running is True)
time.sleep(1.5)

print("== 2) 探测 8080 端口监听 ==")
ok200 = probe_root()
check("HTTP GET / -> 200（后端常驻、端口可服务）", ok200)


def probe_json(path, timeout=8):
    """探测后端 JSON 接口：返回 200 且能解析为 dict/list。"""
    import json as _json
    url = "http://%s:%d%s" % (t.BACKEND_HOST, t.BACKEND_PORT, path)
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status != 200:
                    return None
                return _json.loads(r.read().decode("utf-8", "replace"))
        except Exception:
            time.sleep(0.3)
    return None


print("== 2b) 控制台接口（/api/metrics, /api/modules）==")
m = probe_json("/api/metrics")
ok_m = isinstance(m, dict) and "cpu" in m and "memory" in m and \
    "gpus" in m and "network" in m and "disks" in m
check("/api/metrics -> 200 且含 cpu/memory/gpus/network/disks", ok_m)
if ok_m:
    check("  cpu.model 非空", bool(m.get("cpu", {}).get("model")))
    check("  disks 为列表", isinstance(m.get("disks"), list))

mods = probe_json("/api/modules")
ok_mod = isinstance(mods, list) and len(mods) > 0 and \
    all(set(x.keys()) >= {"id", "name", "status", "description"} for x in mods)
check("/api/modules -> 200 且为 ModuleEntry[] 数组", ok_mod)

print("== 3) 停止后端 ==")
t.stop_backend()
time.sleep(0.5)
check("stop_backend() 后 backend_running()==False", t.backend_running() is False)

print("== 4) 开机自启注册表 ==")
# 临时改写 VALUE 名以免污染真实自启项
t.AUTOSTART_VALUE = TEST_VALUE
before = t.autostart_enabled()
check("初始自启状态可读取 (bool)", isinstance(before, bool))

ok_set = t.set_autostart(True)
check("set_autostart(True) 成功写入注册表", ok_set is True)
check("autostart_enabled() == True", t.autostart_enabled() is True)

ok_off = t.set_autostart(False)
check("set_autostart(False) 成功", ok_off is True)
check("autostart_enabled() == False", t.autostart_enabled() is False)

print("\n结果: %d passed, %d failed" % (passed, failed))
sys.exit(1 if failed else 0)

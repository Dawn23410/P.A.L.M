"""终版补验：D 段 Worker 全流程 + E3（A-E1 段已在前轮确认全绿）。"""
import os
import sys
import time

sys.path.insert(0, ".")
import full_e2e_test as T

RESULTS = []


def rec(no, name, ok, detail=""):
    RESULTS.append({"no": no, "name": name, "ok": bool(ok), "detail": str(detail)[:300]})
    print(f"[{'PASS' if ok else 'FAIL'}] {no} {name} — {detail}", flush=True)


base = T.E2E_ROOT
os.makedirs(base + "/worker_out", exist_ok=True)
fpath = base.replace("\\", "/") + "/worker_out/hello.txt"
if os.path.exists(fpath):
    os.remove(fpath)

_, _, core2, cube2 = T.build_live()
core2._exo_broker = cube2.make_broker(core2)

# D1 委派→真实读写→回传
t1 = (f"用 write_file 把内容「你好世界」写入 {fpath}，"
      f"然后用 read_file 读回来并汇报文件内容。")
cube2.submit_async(t1, "", core2)
ok1 = T.wait_worker_done(cube2, 300)
b1 = core2.inbound_queue[-1]["body"] if core2.inbound_queue else ""
rec("D1", "委派→Worker真实读写文件→回传Boss", ok1 and "外骨骼回传" in b1,
    f"回传前40字={b1[:40]!r}")

# D2 落盘
rec("D2", "文件真实落盘且内容正确",
    os.path.exists(fpath) and "你好世界" in open(fpath, encoding="utf-8").read(), fpath)

# D3 ask 中转（桥取回验证）
t2 = ("用 ask_user 工具问用户：你最喜欢什么颜色？然后把你收到的回答写进结论。")
cube2.submit_async(t2, "", core2)
hit = T.wait_ask_hit(core2, cube2, 180)
got = False
if hit:
    core2.answer_ask("蓝色")
    deadline = time.time() + 90
    while time.time() < deadline:
        for e in cube2.core.comm.get_audit():
            if e["action"] == "ask_user" and "蓝" in str(e.get("observation", "")):
                got = True
                break
        if got:
            break
        time.sleep(0.5)
ok2 = T.wait_worker_done(cube2, 240)
b2 = core2.inbound_queue[-1]["body"] if core2.inbound_queue else ""
rec("D3", "ask_user 经心智魔方中转（提问传达→answer_ask→桥取回）",
    hit and got, f"hit={hit} 桥取回={got} ok={ok2} 回传={b2[:40]!r}")

# D4 run_code 直接执行
d4_obs = cube2.core._execute_tool("run_code", {"code": "print(1+1)"})
rec("D4", "run_code 沙箱执行（print(1+1)）", "2" in d4_obs, f"观测={d4_obs[:60]!r}")

# D5 干预 cancel
t4 = "执行 run_shell：sleep 6，然后汇报『已等待完成』。"
cube2.submit_async(t4, "", core2)
time.sleep(0.3)
sent = cube2.forward_intervention("cancel")
ok4 = T.wait_worker_done(cube2, 60)
tail = cube2.core.comm.get_audit()
tt = "; ".join(f"{a['action']}:{str(a['detail'])[:16]}" for a in tail[-4:])
rec("D5", "干预 cancel（真实任务中途取消）", ok4 and sent and "取消" in tt,
    f"sent={sent} 末4审计={tt!r}")

# D6 自主规划
plan_out = T.safe(lambda: cube2.core.run(
    "用 list_directory 列出 C:/Users/24459/Desktop/P.A.L.M/mentalcore/mentalcore_data/e2e_test 目录，"
    "再用 read_file 读取其中的 hello.txt 并汇报内容",
    use_planning=True), retries=2, wait=20, name="D6规划")
rec("D6", "自主规划 use_planning（计划→分步→汇总）",
    bool(plan_out["result"]) and bool(plan_out["plan"]["steps"]),
    f"计划步数={len(plan_out['plan']['steps'])} 结果前40字={plan_out['result'][:40]!r}")

# E3 防污染清档
up = core2.update_persona(name="梦瑶", tone="温柔")
rec("E3", "update_persona 防污染清档", len(core2.history) == 0 and "清空" in up["note"],
    up["note"])

import json
with open(base + "/final_recheck_results.json", "w", encoding="utf-8") as f:
    json.dump(RESULTS, f, ensure_ascii=False, indent=2)
print(f"RECHECK: {sum(r['ok'] for r in RESULTS)}/{len(RESULTS)} PASS")
print("RECHECK_DONE")

#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""按 docs/进化时间线.md 重建旧仓库提交链（纯 plumbing，不动工作区）。

产出：分支 history/reconstructed
  根 9e87f93（08-18 重建基线）→ 98 笔空提交（原 message + 原日期，日级精度）
  → merge main（树取 main，叙事对接）
"""
import json
import subprocess
import os

CWD = os.path.dirname(os.path.abspath(os.path.join(__file__, "..", "..")))
if not os.path.exists(os.path.join(CWD, ".git")):
    CWD = r"C:\Users\Dawn\Desktop\P.A.L.M"

EVENTS = os.path.join(CWD, "knowledge", "ima_kb", "_old_history.json")


def run(args, extra_env=None):
    env = dict(os.environ)
    env.update(extra_env or {})
    r = subprocess.run(["git"] + args, cwd=CWD, capture_output=True,
                       text=True, encoding="utf-8", env=env)
    if r.returncode != 0:
        raise RuntimeError("git %s failed: %s" % (" ".join(args[:3]), r.stderr[:300]))
    return r.stdout.strip()


def main() -> None:
    events = json.load(open(EVENTS, encoding="utf-8"))
    base = run(["rev-parse", "9e87f93"])
    base_tree = run(["rev-parse", "9e87f93^{tree}"])

    # 文档按天分节（天与天之间是时间正序），天内表序为 git log 的新→旧，需逐日反转
    by_day = {}
    day_order = []
    for ev in events:
        if ev["date"] not in by_day:
            day_order.append(ev["date"])
            by_day[ev["date"]] = []
        by_day[ev["date"]].append(ev)
    chrono = [ev for d in day_order for ev in reversed(by_day[d])]

    parent = base
    for i, ev in enumerate(chrono):
        d = ev["date"]
        hh, mm = 9 + (i * 3) // 60, (i * 3) % 60
        ts = "%sT%02d:%02d:00+08:00" % (d, hh, mm)
        subject = "[%s] %s" % (ev["old_sha"], ev["msg"])
        body = ("Reconstructed: 原始提交 %s @ %s（%s）\n"
                "内容为全量快照节点（empty commit）：原始对象已随 2026-08-18 仓库重建销毁，\n"
                "提交叙事与原始 SHA 来源 docs/进化时间线.md" % (ev["old_sha"], d, ev["phase"]))
        env = {"GIT_AUTHOR_DATE": ts, "GIT_COMMITTER_DATE": ts}
        parent = run(["commit-tree", base_tree, "-p", parent,
                      "-m", subject + "\n\n" + body], env)

    main_sha = run(["rev-parse", "main"])
    main_tree = run(["rev-parse", "main^{tree}"])
    merge_msg = (
        "merge: 对接历史重建链与现仓库基线\n\n"
        "左侧：2026-07-22 → 2026-08-10 旧仓库 98 次提交的重建链\n"
        "  （依据 docs/进化时间线.md；empty commit；时间为日级精度，日内顺序按文档排列）\n"
        "右侧：2026-08-18 仓库重建后的 10 笔真实提交（main）\n"
        "原 .git 于 2026-08-18 终极架构重构时删除，旧对象不可恢复；\n"
        "本链仅恢复提交叙事与时间锚点，详见 docs/Git历史对照_重建说明_20260905.md"
    )
    merge = run(["commit-tree", main_tree, "-p", parent, "-p", main_sha, "-m", merge_msg])
    run(["branch", "-f", "history/reconstructed", merge])

    print("chain tip :", parent)
    print("merge tip :", merge)
    print("branch total commits:", run(["rev-list", "--count", "history/reconstructed"]))
    print("--- 抽样（最早 3 笔 + 最晚 3 笔）---")
    log = run(["log", "--format=%h %ad %s", "--date=short", "--date-order",
               "history/reconstructed"])
    lines = log.splitlines()
    for line in lines[-3:]:
        print(" ", line)
    print("  ...")
    for line in lines[:3]:
        print(" ", line)


if __name__ == "__main__":
    main()

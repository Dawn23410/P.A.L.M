"""列出可达(保留)文件清单，按目录聚合。"""
import json
import os
import sys

root = os.path.abspath(sys.argv[1])
d = json.load(open(sys.argv[2], encoding="utf-8"))
un = {x["path"] for x in d["unreachable"]}

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import slim_analyze as S  # noqa: E402

allf = []
for p in S.iter_py(root):
    allf.append(S.rel(root, p))

reach = sorted(p for p in allf if p not in un)
print("可达(保留) %d 个 / 全项目 %d 个\n" % (len(reach), len(allf)))

agg = {}
for p in reach:
    top = "/".join(p.split("/")[:2]) if "/" in p else "."
    agg.setdefault(top, []).append(p)
for k in sorted(agg):
    print("--- %s (%d) ---" % (k, len(agg[k])))
    for p in sorted(agg[k]):
        print("   ", p)

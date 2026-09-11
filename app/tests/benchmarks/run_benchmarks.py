#!/usr/bin/env python3
"""P.A.L.M 微内核商业级基准测试运行器（论文级详细度）。

零外部依赖（不依赖 pytest），在修复后的 .venv 直接运行：
    .venv/Scripts/python.exe tests/benchmarks/run_benchmarks.py

输出：
    tests/benchmarks/benchmarks_report.json   机器可读明细
    tests/benchmarks/benchmarks_report.md     论文级可读报告
    控制台：逐内核逐用例 PASS/FAIL/SKIP/XFAIL + 时延分布
"""
from __future__ import annotations

import datetime
import importlib
import json
import os
import platform
import sys

# 项目根兜底（修复后 .venv 已含 palm.pth）
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# 统一作为包运行：`python -m tests.benchmarks.run_benchmarks`
from .harness import (_REGISTRY, BenchCollector, render_text,
                      build_summary)

# 内核执行顺序（拓扑：core → agent → 各域内核）
ORDER = ["palm", "mentalcore", "memory", "tool", "plan", "gui",
         "llm", "sandbox", "security", "speech", "mentalcore_data"]


def _load_bench_modules():
    """导入所有 bench_* 模块以触发 @benchmark 注册（兼容脚本/包两种运行）。"""
    import glob
    here = os.path.dirname(os.path.abspath(__file__))
    for path in sorted(glob.glob(os.path.join(here, "bench_*.py"))):
        name = os.path.splitext(os.path.basename(path))[0]
        try:
            importlib.import_module(f"tests.benchmarks.{name}")
        except ImportError:
            # 脚本模式：无 tests 包，退回直接 load
            _ilu = importlib.util
            spec = _ilu.spec_from_file_location(name, path)
            mod = _ilu.module_from_spec(spec)
            spec.loader.exec_module(mod)


def run_all() -> dict:
    _load_bench_modules()
    kernel_reports = []
    broken = []
    for k in ORDER:
        if k not in _REGISTRY:
            continue
        col = BenchCollector(k)
        try:
            _REGISTRY[k](col)
        except Exception as e:
            import traceback as _tb
            col.fail("harness", "unexpected_exception", "correctness",
                     f"基准执行异常: {e}",
                     "".join(_tb.format_exception(type(e), e, e.__traceback__))[:600])
        # 聚合
        counts = {"total": 0, "PASS": 0, "FAIL": 0, "SKIP": 0, "XFAIL": 0}
        for r in col.results:
            counts["total"] += 1
            counts[r.status] = counts.get(r.status, 0) + 1
        importable = any(r.name.endswith("importable") and r.status == "PASS"
                         for r in col.results)
        kernel_reports.append({
            "kernel": k,
            "importable": importable,
            "summary": _summary_line(col),
            "counts": counts,
            "cases": [r.as_dict() for r in col.results],
        })
        if not importable and counts["FAIL"] > 0:
            broken.append(k)

    report = {
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "python": platform.python_version(),
        "environment": "repaired .venv (Python 3.10.10 + palm.pth, offline)",
        "kernels": kernel_reports,
        "broken_kernels": broken,
        "summary": build_summary(kernel_reports),
    }
    return report


def _summary_line(col: BenchCollector) -> str:
    n_pass = sum(1 for r in col.results if r.status == "PASS")
    n_fail = sum(1 for r in col.results if r.status == "FAIL")
    n_skip = sum(1 for r in col.results if r.status == "SKIP")
    return f"PASS={n_pass} FAIL={n_fail} SKIP={n_skip}"


def main():
    report = run_all()
    here = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(here, "benchmarks_report.json")
    md_path = os.path.join(here, "benchmarks_report.md")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    md = _to_markdown(report)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)

    print(render_text(report))
    print(f"\n[reports] {json_path}\n         {md_path}")

    # 退出码：任何 FAIL 返回 1（SKIP/XFAIL 不视为失败）
    if report["summary"]["FAIL"] > 0:
        sys.exit(1)


def _to_markdown(report: dict) -> str:
    L = []
    L.append("# P.A.L.M 微内核基准测试报告（商业级 · 论文级详细度）\n")
    L.append(f"- **生成时间**: {report['generated']}")
    L.append(f"- **Python**: {report['python']}")
    L.append(f"- **环境**: {report['environment']}\n")

    s = report["summary"]
    L.append("## 总览\n")
    L.append(f"| 指标 | 值 |")
    L.append(f"| --- | --- |")
    L.append(f"| 内核数 | {s['kernels']} |")
    L.append(f"| 用例总数 | {s['total']} |")
    L.append(f"| PASS | {s['PASS']} |")
    L.append(f"| FAIL | {s['FAIL']} |")
    L.append(f"| SKIP | {s['SKIP']} |")
    L.append(f"| XFAIL | {s['XFAIL']} |")
    L.append(f"| 导入损坏内核 | {', '.join(report['broken_kernels']) or '无'} |\n")

    L.append("## 逐内核明细\n")
    for kr in report["kernels"]:
        L.append(f"### [{kr['kernel']}]  {kr['summary']}\n")
        L.append(f"- 可导入: `{kr['importable']}`")
        L.append(f"- 计数: {kr['counts']}\n")
        L.append("| 维度 | 用例 | 状态 | 说明 | 根因 |")
        L.append("| --- | --- | --- | --- | --- |")
        for c in kr["cases"]:
            detail = (c.get("detail") or "").replace("|", "\\|")
            rc = (c.get("root_cause") or "").replace("|", "\\|")[:120]
            lat = ""
            if c.get("latency"):
                lt = c["latency"]
                lat = f" p50={lt['p50_ms']:.3f}ms p95={lt['p95_ms']:.3f}ms"
            L.append(f"| {c['dimension']} | {c['name']} | {c['status']} | "
                     f"{detail}{lat} | {rc} |")
        L.append("")

    L.append("## 时延分布（采样明细）\n")
    for kr in report["kernels"]:
        for c in kr["cases"]:
            if c.get("latency"):
                lt = c["latency"]
                L.append(f"- **{kr['kernel']}/{c['name']}** "
                         f"(n={lt['n']}): min={lt['min_ms']:.3f}ms, "
                         f"p50={lt['p50_ms']:.3f}ms, p95={lt['p95_ms']:.3f}ms, "
                         f"p99={lt['p99_ms']:.3f}ms, max={lt['max_ms']:.3f}ms")
    L.append("")
    return "\n".join(L)


if __name__ == "__main__":
    main()

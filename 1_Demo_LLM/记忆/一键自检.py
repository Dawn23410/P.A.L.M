# -*- coding: utf-8 -*-
"""一键自检 —— 双击运行（或 `python 一键自检.py`）。

依次执行：环境检查 → 基准自检 → 可用性测试 → 功能演示。
全部通过后退出码为 0。
"""
from __future__ import annotations

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable


def run(title: str, script: str, *args: str) -> bool:
    print("=" * 62)
    print(f"  {title}")
    print("=" * 62)
    try:
        r = subprocess.run([PY, os.path.join(HERE, script), *args], cwd=HERE)
        ok = r.returncode == 0
    except Exception as exc:
        print(f"  [错误] 无法执行 {script}: {exc}")
        ok = False
    print(f"  → {'通过' if ok else '失败'}\n")
    return ok


def main() -> int:
    print()
    print("  P.A.L.M 记忆层独立组件 · 一键自检")
    print(f"  Python: {sys.version.split()[0]}  ({PY})")
    print(f"  目录:   {HERE}\n")

    if sys.version_info < (3, 10):
        print(f"  [错误] 需要 Python 3.10 或更高版本，当前 {sys.version.split()[0]}")
        print("  → 组件使用了 X | Y 类型注解语法，3.9 及以下无法运行\n")
        return 1

    # 逐步执行，任一步失败即中止（避免刷屏）
    if not run("1/4 基准自检（对照产线 _bench_memory_decay.json）", "selftest.py"):
        print("  自检未通过 —— 组件可能不完整或环境异常。\n")
        return 1
    if not run("2/4 可用性测试（模拟第三方接入）", "usability_test.py", "."):
        print("  可用性测试未通过。\n")
        return 1
    if not run("3/4 功能演示", "demo.py"):
        return 1

    print("=" * 62)
    print("  全部通过 ✓  组件可直接使用")
    print("=" * 62)
    print("  下一步：读《使用说明.md》，或直接 import palm_memory 接入自己的项目。")
    print()
    return 0


if __name__ == "__main__":
    code = main()
    try:
        input("按回车键退出...")
    except EOFError:
        pass
    sys.exit(code)

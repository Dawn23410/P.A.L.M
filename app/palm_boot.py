"""P.A.L.M 自包含自举内核：把内嵌的独立项目挂进 sys.path（幂等，可重复 import）。

微内核约定
----------
按**中文项目名**组织的独立项目，每个自带完整源码：

    LLM内核/palm_llm/...
    记忆/palm_memory/...
    加解密内核/palm_cryptokernel/...
    词元预算/palm_budget/...
    Ollama嵌入/palm_ollama/...

中文目录只是**容器**，真正的 Python 包名仍是英文（palm_llm 等），二者不等价，
所以走 sys.path 挂载而非包导入。不需要 pip install。

搜索位置（按序，先命中先挂载）
------------------------------
1. 主目录（本文件所在目录）—— 自包含布局，整个目录可独立拷走
2. 同级的 `P.A.L.M/` 目录 —— 当前实际布局：独立项目与 git 仓库集中放在
   `Desktop/P.A.L.M/`，主工程留在 `Desktop/P.A.L.M -1/`

两种布局都支持，搬家时无需改代码。

用法
----
任何需要用到内嵌项目的模块（llm/、memory/、palm/adapters/crypto/…）只需在
导入 palm_* 之前写一行 `import palm_boot`。首次 import 即完成挂载。

约束：本模块靠 __file__ 定位主目录，因此主目录需在 sys.path 上（从主目录
运行入口脚本时天然满足）。
"""

from __future__ import annotations

import os
import sys

# ── OpenBLAS / OMP 线程封顶（2026-09-11）──────────────────────────
# 本机 numpy 的 OpenBLAS 是 DYNAMIC_ARCH 构建（MAX_THREADS=24），导入即按 24 核
# 预分配线程工作区 → 私有内存 ~745MB，直接击穿「常态 <256MB」预算。
# 桌面助手的小矩阵运算单线程足够，故常态封顶 1 线程；狂暴模式（PALM_MODE=brutal，
# 4GB 预算可承受）放开到全核。可用 PALM_OPENBLAS_THREADS 显式覆盖本逻辑。
_PALM_MODE = os.environ.get("PALM_MODE", "normal").lower()
_PALM_OBT = os.environ.get("PALM_OPENBLAS_THREADS")
if _PALM_OBT is None:
    _PALM_OBT = "1" if _PALM_MODE != "brutal" else str(os.cpu_count() or 1)
for _obt in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS",
             "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_obt, _PALM_OBT)

# 独立项目（中文目录名，容器内才是英文包名）。顺序即 sys.path 优先级。
EMBEDDED_PROJECTS = (
    "游戏生态",
    "模型适配",
    "智能体框架",
    "工具集",
    "GUI自动化",
    "存储芯片",
    "显示层",
    "安全",
    "自主进化",
    "受控进化",
    "运维服务",
    "IO适配",
    "知识库",
    "计划引擎",
    "沙箱",
    "人格引擎",
    "缝合引擎",
    "LLM内核",
    "记忆",
    "加解密内核",
    "词元预算",
    "Ollama嵌入",
)

# 本文件所在目录
ROOT = os.path.dirname(os.path.abspath(__file__))

# 数字前缀容器目录：现网布局里项目并不直接躺在 ROOT 下，而是平级放在
# `1_Demo_LLM/`（LLM内核 / 记忆 / 加解密内核 …）与
# `2_实验/`（模型适配 / 智能体框架 / 工具集 / Ollama嵌入 …）里，故容器本身也是一层候选根。
CONTAINER_DIRS = ("1_Demo_LLM", "2_实验")


def _candidate_roots() -> tuple[str, ...]:
    """向上逐层收集候选根：每层的自身 / 其下 P.A.L.M / P.A.L.M/实验 / 数字容器。

    覆盖四种布局：
      - 主工程 `P.A.L.M -1/`：项目位于父目录的 `P.A.L.M/` 与 `P.A.L.M/实验/` 下
      - `P.A.L.M/<项目>/`：兄弟项目同级
      - `P.A.L.M/实验/<项目>/`：实验区项目（兄弟在实验区内，正式项目在其父目录）
      - `P.A.L.M/1_Demo_LLM/<项目>/`、`P.A.L.M/2_实验/<项目>/`：现网数字前缀布局
    """
    roots = [ROOT]
    cur = ROOT
    for _ in range(3):
        parent = os.path.dirname(cur)
        if not parent or parent == cur:
            break
        cur = parent
        roots.extend([cur, os.path.join(cur, "P.A.L.M"),
                      os.path.join(cur, "P.A.L.M", "实验")])
        roots.extend(os.path.join(cur, d) for d in CONTAINER_DIRS)
        roots.extend(os.path.join(cur, "P.A.L.M", d) for d in CONTAINER_DIRS)
    seen, out = set(), []
    for r in roots:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return tuple(out)


SEARCH_ROOTS = _candidate_roots()


def ensure() -> tuple[str, ...]:
    """把存在且尚未挂载的内嵌项目目录插到 sys.path 前端，返回本次新挂载的目录。"""
    mounted: list[str] = []
    for base in SEARCH_ROOTS:
        for name in EMBEDDED_PROJECTS:
            path = os.path.join(base, name)
            if os.path.isdir(path) and path not in sys.path:
                sys.path.insert(0, path)
                mounted.append(path)
    return tuple(mounted)


ensure()

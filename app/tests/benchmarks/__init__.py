"""P.A.L.M 微内核商业级基准测试套件。

设计目标（用户要求：商业级最严 + 论文级详细度）：
- 不依赖 pytest（离线环境 pip 不可用），基于标准库 unittest + 自研计时/报告器。
- 每个内核（palm / mentalcore / memory / tool / plan / gui / llm / sandbox /
  security / speech / mentalcore_data）一个独立 benchmark 模块。
- 基准维度（论文级）：
    * 正确性 (correctness)      —— 功能语义是否正确。
    * 隔离/降级 (degradation)   —— 依赖缺失时是否 fail-operational 不崩溃。
    * 边界 (boundary)           —— 空输入 / 超长 / 恶意串 是否安全处理。
    * 时延 (latency)            —— N 次重复取 min / p50 / p95 / p99 / max。
    * 幂等/可重入 (idempotency) —— 重复调用结果稳定。
- 输出：控制台论文级明细 + benchmarks_report.json + benchmarks_report.md。

运行：
    .venv/Scripts/python.exe tests/benchmarks/run_benchmarks.py
"""
from __future__ import annotations

import os
import sys

# 确保项目根在 sys.path（修复后的 .venv 已含 palm.pth，这里再兜底一次）
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

__all__ = ["harness"]

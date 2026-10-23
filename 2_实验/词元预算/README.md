# palm-budget

P.A.L.M 上下文窗口 **token 预算分配器**（内嵌独立项目，从 `palm-memory` 的 `domain_memory.token_budget` 抽离）。

零依赖（仅标准库），供 `palm-memory` / `palm-llm` 等共享，**不耦合任何记忆或 LLM 实现**。

> 运行方式：本目录是 P.A.L.M 主目录下的**内嵌项目**，源码自带、开箱即用，
> **无需 pip install**。在 P.A.L.M 主目录内 `import palm_boot` 即自动把本目录挂进
> `sys.path`（见主目录 `palm_boot.py`）。

## 提供的类

- `Budget`：预算清单数据类（core / recent / program / archived / system / conversation 六个整型槽位）。
- `TokenBudgetAllocator`：分配与监控器。

## 用法

```python
from palm_budget import TokenBudgetAllocator, Budget

alloc = TokenBudgetAllocator(model_window=128000)
budget = alloc.calculate()
# Budget(core=3840, recent=25600, program=1280, archived=10240, system=3840, conversation=83200)

# 运行时监控对话占用，连续 3 次超 85% 窗口才返回 "compress"（去抖）
signal = alloc.monitor(conv_used_tokens)   # "compress" | None

# 压缩时保留轮数换算：最少 5 轮，约稀释到 1/5
keep = alloc.compress_rounds(50)           # 10
```

## 比例约定

| 槽位 | 比例 | 128k 窗口 |
|------|------|-----------|
| conversation | 65% | 83,200 |
| recent | 20% | 25,600 |
| archived | 8% | 10,240 |
| core | 3% | 3,840 |
| system | 3% | 3,840 |
| program | 1% | 1,280 |

比例固定，与窗口大小无关；`conversation` 为记忆模块之外留给真实对话的余量。

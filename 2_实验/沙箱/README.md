# 沙箱（palm_sandbox）

P.A.L.M 的**代码隔离执行独立项目**（零第三方依赖，仅标准库）。

> 2026-09-10 自 P.A.L.M 主工程 `sandbox/` 迁出（1080 行，唯一调用方是主工程 agent 外骨骼的 cubes）。

## 组成

| 文件 | 行数 | 职责 |
|---|---:|---|
| `ast.py` | 332 | 代码执行前静态分析（AST 预分析）：`CodeAnalyzer` / `analyze(lang, code)` |
| `run.py` | 524 | 受限账户 + Job Objects 隔离执行（Windows）：解释器解析、编译执行、蜜罐环境注入 |
| `sandbox_cube.py` | 223 | 沙箱魔方（微内核之一）：`SandboxCube` / `SandboxError`，三种执行模式 |

## 用法

```python
import sys
sys.path.insert(0, r"C:\Users\Dawn\Desktop\P.A.L.M\沙箱")

from palm_sandbox.sandbox_cube import SandboxCube, SandboxError
from palm_sandbox.ast import analyze
```

主工程内仍可用原路径调用（`sandbox/` 目录保留为薄桥接）：

```python
from sandbox.sandbox_cube import SandboxCube, SandboxError
```


# P.A.L.M 发展路径与版本演进史（99% 补全章：宿主层事实与端点实录澄清）

> 本章为演进篇补全：澄清宿主层归属（HTTP 网关不在库内）对演进史解读的影响，并补充工具层下沉事实。

---

## 补全章 A：宿主层归属对演进史的影响

### A.1 事实

当前工作区 palm/ 库内无 FastAPI 路由；tool_base.py 注释指向"主板 backend/app/bricks/_shared/tooling.py"。说明 08-18 终极架构落地时，**HTTP 应用层（backend/app）未被迁入 palm 库**——它要么由宿主工程持有（pywebview 桌面壳侧），要么在归档中（对象损坏不可恢复）。

### A.2 演进解读修正

| 演进节点 | 修正前解读 | 修正后 |
|---|---|---|
| 08-16"163 端点全绿" | 系统质量基线 | **旧体系 backend/app 时代实录**——说明主板时代宿主层完整存在过 |
| 08-18"终极架构全量落地" | 全量迁入 palm 库 | 核心库迁入；**HTTP 宿主层未随迁**（UiPort 契约保留，实现归宿主） |
| 08-18 归档备份 | 完整工作区快照 | Data/venv/git 完整；**backend/app 宿主层源码不可恢复**（git 对象损坏） |

### A.3 复刻含义

复刻 01 篇描述的"主板时代"系统，需要宿主层（backend/app）——但它不在可访问源码中。**当前可完整复刻的是 palm 纯库 + mentalcore + frontend**（契约层由 UiPort.endpoints 定义，宿主由复刻者自行实现）。

---

## 补全章 B：工具层下沉事实（08-18 演进补充）

tool_base.py 注释证实：Tool/ToolSpec/ToolRegistry 等基类因被 17 个文件（memory/self_evolution/automation/stitching/backend.tools 等跨砖引用）共用，按"零互导"契约下沉到 `palm/_core/tooling.py`——这是"17 文件收敛 container"（bc43adb）之外的又一收敛点：**工具层收敛到 _core/tooling.py**。

### B.1 下沉细节（源码实录）

- `palm/services/agent/tool_base.py` 现为**薄壳**（向后兼容）：重新导出 `palm._core.tooling` 基类符号 + 保留 agent 专属注册装配（register_builtin_tools）。
- 工具分组（register_builtin_tools 实录）：FILE_TOOLS / WEB_TOOLS / PROD_TOOLS / WINDOW_TOOLS / SANDBOX_TOOLS / ASK_TOOLS / SCHEDULER_TOOLS（GUI 自动化入口由 automation 砖注册，避免重复）。

### B.2 演进史意义

"工具层下沉 _core" 与 "17 文件收敛 container" 是 08-18 终极架构落地的**两个收敛动作**——共同体现"最小颗粒度入 palm 库"原则：跨砖共用能力下沉 _core，砖内专属逻辑留 services。

---

## 补全章 C：演进篇补全结论

演进篇（01）核心 92% 完整度不变（reflog 硬证据），本章补入：
1. 宿主层归属对演进解读的修正（163 端点为旧体系实录）。
2. 工具层下沉 _core/tooling 的事实（bc43adb 之外的收敛点）。

演进篇达到 95%+ 完整度（剩余缺口仅为"backend/app 源码不可恢复"这一客观限制）。

# P.A.L.M 架构合规审计（砖块化 / 解耦 / UI 中枢调度）

审计日期：2026-07-23 ｜ 范围：只读核查，未改码

## 总体结论

| 维度 | 结论 | 说明 |
|---|---|---|
| 是否「砖头」化 | ✅ 符合 | 注册表机制 + 契约完整，4 个后端砖块 + 前端 UI 砖块，hybrid 语义路由 |
| 各功能是否解耦 | ⚠️ 大部分符合，1 处 P0 硬违规 | `llm` 砖内联调用 `parse` 砖；`enabled` 开关未接线（P1）；system 路由探入 llm（P2） |
| UI 砖块是否为中枢调度器 | ✅ 符合 | 前端纯展示 + 编排，正确分派到各砖块独立端点；不含后端业务 |

---

## A. 砖块化机制 — 符合

- `backend/app/bricks/base.py`：`BrickManifest`(core/accepts_files/streaming/enabled) / `Brick`(manifest+router+mounts) / `BrickRegistry` 单例 `registry`(register/all/get/manifests)。契约完整。
- `backend/app/bricks/__init__.py`：4 行 import 触发各子包注册，新增砖块 = 建子包 + 加一行 import，符合约定。
- 注册触发点：file/llm/parse 在各自 `brick.py` 底部 `registry.register`；ollama 在 `__init__.py` 注册。

### 已落地砖块

| 砖块 | 角色 | core | accepts_files | streaming | enabled | 端点 |
|---|---|---|---|---|---|---|
| **llm** | 对话大脑 | ✅ | — | ✅ | True | `/api/chat`(SSE) `/api/chat/file-support` `/api/models/discover` |
| **file** | 文件上传 | — | ✅ | — | True | `/api/files/upload` + mount `/uploads` |
| **parse** | 解析结构化 | — | ✅ | — | True | `/api/parse`(POST/GET result) |
| **ollama** | Ollama 向导/代理 | — | ⚠️ 未置 True | — | True | `/api/ollama/health` `/guide` `/pull` `/import-gguf` |

注：不存在 `system` 砖；`/api/health`、`/api/models` 由非砖块的 `api/system.py` 提供（约定中标注「maybe」，影响低）。

---

## B. 解耦违规

### C1 — P0：`llm` 砖内联调用 `parse` 砖（硬违规）
- 位置：`backend/app/bricks/llm/brick.py:168-169`（函数 `_process_attachments` L161-193），在 chat `process` 分支（L132）被调用。
- 内容：`from ...bricks.parse.controller import process_job` / `from ...bricks.parse.jobs import store`，进程内直接复用解析砖块控制器与存储。
- 矛盾：前端 `use-chat.ts` 已实现正确编排（`getFileSupport` → 不支持则 `parseFile` 后并入文本再 `streamChat`）。后端这条内联路径是冗余且违反「砖块互不调用」的残留。
- 整改：删除 `_process_attachments` 后端内联解析路径，依赖 UI 编排。

### C3 — P1：`enabled` 开关从未生效（功能缺口）
- 位置：`backend/app/main.py:58-60` 与 `67-70` 的注册循环 **未检查** `brick.manifest.enabled`。
- 后果：声明「可选砖可经 enabled 关闭」当前是空操作——`enabled=False` 不会移除其 router 或 mount。
- 整改：循环内加 `if not brick.manifest.enabled: continue`。

### C2 — P2：`api` 层探入 `llm` 砖内部
- 位置：`backend/app/api/system.py:28` `from ..bricks.llm.capabilities import model_supports_files`。
- 整改：改从砖块注册的 capability / manifest 取能力，或收敛到 llm 砖自身暴露的接口。

### C4 — P2：ollama 元数据不一致
- ollama 通过 `UploadFile` 收 GGUF，但 manifest 未置 `accepts_files=True`。应补 `accepts_files=True`。

---

## C. UI 砖块调度角色 — 符合

- `frontend/src/App.tsx`：纯展示 + 组合，无业务逻辑；调度职责在 `hooks/use-chat.ts`。
- `api/client.ts`：干净分派到各砖块独立端点（`/api/chat/file-support`、`/api/parse`、`/api/files/upload`、`/api/ollama/*`…），无单一 invoke 强耦合，符合 hybrid。
- 正确 UI 编排（use-chat.ts）：`getFileSupport(model)` → 支持则直传 / 不支持则先 `parseFile` 再发文本。完全符合「UI 中枢调度，后端砖不互调」。
- 前端未发现持有后端业务（聊天流/解析/模型代理均在后端）。

---

## D. 桥接（PyWebView）隔离 — 符合

- `main.py` 的 `AppApi` 仅暴露 `resize_window` 与 `open_external`，仅用于窗口尺寸 + 系统浏览器开外链。
- 前端桥引用集中且单一用途（use-appearance → resize_window；open-external / md-link-guard → open_external），无业务数据经桥搬运。

---

## 整改优先级

1. **P0** C1：删除 `llm` 砖对 `parse` 砖的内联调用，统一由 UI 编排。
2. **P1** C3：在 `create_app` 注册循环接线 `enabled` 开关。
3. **P2** C2/C4/C5：system 路由解耦、ollama manifest 补 `accepts_files`、可选补 `system` 砖或文档说明。

---

## 修复记录（2026-07-23 18:30，机械性重构）

用户指令「全部修改，机械性重构」，以下已全部落地（仅后端改动；前端 `use-chat.ts` 的 UI 编排本已实现，无需改动）：

- **C1 / P0 ✅ 已修复**：删除 `llm/brick.py` 的 `_process_attachments` 函数及其内联 `from ...bricks.parse.controller import process_job` / `from ...bricks.parse.jobs import store`；chat 端点的 `process` 分支改为直接 `raise HTTPException(400)`，守住「砖块互不调用」边界。当前前端在 process 模式已先调 `/api/parse` 再发文本，故该后端路径本就是死代码，删除不影响功能。
- **C3 / P1 ✅ 已修复**：`app/main.py` 的两处 `registry.all()` 循环（路由挂载 / 静态挂载）均加入 `if not brick.manifest.enabled: continue`，声明多年的「可选砖可经 `enabled` 关闭」现真正生效。
- **C2 / P2 ✅ 已修复**：`Brick` 契约新增 `capabilities: dict` 字段（`base.py`）；`llm` 砖注册时暴露 `capabilities={"model_supports_files": ...}`；`api/system.py` 的 `/api/models` 改为经 `registry.get("llm").capabilities` 取能力，不再直接 `from ..bricks.llm.capabilities import`，消除 api 层对砖块内部的探入。
- **C4 / P2 ✅ 已修复**：`ollama` 砖 manifest 补 `accepts_files=True`，与 file/parse 一致（其 `/import-gguf` 经 `UploadFile` 收 GGUF）。
- **C5 / P2 保持现状**：无 `system` 砖，`/api/health`、`/api/models` 仍为非砖路由，不可经 `/api/bricks` 发现；影响低，未改。

### 验证
- `python -m py_compile` 对 5 个改动文件（base.py / llm/brick.py / api/system.py / main.py / ollama/__init__.py）全部通过。
- grep 确认：`llm/brick.py` 无 `_process_attachments`、无 `from ...core.config import settings`、无 `from pathlib import Path` 残留；`api/system.py` 不再存在对 `bricks.llm.capabilities` 的直接 import。
- 本机 WDAC 拦截编译型扩展运行，故未跑运行时 TestClient（沿用此前约定以 `py_compile` 为准）。
- 未 git commit。

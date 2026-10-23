# P.A.L.M 砖块独立拆分说明

> 按「主板 + 砖块」架构，将每个砖块物理拆分为**项目根下的中文名文件夹**，
> 每块均含独立 [uv](https://github.com/astral-sh/uv) 虚拟环境，可完全独立测试。

## 拆分范围

- **30 个独立文件夹**：29 块业务砖 + 主板（共享内核 `_shared`）
- 来源：
  - 业务砖：`backend/app/bricks/<name>/`
  - 主板：`backend/app/bricks/_shared/`
  - 插件砖（显示层）：`plugins/display/`
- 每块文件夹结构：
  ```
  <中文名>/
  ├── src/            # 砖块代码副本（与原始包结构一致）
  ├── README.md       # 砖块说明 + 独立测试指引
  ├── requirements.txt# 取自项目根 requirements.txt（全量后端依赖，可按需裁减）
  └── .venv/          # uv 创建的独立虚拟环境
  ```

## 砖块清单（中文名 → 英文砖名 → 总线类型）

| 中文名 | 英文砖名 | 总线类型 |
|---|---|---|
| 沙箱执行 | sandbox | pcie |
| 文件处理 | file | board |
| 对话 | chat | board |
| 模型供应商 | models | pcie |
| 会话记录 | conversations | sata |
| Ollama 向导代理 | ollama | pcie |
| 解析与结构化 | parse | pcie |
| 本机加解密 | crypto | ram |
| 存储芯片+管理芯片 | storage | chip |
| 离线模式 | offline | board |
| 应用设置 | settings | board |
| Token 用量 | usage | ram |
| 裁决引擎 | adjudicator | board |
| 角色扮演引擎 | roleplay | board |
| 对话缝合引擎 | stitching | ram |
| 好感度引擎 | affinity | ram |
| 记忆引擎 | memory | sata |
| Agent 框架 | agent | cpu |
| GUI 自动化 | automation | pcie |
| 自主进化引擎 | evolution | board |
| 显示层 | display | pcie |
| 语音合成 (CosyVoice) | cosyvoice | pcie |
| 语音合成 (GPT-SoVITS) | tts_sovits | pcie |
| 受控自我进化 | self_evolution | board |
| 定时任务引擎 | scheduler | board |
| 游戏生态 | game | ram |
| 兜底防御 | safety | board |
| 运行监控 | monitor | ram |
| 语音识别 | stt | cpu |
| 主板 | _shared | board（共享内核） |

## 独立测试方式

进入任意砖块文件夹，例如：

```bash
cd 记忆引擎
uv pip install -r requirements.txt      # 安装依赖（首次）
uv run python -c "import src; print('记忆引擎 import OK')"
```

> 注意：自 2026-08-15 全量解耦后，砖块不再依赖单体 archive，统一经项目根下的独立运行
> 基座 **`palm_sdk`** 满足共享依赖。砖内 `from palm_sdk.X import Y` 替代原 `app.*` 绝对导入
> 与跨砖相对导入；`palm_sdk` 已置于项目根目录，`import src` 时随根目录进入 `sys.path`，
> 无需把 `archive/monolith_20260815/` 纳入 PYTHONPATH。**已实测 30/30 砖可独立 import 通过。**

## 运行基座 palm_sdk（解耦关键）

`palm_sdk/` 是位于项目根目录的**独立运行基座包**，是「全量解耦」让每块砖可独立 import 的核心：

- **来源**：由原单体 `backend/app/` 的共享层（core / permission / security / bricks/_shared
  的 tooling / eventbus / paths 等）抽取为可独立安装的运行基座，去除对 `app.*` 命名空间的依赖。
- **三类导出面的语义**：
  - **核心原语 = 真实实现**：`palm_sdk.core`、`palm_sdk.base`、`palm_sdk.security`、
    `palm_sdk.permission`、`palm_sdk.schemas` 提供配置/日志/安全/权限/数据模型的真实代码。
  - **跨砖服务 = 安全桩**：`palm_sdk.bricks.agent.llm_bridge` 等跨砖能力在独立态下抛出
    明确 `RuntimeError("独立态未接入 … 后端")`，fail-closed 而非静默错误。
  - **共享工具 = 真实实现**：`palm_sdk.bricks._shared` 提供 `tooling`/`eventbus`/`paths`/
    `redundancy` 等真实代码（含 `Tool`/`ToolRegistry`/`emit`），砖块运行时直接复用。
- **导入改写规则**（见 `Data/diag/decouple_imports.py`）：
  - 原 `from app/backend/_shared.x` → `from palm_sdk.bricks._shared.x`
  - 原 2+ 点相对导入 `from ..core.x` → 外部依赖，映射到 `palm_sdk`
  - 1 点相对导入 `from .x` → 砖内文件，留原样（文件系统解析）
- **验证**：`Data/diag/decouple_imports.py` 静态校验 0 未解析；`Data/diag/brick_import_smoke.py`
  逐砖独立子进程 `import src` → **30/30 ok**。

## 砖→主板 API 契约（链接方式）

架构定位：**主板是唯一整合点（hub）**，其余 29 块业务砖各自独立可用，仅通过「API」与主板链接；
砖与砖之间严格零互导。本阶段只定义接口，主板侧的链接装配（挂载/调度）暂不做。

- **每砖对外暴露两类 API 表面**：
  - **HTTP 层**：`router = APIRouter(prefix="/api/<砖名>")`（约 24 块已声明）。主板经
    `app.include_router(brick.router)` 统一挂载，对外暴露为 P.A.L.M 的 HTTP 服务。
  - **进程内层**：`capabilities` 字典（或专用 API 对象，如 `roleplay_api`/`stitch_api`），
    经 `registry.get(name).capabilities` 取用，用于主板/其他砖在进程内调用本砖能力，
    不触发 HTTP、不产生跨砖 import。
- **链接由主板独占**：只有主板调用 `include_router` 与 `registry.get(...).capabilities`；
  业务砖不得 import 其他砖的内部模块，跨砖需求一律走 capability / HTTP（仍经主板转发）。
- **独立运行默认路径**：未接入主板（无全局 `settings`）时，砖回退到「砖根/data」本地目录
  （见 `palm_sdk.bricks._shared.paths.fallback_dir`/`resolve_storage`），保证 `import src`
  与基础能力在脱离主板时也可用。
- **接口就绪判定**：凡是声明了 `router` 或 `capabilities` 的砖，即视为「对主板接口已就绪」，
  主板日后只需按名挂载即可，无需改砖代码。

## 重要说明

- **本拆分为副本**：原始 `backend/app/bricks/` 与 `plugins/` 已于 2026-08-15 归档至 `archive/monolith_20260815/`（仅留中文砖块文件夹为代码组织；cosyvoice 砖补建为「语音合成 (CosyVoice)」文件夹，共 30 块）。如需启动原单体，从 archive 恢复即可。
- **同步方向**：在中文文件夹内的修改是独立测试沙盒，需手动同步回原始位置；反向不自动同步。
- 生成工具：`split_brick.py`（单块）+ `batch_split.py`（批量），已删除，避免污染根目录。

# P.A.L.M — AI 桌面助手 完整项目架构复刻文案

> **版本：v3.0（当前代码基线）**
> **目标：本文档按"照着做就能 1:1 复刻出可运行项目"的标准撰写，涵盖目录结构、每个模块的职责、全部 HTTP 端点、权限键、工具清单、数据文件结构、启动方式与复刻步骤。**
> **与代码冲突时以代码为准；接口明细见《接口文档.md》（从代码自动提取）。**

## 版本记录

| 版本 | 说明 |
|---|---|
| v3.0 | 当前基线：24 砖注册体系、sandbox 砖化、记忆/角色扮演/好感度独立成砖、双 Agent、自进化/定时任务/监控/STT 新砖 |
| v2.0 | 上一版基线（已归档） |

---

## 一、项目定位与核心设计

P.A.L.M（Personal AI Life Manager）是一个**三层解耦的本地优先 AI 桌面助手**：

- **后端**：FastAPI 纯 HTTP 服务（`backend/`），对前端只暴露语义化 REST + SSE 端点，不含任何桌面代码。
- **前端**：React 18 + TypeScript SPA（`frontend/`），只通过 `fetch` 调用后端，不感知桌面壳存在。
- **桌面壳**：PyWebView（`main.py`），负责拉起后端进程、创建原生窗口、提供 JS→Python 桥（`window.pywebview.api`）。

三个核心架构决策：

1. **砖块（Brick）可插拔架构**：每个后端能力（对话/文件/加解密/存储…）是一个砖块，**砖块之间严格互不 import**，跨砖能力一律经注册表 `capabilities` 字典暴露（缺失时调用方降级为 None）。前端通过 `/api/bricks` 发现砖块与能力，不硬编码砖块名。注册顺序即依赖顺序（`bricks/__init__.py`）。
2. **文件系统即数据库**：无任何数据库依赖，数据全部落在项目根 `Data/` 目录（JSON 文件 + 分类存储池 `pool.json` 索引），单文件原子写（临时文件 + `os.replace`）。
3. **安全默认拒绝**：权限引擎默认拒绝一切敏感操作；文件删除走系统回收站 + 保险库双兜底；AI 代码执行走进程隔离沙箱；启动随机 Token 保护文件端点。

### 技术栈总览

| 层 | 技术 | 关键点 |
|---|---|---|
| 桌面壳 | PyWebView 6.x | WebView2 后端、`js_api` 桥、port=0 动态端口 |
| 后端 | FastAPI + Uvicorn | 应用工厂模式、SSE 流式、统一异常处理 |
| 模型层 | httpx 流式 | Mock / OpenAI 兼容 / Anthropic 三协议 Provider |
| 前端 | React 18 + TS + Vite 5 | Tailwind 3、Radix UI、marked/KaTeX/highlight.js |
| 数据 | JSON 文件 + 分类存储池 | 无数据库；`Data/pool.json` 索引 |
| 加密 | 国密 SM3/SM4（gmssl） | 硬件指纹绑定密钥 + 恢复密钥 |
| 沙箱 | 多进程 + 隔离账户 + 网络代理 | Windows 下临时账户 + 防火墙按 PID 放行 |
| 本地模型 | Ollama + ModelScope | 引导下载 GGUF、目录直连 |
| 语音 | sherpa-onnx（STT）+ GPT-SoVITS（TTS） | STT 独立子进程；TTS 自包含 7z 解包 |

---

## 二、完整目录结构

```
P.A.L.M/
├── main.py                    # ★桌面壳入口：PyWebView 窗口 + 后端子线程
├── dev.py                     # ★开发模式启动器：后端 --reload + Vite dev + 浏览器
├── run.bat                    # 一键启动：建 venv → 装依赖 → 构建前端 → 启动桌面壳
├── dev.bat                    # 开发模式启动：venv + npm install + dev.py
├── requirements.txt           # 根级依赖清单（桌面壳 + 后端公共依赖）
├── Modelfile.gpu              # Ollama 本地模型文件（DeepSeek-R1-Distill-Qwen-7B 示例）
├── README.md                  # 占位（无实质内容）
├── docs/                      # ★文档库（本文件、接口文档、架构日志、各报告，纯 md）
├── logs/                      # 运行时日志
├── archive/                   # 历史产物/脚本归档（gitignore，本地留存）
│
├── backend/                   # ★FastAPI 后端（独立可导入的包）
│   ├── run.py                 # 后端独立启动入口（固定端口，开发用）
│   ├── run_api.py             # Headless 启动：port=0 动态端口，仅 API
│   ├── bench_eval.py          # P1-P6 真实模型端到端评测脚本（tokenhub）
│   ├── requirements.txt       # 后端专属依赖（含 pyyaml/pyautogui/pydantic-ai 等）
│   │
│   ├── app/                   # ★应用包
│   │   ├── __init__.py
│   │   ├── main.py            # ★应用工厂 create_app()：中间件/异常/砖块路由/SPA 托管
│   │   ├── security.py        # 启动随机 API Token 鉴权（Bearer 恒定时间比较）
│   │   ├── permission.py      # ★权限引擎：PermissionSpec/State/Risk + 持久化
│   │   ├── schemas/
│   │   │   └── chat.py        # ChatMessage/ChatRequest/ModelInfo/ConversationLogList
│   │   ├── core/
│   │   │   ├── config.py      # ★Settings：全部环境变量配置（单例 settings）
│   │   │   ├── gateway.py     # 离线模式四层网络拦截（httpx/requests/urllib/socket）
│   │   │   ├── logging.py     # 统一 JSON 单行日志 + request_id 链路
│   │   │   └── net.py         # read_bound_port()：读 uvicorn 实际绑定端口
│   │   ├── api/
│   │   │   ├── bricks.py      # GET /api/bricks 砖块发现
│   │   │   ├── permissions.py # /api/permissions 授权清单与 grant/revoke/bulk
│   │   │   └── system.py      # /api/health、/api/models、/api/files/window-size
│   │   ├── tools/             # ★GUI 自动化工具组（agent 工具，非砖块）
│   │   │   └── gui/           # 窗口管理/OCR/坐标点击（19 个工具，见工具表）
│   │   └── bricks/            # ★砖块体系（导入即注册，24 砖）
│   │       ├── __init__.py    # 按固定顺序 import 全部砖块子包
│   │       ├── base.py        # BrickManifest/MountSpec/Brick/BrickRegistry
│   │       ├── _token_estimate.py
│   │       ├── _shared/       # BIOS 自检共享（/api/bios/status）
│   │       ├── sandbox/       # ★沙箱砖：隔离执行/回收站/保险库/还原点/蜜罐
│   │       ├── file/          # 文件上传与鉴权读取
│   │       ├── chat/          # 核心砖：SSE 对话
│   │       ├── models/        # 模型供应商（Mock/OpenAI/Anthropic）
│   │       ├── conversations/ # 会话记录落盘与恢复
│   │       ├── ollama/        # Ollama 引导/目录/下载/部署
│   │       ├── parse/         # 文档/图片解析（OCR、docx/pptx/xlsx/pdf）
│   │       ├── crypto/        # SM4 国密加解密 + 硬件指纹 + 恢复密钥
│   │       ├── storage/       # ★存储池（分类/容量/清除/加解密，chip 总线）
│   │       ├── offline/       # 核心砖：离线模式开关
│   │       ├── settings/      # 核心砖：应用设置持久化（settings.json）
│   │       ├── usage/         # Token 用量台账与配额
│   │       ├── adjudicator/   # 裁决引擎（规则驱动 + AI 兜底）
│   │       ├── roleplay/      # ★角色扮演引擎（人设/渲染/污染守卫）
│   │       ├── affinity/      # ★好感度引擎（base/dynamics/bond 三线）
│   │       ├── memory/        # ★记忆引擎（长期归档/核心/向量/预算/压缩）
│   │       ├── agent/         # ★核心砖：Agent 框架（编排/工具/规划/双 Agent）
│   │       ├── evolution/     # ★自主进化引擎（后台任务/习惯/简报）
│   │       ├── self_evolution/ # ★受控自注册工具/技能/交换（人工审批）
│   │       ├── scheduler/     # ★定时任务引擎（持久化任务 + SSE 推送）
│   │       ├── game/          # 游戏生态（经验/星砂/商城）
│   │       ├── safety/        # 兜底防御（保险库 API + 还原点状态）
│   │       ├── monitor/       # 运行监控（游戏检测/模式解析）
│   │       ├── stt/           # ★语音识别（sherpa-onnx，独立子进程）
│   │       └── tts_sovits/    # GPT-SoVITS 语音合成（自包含完整 GSV）
│   │
│   └── sandbox_runtime/
│       └── decoys/            # 沙箱诱饵文件（检测逃逸）
│
├── frontend/                  # ★React SPA
│   ├── index.html             # SPA 入口（后端注入 __API_BASE__/__API_TOKEN__）
│   ├── package.json           # 依赖清单（见第七节）
│   ├── vite.config.ts         # @别名 / 代理 / 分块构建
│   ├── tailwind.config.js / postcss.config.js / tsconfig*.json
│   └── src/
│       ├── main.tsx           # ReactDOM 挂载（ErrorBoundary 包裹）
│       ├── App.tsx            # ★根组件：分区切换 + 全部面板挂载
│       ├── types.ts           # 全局 TS 类型（Message/Settings/CharacterCard…）
│       ├── index.css          # Tailwind + 主题变量
│       ├── api/               # API 客户端（按域拆分，19 个，client.ts 汇总导出）
│       │   ├── client.ts / client-infra.ts（★鉴权注入点）
│       │   ├── client-health / client-chat / client-agent / client-crypto
│       │   ├── client-storage / client-file / client-conversations / client-usage
│       │   ├── client-permissions / client-game / client-safety / client-system
│       │   ├── client-display / client-monitor / client-scheduler / client-self-evolution
│       │   └── ollama-client.ts
│       ├── hooks/             # use-settings / use-appearance / use-chat /
│       │                      # chat-agent-events / chat-helpers / use-permissions / use-theme
│       ├── components/        # 58 个组件（见第七节清单）
│       │   └── ui/            # shadcn 风格基础组件（button/dialog/switch…）
│       ├── lib/
│       │   ├── md.ts / md-ui-kit/     # Markdown 渲染管线（marked+katex+hljs+sanitize）
│       │   ├── storage.ts             # localStorage 安全读写
│       │   ├── storageCache.ts / affinity-bus.ts / open-external.ts / url.ts / utils.ts
│       └── vite-env.d.ts
│
└── Data/                      # ★数据存储池（STORAGE_POOL_DIR）
    ├── settings.json          # 应用设置（权威源，可加密）
    ├── pool.json              # ★存储池索引（分类 + 文件记录）
    ├── permissions.json       # 权限授权状态
    ├── game_state.json        # 游戏状态（经验/星砂/每日任务/解锁道具）
    ├── .window_size           # 未加密窗口尺寸（桌面壳读取）
    ├── characters/            # 角色卡 JSON（如 mengyao.json）
    ├── agent_memory/          # Agent 记忆文件（按会话 <id>.json）
    ├── agent_affinity/        # 好感度历史快照
    ├── vector_memory/         # 向量记忆持久化（按角色子目录）
    ├── agent_artifacts/       # Agent 工具产物
    ├── agent_habits/          # 进化引擎习惯数据
    ├── observations/          # 进化引擎观察记录
    ├── schedules.json         # 定时任务持久化
    ├── skills/                # Skill 定义库
    ├── gui_atlas/             # GUI 世界模型静态认知地图
    ├── tts_cache/             # TTS 合成音频
    ├── 对话记录/ 配置文件/      # storage 池分类目录
    └── _cleanup_bak_*/_crypto_bak/  # 历史清理/加密备份（可删除）
```

---

## 三、启动方式与运行形态

### 3.1 环境准备

- Python 3.10+（实测 3.10/3.13 均可）
- Node.js 18+（构建前端需要）
- Windows 上桌面壳需要 **Microsoft Edge WebView2 Runtime**（缺失时 main.py 自动回退浏览器打开）

### 3.2 一键启动（生产形态，Windows）

`run.bat` 流程：
1. 若无 `.venv` → `python -m venv .venv` + `.venv\Scripts\pip install -r requirements.txt`
2. 删除 `frontend/dist` 与 `node_modules/.vite` → `cd frontend && npm run build`
3. `.venv\Scripts\python.exe main.py`

### 3.3 开发模式（热重载）

`dev.bat` → `dev.py` 流程：
1. 确保 venv 与 `frontend/node_modules` 存在
2. `kill_stale_by_ports()` 精确清理占用 8005/5173 端口的旧进程
3. 启动后端：`.venv\python -m uvicorn backend.app.main:app --reload --port 8005`（日志 `backend_dev.log`）
4. 启动前端：`npm run dev -- --port 5173`，注入 `VITE_BACKEND_PORT=8005`（日志 `frontend_dev.log`）
5. HTTP 探活 `/api/health` + TCP 探活 5173，就绪后自动开浏览器
6. Ctrl+C 时 `taskkill /T` 杀进程树

**关键约定**：`vite.config.ts` 把 `/api` 与 `/uploads` 代理到 `http://127.0.0.1:${VITE_BACKEND_PORT || "8005"}`，与后端默认端口保持同步（开发模式通过 Vite 代理解决跨域；生产形态同源无跨域）。

### 3.4 纯后端服务（Headless）

```bash
cd backend
python run_api.py              # port=0 动态分配空闲端口并打印地址
PORT=9000 python run_api.py    # 优先 9000，被占则退回空闲端口
```

### 3.5 三种形态的 URL 解析（main.py `_resolve_url`）

- 设置 `PALM_TEST_PAGE=1` → 直接打开 `http://localhost:5173/test.html`（需先起 Vite）
- 存在 `frontend/dist/index.html` → 打开 `http://{HOST}:{PORT}/`（后端托管 SPA，同源）
- 否则 → 打开 Vite 开发服务器 `http://localhost:5173`

---

## 四、后端核心机制

### 4.1 应用工厂（backend/app/main.py `create_app`）

启动时序：
1. `init_api_token()`：生成 32 字节随机 Token，写入 `%TEMP%/palm_api_token`；`PALM_API_TOKEN` 环境变量可覆盖（开发固定值）
2. `configure_logging()`：JSON 单行日志 + request_id 过滤器
3. 注册 CORS（`allow_origins` + `allow_origin_regex` 覆盖 loopback 任意端口，`credentials=True`）
4. 注册 4 个全局异常处理器：
   - `HTTPException` → 原样 JSON
   - `RequestValidationError` → 422 结构化（`default=lambda o: repr(o)` 防 bytes 二次 500）
   - `PermissionDenied` → 403 结构化体 `{error, key, title, description}`
   - `Exception` → 500 通用体 + 服务端堆栈
5. 注册请求日志中间件（method/path/status/dur_ms + request_id）
6. `_mount_brick_routers()`：遍历 `registry.all()`，`is_enabled` 且 router 非空则挂载；再挂 `/api/bricks`、`/api/permissions`、`/api/system`
7. `_mount_brick_static()`：砖块自带静态挂载（在 SPA 兜底**之前**）
8. `_should_serve_frontend()`（`SERVE_FRONTEND` auto/true/false）为真时 `_mount_spa()`：
   - 读取 `dist/index.html`，向 `</head>` 注入 `window.__API_BASE__=window.location.origin` 与 `window.__API_TOKEN__=...`
   - **移除 `crossorigin` 属性**（WebView2 拒绝执行带 crossorigin 的跨域模块脚本，否则白屏）
   - 根路径返回注入后的 HTML；其余路径 `StaticFiles(directory=dist, html=True)` 兜底

### 4.2 配置（backend/app/core/config.py `Settings`）

| 环境变量 | 默认值 | 说明 |
|---|---|---|
| `HOST` / `PORT` | `127.0.0.1` / `8000` | 服务监听（桌面壳 main.py 用 port=0 动态分配） |
| `CORS_ALLOW_ORIGINS` | localhost:5173/8000 等 | CORS 白名单 |
| `CORS_ALLOW_ORIGIN_REGEX` | `^https?://(localhost\|127\.0\.0\.1\|\[::1\])(:\d+)?$` | 反射 loopback 任意端口 |
| `FRONTEND_DIST` | 项目根 `frontend/dist` | SPA 构建产物目录 |
| `SERVE_FRONTEND` | `auto` | `auto`=仅当 dist 存在才托管 |
| `UPLOAD_DIR` | `backend/uploads` | 上传文件落盘目录 |
| `STORAGE_POOL_DIR` | 项目根 `Data` | ★所有数据的根目录 |
| `SOVITS_*` | 见下 | GPT-SoVITS 配置（URL/ROOT/模型/设备/自动拉起） |
| `STT_*` | 见下 | sherpa-onnx STT 配置（独立子进程） |

**SOVITS 关键默认值**：`SOVITS_API_URL=http://127.0.0.1:9880`、`SOVITS_ROOT=backend/app/bricks/tts_sovits/gpt_sovits`、`SOVITS_INFER_DEVICE=cuda`、默认 v2final 预训练模型路径、`SOVITS_AUTO_LAUNCH=true`、`SOVITS_OUTPUT_DIR=Data/tts_cache`。

**STT 关键点**：sherpa-onnx 引擎跑在独立子进程（`.venv-stt` 虚拟环境），VAD + KWS + 流式 ASR；识别事件经事件总线广播供对话链路消费。

### 4.3 鉴权（backend/app/security.py）

- `require_api_token`：校验 `Authorization: Bearer <token>` 或 `?token=` 查询参数（兼容 `<img>`/`<a download>`），`secrets.compare_digest` 恒定时间比较
- Token 未初始化（`_TOKEN is None`）时不拦截 → 保证开发/测试可运行
- 仅 `/api/health`、`/api/ollama/health`、`/api/bios/status`、各 `status` 探测端点等无鉴权，其余端点几乎全部挂 `Depends(require_api_token)`

### 4.4 权限引擎（backend/app/permission.py）

- `RiskLevel`：high / medium / low
- `PermissionState`：granted / denied / unset（**默认拒绝**：只有显式 granted 放行）
- `GrantRecord`：state + scope（`always`/`session`）+ 时间戳
- `PermissionEngine`：
  - `declare/declare_many`：砖块构造 Brick 时经 `permissions=[PermissionSpec(...)]` 自动登记
  - `grant/revoke/apply_bulk`：实时生效，持久化到 `Data/permissions.json`（原子写）
  - `require_permission(key)`：FastAPI 依赖，未授权抛 `PermissionDenied`
- 未挂权限键的工具 / 未加依赖的端点**默认放行**（fail-open，避免误锁无害功能）

### 4.5 已声明的权限键全表

| 权限键 | 风险 | 归属砖 | 说明 |
|---|---|---|---|
| `file.read` | medium | file | 读取本地文件 |
| `file.write` | medium | file | 写入/追加/复制/移动/建目录 |
| `file.delete` | high | file | 删除本地文件 |
| `file.fs_query` | low | file | 列目录/元信息/搜索/哈希 |
| `conversations.delete` | medium | conversations | 删除会话记录 |
| `storage.delete` | medium | storage | 删除存储池分类/文件 |
| `storage.prune` | medium | storage | 触发分类清理 |
| `storage.quota` | medium | storage | 调整存储配额/层级 |
| `ollama.pull_model` | medium | ollama | 拉取/下载/导入模型 |
| `ollama.deploy_model` | medium | ollama | 部署/上传模型 |
| `sandbox.run_code` | high | agent | 沙箱执行代码 |
| `desktop.control` | high | agent | 桌面自动化控制 |
| `network.http_outbound` | high | agent | 对外网络访问（web_search/web_fetch） |
| `system.restore` | high | agent | 创建/清理系统还原点 |
| `stt.listen` | medium | stt | 语音识别监听 |

（前端「权限中心」经 `/api/permissions` 渲染清单，用户可逐项授权/撤销；`FirstLaunchChecklist` 首启批量授权。）

---

## 五、砖块体系详解

### 5.1 砖块契约（backend/app/bricks/base.py）

```python
BrickManifest: name/title/description/is_core/bus_type/is_streaming/is_enabled
MountSpec:     path/directory/name   # 砖块自带静态挂载
Brick:         manifest + router(APIRouter|None) + mounts + capabilities(dict) + permissions(list)
BrickRegistry: register/all/get/manifests
```

- 核心砖（chat/agent/settings/offline，`is_core=True`）不可插拔
- `Brick.__post_init__` 把 `permissions` 自动登记进权限引擎（延迟导入避免循环依赖）
- `bricks/__init__.py` 按固定顺序 import（底层域先注册：sandbox → 基础能力 → roleplay/affinity/memory → agent → evolution/self_evolution/scheduler）
- **新增砖块三步**：`bricks/<name>/` 建子包 → 子包 `brick.py` 创建 `Brick` 并 `registry.register(brick)` → `bricks/__init__.py` 加一行 import

### 5.2 全部 HTTP 端点

共 **141 个路由**（按砖分组，含权限标注）。完整明细见 `docs/接口文档.md`（从代码自动提取，保持同步）。要点：

| 砖块 | 前缀 | 说明 |
|---|---|---|
| system | `/api` | health/models/window-size + bricks/permissions |
| _shared | `/api/bios` | BIOS 自检状态 |
| chat | `/api` | SSE 对话 + file-support |
| agent | `/api/agent` | run/ask-response/events/characters/affinity/dual-* |
| storage | `/api/storage` | 分类/文件/配额/层级/加密/统计（19 端点） |
| self_evolution | `/api/self-evolution` | 观察/提案/skills/slots/swaps/tools（26 端点） |
| adjudicator | `/api/adjudicator` | rules/events/operators/actions/evaluate/ai-fallback |
| ollama | `/api/ollama` | 目录/拉取/下载/部署 |
| crypto | `/api/crypto` | 加解密/恢复密钥/加密开关 |
| game | `/api/game` | 状态/签到/奖励/商城 |
| scheduler | `/api/scheduler` | 定时任务 CRUD |
| stt | `/api/stt` | 监听起停/关键词 |
| safety | `/api/safety` | 保险库 |
| 其余 | 各自前缀 | file/conversations/parse/offline/settings/usage/monitor/models |

### 5.3 砖块逐一详解（24 砖）

#### ① sandbox（可选砖，pcie 总线）★
- **砖化后承载全部运行时安全边界**：`run_isolation.py`（多进程 + Windows 临时隔离账户）、`net_interceptor.py`（透明 HTTP 代理拦截）、`net_policy.py`（FirewallManager 按 PID 防火墙）、`restore.py`（系统还原点）、`safe_delete.py`（删除守卫 → 回收站 + 保险库）、`vault.py`（文件级保险库）、`honeypot.py`（蜜罐诱捕）、`ast.py`（AST 预检）、`adjudicator.py`（沙箱内裁决）
- capabilities：`sandbox_engine` / `send_to_recycle_bin` / `run_code_isolated` / `restore_point` / `vault`

#### ② file（可选砖）
- 上传落 `UPLOAD_DIR`，返回 `UploadedFile`（file_id 为 12 位 hex）；读取经应用层鉴权（不暴露静态目录）
- 权限：file.read / file.write / file.delete / file.fs_query

#### ③ chat（核心砖，board 总线）
- 纯编排，不持有模型协议：`create_stream` 能力来自 models 砖、配额/记账来自 usage 砖
- SSE 事件格式：`data: {id, model, created, delta, reasoning, usage}` + 结尾 `data: [DONE]`
- 无 model 且无 provider → 400「请先在设置 › 模型 › 添加模型」；models 砖未启用 → 503
- 附件策略：模型支持文件（direct）→ 跳过解析直传；否则（process）→ 400 要求先经 parse 解析
- 配额超额 → 429；流末仅真实 usage（total>0）才记账

#### ④ models（可选砖）
- `provider.py`：`ChatDelta`（content/reasoning/usage）；`BaseProvider.stream` 抽象；`MockProvider`（本地回显调试）；`OpenAIProvider`（OpenAI 兼容，含工具调用）；`AnthropicProvider`（强制回落 ReAct，不支持原生工具）
- capabilities：`create_stream` / `is_model_file_capable` / `file_handling_mode` / `model_supports_files`
- 文件能力判定：`qwen2.5-vl-72b` / `gpt-4o*` / `gemini-*` / `claude-*` 等含视觉关键字的模型为 direct，其余 process

#### ⑤ conversations（可选砖）
- 底层委托 storage 砖 `store_file`（含加密 + pool.json 索引），复用 PoolStore 单例避免双实例竞争
- 固定文件名 `<convId>.json` upsert 到「对话记录」分类；`_strip_surrogates` 递归清除孤立代理对
- 权限：conversations.delete

#### ⑥ ollama（可选砖）
- `connection.py`：Ollama HTTP 客户端；`catalog.py` + `catalog_data.py`：多源模型目录（HF/ModelScope 双源）；`downloader.py`：ModelScope GGUF 后台下载；`convert.py`：GGUF/Modelfile 转换
- `import-gguf`：本地 GGUF 导入生成 Modelfile（如 `Modelfile.gpu` 含 `num_gpu 999`、`num_ctx 32768`）
- 权限：ollama.pull_model / ollama.deploy_model

#### ⑦ parse（可选砖）
- `controller.py`：`run_parse_job` 识别类型分发；OCR（rapidocr_onnxruntime）+ 图片预处理 + docx/pptx/xlsx/pdf 结构化
- 任务型接口：POST 提交 → GET `/{job_id}` 查询 → `/{job_id}/result` 取结果
- 依赖懒加载：缺失仅对应格式降级

#### ⑧ crypto（可选砖，ram 总线）
- 硬件指纹 = SHA256(系统制造商 + 系统产品名)；主密钥经指纹 `seal_keystore` 封存
- `encrypt_bytes/decrypt_bytes` 经 capabilities 暴露给 settings/storage 砖
- 恢复密钥：离线恢复路径（recovery-key 导出/导入）；`_bind_ok` 失败时 router=None（砖降级不挂载）

#### ⑨ storage（可选砖，chip 总线）★
- `pool.py`：`PoolStore` 管理 `Data/pool.json`；分类 `CategoryMeta`（capacity_bytes/cleanup 规则：oldest_first、keep_min_count、max_age_days、auto）
- `store_file`：可选加密（SM4）、去重、容量超额触发自适应清除
- `cleanup_category`：按规则清理；存量全量加解密（crypto 砖经 capabilities 调用）
- 内置分类：`配置文件`、`对话记录`；支持配额/层级调整
- 权限：storage.delete / storage.prune / storage.quota

#### ⑩ offline（核心砖，board 总线）
- 导入期 `patch_httpx()` 给四层出网链路打补丁（httpx/requests/urllib/socket），全部幂等
- 开启后仅放行回环地址（127.x/localhost/::1），保证 Ollama 本地可用

#### ⑪ settings（核心砖，board 总线）
- `load_app_settings/save_app_settings`：读写 `Data/settings.json`；加密开启时内容经 crypto 加密落盘
- 原子写：`.tmp` + `os.replace`
- 默认设置字段：apiUrl/windowSize/background/maskBlur/fontSize/agentWebSearch/agentDeepThink/agentCharacterId/agentToolMode/agentPlanningMode/agentAutoFilterTools/agentStorageAutoCleanup/theme/language

#### ⑫ usage（可选砖）
- `token_ledger.py`：台账落盘 `Data/token_usage.json`（或经 storage）
- `check_quota()`：读取配额，超额返回 `(True, msg)` → chat 砖抛 429
- `record_usage(chat_id, model, provider, prompt_tokens, completion_tokens, total_tokens)`
- capabilities：`check_quota` / `record_usage`

#### ⑬ adjudicator（可选砖，board 总线）
- `engine.py` + `rules.py` + `rules.yaml`：规则引擎（默认放行原则）；AI 兜底裁决（`ai_fallback`，默认关）
- 规则模型：id/description/enabled/priority/trigger/conditions/actions；条件 `{field, op, value}` AND 组合；动作 `deny/ask/allow/warn`
- capabilities：`check_action` / `get_rules` / `add_rule` / `remove_rule` / `validate_rule` / `ai_fallback_*`
- 拦截时事件带 `adjudicated=true` + `adjudicated_reason`

#### ⑭ roleplay（可选砖，board 总线）★
- `character.py`：角色卡模型；`pollution_guard.py`：`strip_roleplay_tone` 治本（persona_text 空即无角色；阻断角色扮演语气回灌历史）
- `import_skill.py`：角色技能导入
- capabilities：`roleplay_api` / `on_entity_deleted`
- 好感度已拆出为独立 affinity 砖（经 capability 门面取用）

#### ⑮ affinity（可选砖，ram 总线）★
- 双线好感度：`base` 地基 -50~100 慢 + `dynamics` 温度计 -50~50 幂律回归 0 快 + `bond` 无上限装饰
- 档位来自 `affection_rules/official_6stage.yaml` 或角色卡 `affinity_stages`（引擎零硬编码）
- capabilities：`affinity_api` / `on_entity_deleted`
- 数值全隐藏：显示权威在 `/api/agent/affinity` 的 `display_allowed`，由 game 砖 `has_item("affinity_display")` 解锁

#### ⑯ memory（可选砖，sata 总线）★
- 独立记忆引擎：长期归档（幂律衰减 + Token 预算裁剪）/ 核心记忆 / 向量语义检索（1024 维，同维校验 + 维度不匹配自愈）/ 短长期上下文压缩
- **短期记忆**：近 50 轮；近 3 轮压缩完整注入，3-50 轮仅注入关键词重叠 ≥15% 的语义相关内容
- **注入防线**：非 user 消息写长期记忆前 `strip_roleplay_tone`；工具结果入记忆前 `_strip_prompt_injection`
- capabilities：`memory_api`

#### ⑰ agent（核心砖，cpu 总线）★
见第六节专章。

#### ⑱ evolution（可选砖，board 总线）★
- 自主进化引擎：后台任务调度 / 闲置习惯推测 / 每日偏好简报 / 习惯学习 / 本地兜底（eco 模式）
- 依赖 agent 的 `run_proactive_stream` / `push_bubble` 能力
- capabilities：`evolution_api`

#### ⑲ self_evolution（可选砖，board 总线）★
- 受控自注册：观察 → 提炼 → 注册新工具/技能的闭环，含影子模式 + 灰度切换 + 自动回退熔断
- **铁律：AI 不能自开插槽，所有产出必须人工审批才能激活**（skills/slots/swaps/tools 全走 approve 流程）
- capabilities：`self_evo_tools` / `self_evo_skills` / `self_evo_observe`

#### ⑳ scheduler（可选砖，board 总线）★
- 定时任务引擎：持久化任务、周期触发、经 agent 生成并 SSE 推送
- capabilities：`create_job` / `list_jobs` / `delete_job` / `on_entity_deleted`

#### ㉑ game（可选砖，ram 总线）
- `xp.py`：经验系统（10 阶 × 100 级/阶，`exp_per_level = 1000*(stage+1)`）、`derive_level`、`affinity_coefficient`、`streak_coefficient`、`chat_xp`、`login_currency`（每日登录星砂）
- `state.py`：`game_state.json`；`brick.py`：签到/award/SHOP_CATALOG/purchase/unlock-item
- capabilities：`award_chat_xp` / `award_plan_xp` / `has_item` / `unlock_item` / `purchase_item`

#### ㉒ safety（可选砖，board 总线）
- 暴露保险库 API：list/restore/clear + status
- 与 sandbox 砖的 vault/restore 联动（系统还原点状态汇总）

#### ㉓ monitor（可选砖，ram 总线）
- 运行监控：游戏检测（`is_game_running`）/ 模式解析（`resolve_effective_mode`）/ 运行模式配置（`get_run_mode_config`）

#### ㉔ stt（可选砖，cpu 总线）★
- 基于 sherpa-onnx 的本地语音识别：VAD + KWS + 流式 ASR，跑在独立子进程（`.venv-stt`）
- 识别文本经事件总线广播，供对话链路消费
- capabilities：`is_stt_available` / `start_listening` / `stop_listening` / `list_keywords`；权限：stt.listen

#### ㉕ tts_sovits（可选砖，自包含完整 GPT-SoVITS）
- **砖块即完整 GSV**：`install.py` 从 7z 解包到 `gpt_sovits/`（自带 runtime/python 与模型）
- `client.py`（HTTP 薄代理）/ `launcher.py`（自带 runtime 发现与启动）/ `tool.py`（经 agent `register_tool` 注册语音工具）
- 启动按 `SOVITS_AUTO_LAUNCH` 拉起自带 runtime；缺 runtime/无 GPU/未解包 → 优雅降级

---

## 六、Agent 框架（backend/app/bricks/agent/）★

### 6.1 模块地图

| 文件 | 职责 |
|---|---|
| `core.py` | `Agent(PromptMixin, ExecutionMixin, ReactMixin)` 实例装配与顶层 run 分发（支持依赖注入） |
| `protocols.py` | ★核心层 Protocol 接口（工具/记忆/规划/LLM 等 8 个，各层级独立可插拔） |
| `schemas.py` | `AgentRunRequest`、`AgentEvent` |
| `agent_prompt_mixin.py` / `agent_execution_mixin.py` / `agent_react_mixin.py` | 提示构建/执行编排/ReAct 兜底 |
| `native_runner.py` / `_native_execution.py` | 原生 function-calling 主循环 + 工具执行编排抽取 |
| `code_guard.py` | 代码工具预检（危险 API 阻断/确认） |
| `llm_bridge.py` | models 砖 create_stream 归一为（content/reasoning/tool_calls/usage）流 |
| `tool_base.py` / `tool_matcher.py` | Tool 基类/注册表/语义工具匹配索引 |
| `tools/` | 内置工具集（file/web/sandbox/window/life/life_domestic/scheduler/ask） |
| `dual/` | ★双 Agent 架构：Boss（对话）+ Worker（后台执行），coordinator/dual_core/intent_router/trace_store/professional_memory |
| `plan_engine.py` / `planner.py` | 自主规划引擎（先计划→分步执行→失败重规划） |
| `react_parser.py` / `question_hub.py` / `trace.py` / `prompt_templates.py` | ReAct 解析/ask_user 队列/运行轨迹/提示模板 |
| `brick.py` | HTTP 层：run SSE/工具清单/角色卡/好感度/双 Agent + 工具注册装配 |

### 6.2 运行流程（/api/agent/run）

1. `brick._prepare_agent_run`：解析设置（web 搜索/深度思考/工具过滤）、人设与角色卡、构造 Memory（按 `conversation_id + character_id` 路径持久化）、`_derive_tool_mode`（Anthropic 强制 react）、创建 Agent、包装 `_llm_with_provider`、取 adjudicator `check_action`
2. `_stream_agent_sse`：预挂 `agent._ask_events` 队列 → `memory.initialize()` → `_merge_ask_events(agent.run(...))` 并发消费即时事件
3. `Agent.run`：`_prepare_run` → `compress_old_turns`（超预算历史摘要化）→ 包裹 `RunTracer` → 分派：
   - `use_planning=true` → `PlanEngine.run`
   - `tool_mode=native` → `run_native`（function calling 循环）
   - 否则 → `run_react`（ReAct 循环）
4. done 事件统一处理：真实 usage 记账 → 好感度结算（经 affinity 砖，非唤醒轮）→ 情感事件记录 → `_award_game_xp_on_done` → `memory.shutdown()`
5. 异常 → error 事件；finally `question_hub.cancel_for_conversation`

### 6.3 双 Agent（dual/）

- **Boss**：前端对话 Agent，空工具注册表 + `max_iterations=2`，负责意图路由与答复
- **Worker**：后台执行 Agent，独立 ToolRegistry + buffer memory，执行复杂任务
- `intent_router.py`：纯关键词四意图路由（chat/task/intervention/query）
- 接口：`/api/agent/dual-run` / `dual-status` / `dual-intervene`
- `trace_store.py`：分片记录 Worker 轨迹；`professional_memory.py`：专业 Agent 私有经验层（SQLite，主 Agent 不可读）

### 6.4 内置工具全表（54 个）

**文件组**（file_tools.py）：`read_file` / `write_file` / `append_file` / `copy_file` / `move_file` / `delete_file`（★回收站+保险库双兜底）/ `list_directory` / `get_file_info` / `search_files` / `file_hash` / `create_directory`

**网络组**（web_tools.py）：`web_search` / `web_fetch`（`_is_safe_host` 拒内网/回环/保留地址，防 SSRF；权限 network.http_outbound）

**窗口组**（window_tools.py）：`type_text` / `press_key` / `hotkey` / `get_mouse_position` / `move_mouse` / `click_mouse` / `scroll_mouse` / `drag_mouse` / `take_screenshot` / `screenshot_region` / `clipboard_write` / `clipboard_read`（权限 desktop.control）

**GUI 组**（app/tools/gui/，19 个）：`list_windows` / `focus_window` / `close_window` / `maximize_window` / `minimize_window` / `restore_window` / `get_window_rect` / `get_active_window` / `wait_for_window` / `wait_seconds` / `wait_for_pixel` / `find_text` / `click_text` / `click_element` / `click_mouse` / `get_cognitive_map` / `list_software`（权限 desktop.control；经世界模型静态地图 + 实时 UIA 树解析坐标）

**沙箱组**（sandbox_tools.py）：`run_code`（sandbox.run_code，★隔离+代理+还原点+裁决预检）/ `start_background_task`（守卫 + 防套娃）/ `create_restore_point` / `cleanup_restore_points`（system.restore）

**调度组**（scheduler_tools.py）：`schedule_task`（定时任务）

**生活组**（life_tools.py / life_domestic_prod_tools.py）：`chengyu`（成语）/ `chinese_dict`（词典）/ `festival`（节日）/ `qrcode`（二维码）/ `remind`（提醒）/ `toggle_setting`（设置开关）等

**交互组**（ask_tool.py）：`ask_user`（人机交互卡片，阻塞等待应答）

**外部工具**：各砖块经 `capabilities["agent_tools"]` 注册（如 tts_sovits 语音合成工具），`_ensure_tools()` 运行时收集。

### 6.5 记忆层（独立 memory 砖）

- **短期记忆**：近 50 轮；近 3 轮压缩完整注入（`[用户]/[助手]` 格式 + 要点提取），3-50 轮仅注入关键词重叠 ≥15% 的语义相关内容
- **核心记忆**：personality/user_profile 等事实
- **归档记忆**：超出 50 轮历史，幂律衰减 + Token 预算裁剪（五因子情绪公式：`Score = W_imp × E_enc × T_em × R(Δn) × E_ret`）
- **向量记忆**：1024 维（Ollama bge-m3/mxbai-embed-large），降维触发 `_heal_dimension_mismatch` 自愈
- **注入防线**：`strip_roleplay_tone`（去角色扮演语气）+ `_strip_prompt_injection`（剥高信号注入短语）

### 6.6 安全链路（Agent 视角）

工具执行前：`adjudicator.check_action` 规则预检（deny/ask/allow/warn）→ `code_guard._run_code_guard` → 文件路径 `_resolve_allowed_path`（限用户主目录）→ 删除类走 `send_to_recycle_bin`（自动归档保险库）→ `start_background_task` 经 `guard_background_command` → 网络工具 `_is_safe_host` 防 SSRF。

---

## 七、前端架构（frontend/）

### 7.1 依赖清单（package.json）

- **dependencies**：react 18.3、react-dom、@radix-ui/react-*（avatar/dialog/scroll-area/separator/slot）、class-variance-authority、clsx、dompurify、gemoji、highlight.js、katex、lucide-react、marked、tailwind-merge、unicode-emoji-json
- **devDependencies**：typescript 5.6、vite 5.4、@vitejs/plugin-react、tailwindcss 3.4 + autoprefixer + postcss + tailwindcss-animate
- **scripts**：`dev` / `build`（tsc -b && vite build）/ `preview`
- **构建分块**：vendor-react / vendor-katex / vendor-markdown / vendor-icons

### 7.2 Vite 配置要点（vite.config.ts）

- 别名 `@` → `./src`；dev server：host=true、port 5173；**代理 `/api` 与 `/uploads` → `http://127.0.0.1:${VITE_BACKEND_PORT||"8005"}`**
- build：outDir=dist、emptyOutDir、manualChunks 四块

### 7.3 数据流与鉴权（client-infra.ts）

`API_URL` 解析顺序：`window.__API_BASE__`（桌面壳注入）→ `VITE_API_URL` → `window.location.origin`。
`API_TOKEN`：`window.__API_TOKEN__` → `VITE_API_TOKEN`。所有请求经 `authedFetch` 自动带 `Authorization: Bearer`；`throwHttp` 解析 JSON detail 抛出中文错误。

### 7.4 组件清单（src/components/，58 个）

`AgentPanel`、`AppearancePanel`、`AskUserCard`、`BackgroundLayer`（z-0 全屏背景）/`MaskLayer`（z-1 毛玻璃遮罩）/`.business-layer`（z-10 业务层）——**外观三层全屏叠加**、`Brand`、`CharacterEditor`、`ChatInput`、`ChatSidebar`、`ConversationHeader`、`DisplayPanel`（桌面组件显示层）、`EncryptionPanel`/`EncryptionDoneViews`、`ErrorBoundary`、`EvolutionModeChip`、`EvolutionPanel`（进化面板）、`ExperiencePanel`、`FileChip`、`FirstLaunchChecklist`、`MdBlock`、`MessageBubble`/`MessageList`/`ThinkingBlock`、`MiniGamePanel`、`ModelPanel`/`ModelSelect`、`OllamaGuide`/`OllamaGuideHeader`/`OllamaStepConfig`/`OllamaStepDeploy`/`OllamaStepDownload`/`OllamaStepInstall`、`PermissionCenter`/`PermissionDenialCard`、`RoleplayStatusBar`、`RulesPanel`/`AddRuleDialog`/`rules-shared`、`SchedulerPanel`（定时任务）、`SecurityPanel`、`SelfEvolutionPanel`/`SelfEvoObserveSection`/`SelfEvoSkillSection`/`SelfEvoSwapSection`/`SelfEvoToolSection`（自进化四分区）、`SettingsDialog`、`ShopPanel`、`SizeSelect`、`SkillImportDialog`/`SkillsPanel`、`StorageManagement`/`StoragePanel`（存储池管理，外壳+内面板）、`SystemPanel`、`TokenLimitPanel`、`TopBar`、`UsageTable`、`VaultPanel`、`Welcome`。

### 7.5 hooks 职责

- `useSettings`：localStorage 快速缓存 + 后端权威覆盖
- `useAppearance`：外观副作用（theme/背景/模糊/字号 + resize_window 桥）
- `useChat`：★对话状态机（SSE 消费、AbortController 中断、重试、会话落盘、后台事件）
- `chat-agent-events.applyAgentEvent`：Agent SSE 事件 → 消息流归约（thought/ask_user/tool_call/tool_result/plan/plan_step/delta/done/error）
- `chat-helpers`：`processFileAttachments`（direct/process 分支）、`shouldUsePlanning`、`buildMessagePair`
- `usePermissions`：权限清单 + grant/revoke/bulk
- `useTheme`：亮/暗主题

### 7.6 三层全屏叠加（外观实现，改动须维护三处）

```
BackgroundLayer (z-0)  ← 全屏背景图/纯色
MaskLayer (z-1)        ← backdrop-filter: blur(maskBlur) 毛玻璃，pointer-events:none
.business-layer (z-10) ← 业务 UI；「外观设置」开启时置 invisible
```

---

## 八、桌面壳（main.py，PyWebView）

### 8.1 启动时序

1. `_ensure_venv()`：当前解释器缺依赖时自动 re-exec 到 `.venv\Scripts\python.exe`
2. `dotenv.load_dotenv(.env)`（可选）
3. uvicorn `port=0` 起后端线程 → `read_bound_port(server)` 读出实际端口同步 `settings.PORT`
4. `_wait_for_server()` 轮询 `/api/health`
5. `_resolve_window_size()` 读 `Data/.window_size`（无则 1200×780）→ `_resolve_url()`（见 3.5）
6. `webview.create_window("P.A.L.M · AI Assistant", url, w, h, min_size=(900,600), js_api=api)`
7. `webview.start()`；窗口关闭 → `server.should_exit=True` 优雅退出
8. PyWebView 创建失败 → 弹框提示（WebView2 缺失指引）→ **自动回退系统浏览器打开界面**

### 8.2 JS→Python 桥（window.pywebview.api）

| 方法 | 前端用途 |
|---|---|
| `resize_window(w, h)` | 外观设置窗口尺寸；≤0 表示最大化；前端同时写 `.window_size` |
| `open_external(url)` | 外链在系统浏览器打开（仅 http(s)） |
| `pick_directory()` | 原生文件夹选择对话框（存储池目录选择） |
| `pick_files()` | 原生多文件选择（模型文件 *.safetensors/*.gguf） |
| `save_recovery_key(content, filename)` | 原生另存为对话框写恢复密钥 txt |

---

## 九、安全设计总览

### 9.1 纵深防御层次

1. **传输层**：离线模式四层拦截（httpx/requests/urllib/socket）
2. **端点层**：启动随机 Token + 权限引擎默认拒绝
3. **AI 行为层**：裁决引擎规则预检（系统路径删除/通配符大量删除 deny）+ AI 兜底裁决
4. **代码执行层**：多进程 + Windows 隔离临时账户 + 防火墙按 PID 放行 + 透明代理拦截 + 超时；`run_code` 前建系统还原点
5. **文件删除层**：`safe_delete.py` 路由到回收站 → `vault.archive_before_delete` 归档副本（版本化：日期子目录 + 毫秒时间戳 + `.meta.json`）
6. **网络工具层**：`_is_safe_host` 拒绝内网/回环/链路本地/保留地址，重定向逐跳校验（防 SSRF）
7. **注入层**：`_strip_prompt_injection` + `strip_roleplay_tone` + `_resolve_allowed_path`（文件工具限用户主目录）

### 9.2 保险库（bricks/sandbox/vault.py）

- 根目录：`PALM_VAULT_DIR` 或 `Data/vault`
- `archive_before_delete(src)` → `{id, original, archived_at, size, is_dir, restored?}`
- API：list/get/stats/restore/delete/clear；归档失败不阻断删除；safety 砖暴露 HTTP

### 9.3 系统还原点（bricks/sandbox/restore.py）

- PowerShell WMI 调用创建/列出/清理还原点（描述带 `PALM` 前缀）；`enable_system_protection` 开启系统保护
- 24h 合并破坏"操作前建点"语义（仅系统级兜底）

### 9.4 已知边界（复刻时注意）

- 隔离账户模式下沙箱写保险库主进程未必可读（与回收站同局限），可设 `PALM_VAULT_DIR` 指向共享路径缓解
- 沙箱 `safe_delete` 在 run_code 子进程按绝对路径独立加载，取 vault 用兼容两种上下文的懒加载 `_get_vault_module`

---

## 十、数据文件规范

### 10.1 Data/settings.json（权威设置）

```json
{"apiUrl": "http://localhost:8000", "windowSize": "", "background": "system",
 "maskBlur": 8, "fontSize": 16, "agentWebSearch": true, "agentDeepThink": false,
 "agentCharacterId": "", "agentToolMode": "native", "agentPlanningMode": "never",
 "agentAutoFilterTools": true, "agentStorageAutoCleanup": false,
 "theme": "light", "language": "zh-CN"}
```

### 10.2 Data/pool.json（存储池索引）

```json
{"categories": {"分类名": {"name": "...", "capacity_bytes": 0,
  "cleanup": {"order": "oldest_first", "keep_min_count": 0, "max_age_days": null, "auto": true},
  "created_at": 1784983553.83}},
 "files": [{"id": "12位hex", "category": "对话记录", "name": "原文件名",
   "stored_name": "<id>.json", "size": 486993, "stored_at": 1785725090.28}]}
```

### 10.3 Agent 记忆文件（Data/agent_memory/<convId>.json）

```json
{"personality": {"name": "", "traits": [], "preferences": {}},
 "affinity": 9.68, "recent_history": [{"role": "user", "content": "..."}],
 "user_profile": {}, "safety": {}, "violation_count": 0,
 "cooldown_active": false, "cooldown_remaining": 0,
 "current_age": 16, "current_grade": "高一"}
```

### 10.4 角色卡（Data/characters/<id>.json）

`id/name/tagline/personality_pillars[]/voice{vocabulary_range,sentence_rhythm,never_say[],ticks[]}/example_dialogue[]/flaws[]/...`（可含 `affinity_stages` 覆盖默认六阶段档位）。

### 10.5 Data/game_state.json

```json
{"total_exp": 0, "streak_days": 1, "last_checkin_date": "",
 "last_reset_date": "2026-08-03", "daily_chat_count": 0, "daily_plan_count": 0,
 "daily_tasks_done": [], "daily_task_exp_earned": 0,
 "unlocked_items": ["affinity_display"], "currency": 0}
```

### 10.6 Data/permissions.json

```json
{"file.read": {"state": "granted", "scope": "always", "granted_at": "...", "revoked_at": null}}
```

### 10.7 其他数据文件

- `Data/schedules.json`：定时任务持久化（scheduler 砖）
- `Data/skills/`：Skill 定义库（self_evolution 砖）
- `Data/gui_atlas/`：GUI 世界模型静态认知地图（加密落盘）
- `Data/observations/`、`Data/agent_habits/`：进化引擎数据

---

## 十一、前端事件流：Agent SSE → UI 归约

1. 用户发送 → `useChat` 组装请求 → POST `/api/agent/run`（或 `/api/chat` 非 Agent 模式），`AbortController` 管理中断
2. 逐行解析 `data: {...}`（SSE），按 `event.type` 交给 `applyAgentEvent`：
   - `thought` → ThinkingBlock 思维链
   - `tool_call`/`tool_result` → 过程条目（AgentProcessEntry）
   - `plan`/`plan_step` → 计划面板
   - `delta` → 正文增量追加（实时渲染 Markdown）
   - `ask_user` → 弹出 `AskUserCard`，用户应答 POST `/api/agent/ask-response`（主事件流阻塞等待）
   - `done` → 收尾：usage 汇总、好感度（若解锁显示）、会话落盘
3. 后台任务：`EventSource` 订阅 `/api/agent/events`（带 `conversation_id`），`applyBackgroundEvent` 追加为消息

---

## 十二、复刻路线图（照此顺序即可产出可运行项目）

### 阶段 0：骨架
1. 建目录（见第二节结构树），写根 `requirements.txt`（fastapi/uvicorn/pydantic/httpx/python-dotenv/python-multipart/pillow/numpy/opencv/rapidocr/docx/pptx/openpyxl/pdfplumber/pywebview/modelscope/gmssl）
2. 后端 `app/core/config.py` + `app/core/net.py` + `app/core/logging.py`
3. `app/main.py` create_app + `app/security.py` + `app/permission.py`
4. `app/api/system.py`（health/models/window-size）

### 阶段 1：核心砖
5. `app/bricks/base.py` + `__init__.py`（import 链）
6. `chat` 砖 + `models` 砖 + `usage` 砖
7. `settings` 砖 + `offline` 砖（gateway 四层拦截）

### 阶段 2：数据能力
8. `storage` 砖（PoolStore + pool.json）+ `crypto` 砖（SM4+指纹+恢复密钥）+ `conversations` + `file` + `parse`

### 阶段 3：Agent
9. `tool_base.py` + `tools/*` + `code_guard.py`
10. `memory` 砖（独立）+ `roleplay` 砖 + `affinity` 砖
11. `llm_bridge.py` + `native_runner.py` + `react_parser.py` + mixins + `core.py` + `protocols.py` + `plan_engine.py` + `question_hub.py` + `trace.py`
12. `agent/brick.py`（run SSE/工具清单/角色卡/好感度/双 Agent 端点）

### 阶段 4：安全与生态
13. `sandbox` 砖（run_isolation/net_policy/run_exec/safe_delete/vault/restore）+ `adjudicator` 砖 + `safety` 砖
14. `game` 砖 + `monitor` 砖

### 阶段 5：自进化与调度
15. `evolution` 砖 + `self_evolution` 砖（观察/提案/审批闭环）+ `scheduler` 砖

### 阶段 6：前端
16. `npm create vite`（react-ts）→ 按 7.4 组件清单补齐；`vite.config.ts` 代理与分块；`client-infra.ts`
17. `App.tsx` 分区 + `useChat` 状态机 + `chat-agent-events` 归约
18. 外观三层叠加 + `useAppearance` + `useSettings`

### 阶段 7：桌面壳与联调
19. `main.py`（PyWebView 壳 + 桥）+ `dev.py`/`dev.bat`/`run.bat`
20. 联调验证：`/api/health` 探活 → 前端构建 → 桌面壳加载 → Agent 对话 → 权限授权 → 存储/加密/游戏闭环

### 阶段 8（可选扩展）
21. `ollama` 砖 + `stt` 砖（sherpa-onnx 独立子进程）+ `tts_sovits` 砖（7z 自包含 GSV）+ `bench_eval.py` 评测

---

## 十三、复刻自检清单（对照代码底线规则）

- 函数 ≤50 行、文件 ≤500 行（超限拆子模块；已知 P2 待办：`brick.py`/`core.Agent.run`/`sandbox.run_isolation._run_win32` 等超限，留待低风险重构轮次）
- 布尔值 `is|has|should|can|will` 开头；函数名动词+业务名词；禁用泛词变量
- 砖块严格互不 import，跨砖一律 capabilities（缺失降级 None）
- 全程中文注释，只写"为什么"；标识符保留英文
- 不修改任何测试文件

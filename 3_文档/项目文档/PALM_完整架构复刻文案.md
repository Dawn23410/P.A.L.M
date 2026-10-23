# P.A.L.M — AI 桌面助手 完整项目架构文档

> **版本：1.0.0**  
> **目标：本文档详细记载了 P.A.L.M 项目的完整架构、模块分工、数据流和所有核心实现细节，可直接据此复刻整个项目。**

---

## 一、项目概述

P.A.L.M（Personal AI Life Manager）是一个三层解耦的 AI 桌面助手，核心定位为：

- **离线优先**：本地运行，所有数据默认落本地磁盘
- **可插拔砖块架构**：功能模块以「砖块」（Brick）为单位，互不直接调用，通过注册表暴露能力
- **三种运行形态**：桌面原生窗口（PyWebView）、浏览器开发模式、纯后端 API 服务
- **国密加密**：SM4 硬件指纹绑定加密，支持恢复密钥

### 技术栈总览

| 层 | 技术 | 职责 |
|---|---|---|
| **桌面壳** | PyWebView 6.x | OS 原生窗口、JS↔Python 桥、对话框 |
| **后端** | FastAPI + Uvicorn | HTTP API 服务、砖块注册与管理 |
| **前端** | React 18 + TypeScript + Tailwind CSS + Vite | SPA 用户界面 |
| **数据库** | 无（文件系统即数据库） | JSON 文件分类存储 |

---

## 二、目录结构

```
P.A.L.M/
├── main.py                    # PyWebView 桌面壳入口（启动后端 + 创建窗口）
├── run.bat                    # Windows 一键启动脚本
├── requirements.txt           # Python 依赖
├── .env                       # 环境变量配置
├── error.log                  # 启动错误日志
├── webview_debug.log          # WebView 调试日志
│
├── backend/                   # FastAPI 后端
│   ├── __init__.py
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py            # 应用工厂 create_app()
│   │   ├── security.py        # 启动随机 Token 鉴权
│   │   │
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   ├── config.py      # 全局配置（Settings 数据类）
│   │   │   ├── gateway.py     # 离线模式 httpx 拦截
│   │   │   ├── logging.py     # 统一结构化日志（JSON 单行）
│   │   │   └── net.py         # 端口读取工具
│   │   │
│   │   ├── bricks/            # ★ 砖块系统
│   │   │   ├── __init__.py    # 所有砖块导入注册
│   │   │   ├── base.py        # Brick / BrickManifest / BrickRegistry
│   │   │   │
│   │   │   ├── chat/          # 核心砖：流式对话
│   │   │   ├── models/        # 可选砖：模型供应商
│   │   │   ├── file/          # 可选砖：文件上传
│   │   │   ├── parse/         # 可选砖：文档解析
│   │   │   ├── ollama/        # 可选砖：Ollama 管理
│   │   │   ├── crypto/        # 可选砖：SM4 加解密
│   │   │   ├── storage/       # 可选砖：分类存储
│   │   │   ├── settings/      # 核心砖：应用设置
│   │   │   ├── conversations/ # 可选砖：会话记录
│   │   │   ├── usage/         # 可选砖：Token 用量
│   │   │   ├── offline/       # 核心砖：离线模式
│   │   │   ├── agent/         # 可选砖：Agent 框架
│   │   │   ├── adjudicator/   # 可选砖：裁决引擎
│   │   │   └── sandbox/       # 可选砖：沙箱
│   │   │
│   │   ├── api/               # 非砖块路由
│   │   │   ├── bricks.py      # /api/bricks 发现端点
│   │   │   └── system.py      # /api/health, /api/models, 窗口大小
│   │   │
│   │   └── schemas/           # Pydantic 数据模型
│   │       └── chat.py        # ChatMessage, ChatRequest, ModelInfo 等
│   │
│   ├── tools/                 # 重型工具脚本（懒加载）
│   │   ├── doc2struct.py      # 文档→结构化 JSON
│   │   ├── img_ocr.py         # RapidOCR 图片文字识别
│   │   └── img_preprocess.py  # OCR 前处理
│   │
│   └── uploads/               # 上传文件存储
│
├── frontend/                  # React SPA 前端
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── tailwind.config.ts
│   ├── postcss.config.js
│   ├── index.html
│   └── src/
│       ├── main.tsx           # 入口
│       ├── App.tsx            # 根组件
│       ├── index.css          # 全局样式
│       ├── types/             # TypeScript 类型定义
│       │   └── index.ts
│       ├── api/               # API 客户端
│       │   ├── client-infra.ts       # 鉴权 fetch + API 地址
│       │   ├── client.ts             # 统一导出
│       │   ├── client-chat.ts        # 聊天流
│       │   ├── client-health.ts      # 健康/设置
│       │   ├── client-crypto.ts      # 加密
│       │   ├── client-storage.ts     # 存储
│       │   ├── client-file.ts        # 文件
│       │   ├── client-conversations.ts # 会话
│       │   ├── client-usage.ts       # Token 用量
│       │   └── client-agent.ts       # Agent
│       ├── hooks/             # React Hooks
│       │   ├── use-settings.ts       # 设置状态管理
│       │   ├── use-chat.ts           # 聊天状态
│       │   └── use-appearance.ts     # 外观副作用
│       ├── components/        # UI 组件
│       │   ├── ChatSidebar.tsx
│       │   ├── MessageList.tsx
│       │   ├── ChatInput.tsx
│       │   ├── SettingsDialog.tsx
│       │   ├── StoragePanel.tsx
│       │   ├── Welcome.tsx
│       │   ├── TopBar.tsx
│       │   ├── ConversationHeader.tsx
│       │   ├── RoleplayStatusBar.tsx
│       │   ├── BackgroundLayer.tsx
│       │   ├── MaskLayer.tsx
│       │   └── ErrorBoundary.tsx
│       ├── lib/               # 工具函数
│       │   ├── open-external.ts
│       │   └── storageCache.ts
│       └── store/             # 状态管理（如适用）
│
└── Data/                      # 存储池根目录
    ├── settings.json          # 应用设置
    ├── pool.json              # 存储池元信息
    ├── .window_size           # 窗口大小（未加密）
    ├── .crypto_state.json     # 加密开关（未加密）
    ├── .crypto_keystore       # 加密密钥库
    ├── .recovery_checksum     # 恢复密钥校验码
    ├── .token_usage.json      # Token 用量台账
    ├── 对话记录/              # 会话聊天记录
    ├── 配置文件/              # 配置文件
    ├── 用户文件/              # 用户上传文件
    ├── 数据库/                # 数据库文件
    └── 插件/                  # 插件文件
```

---

## 三、三层解耦架构

### 3.1 设计原则

```
┌─────────────────────────────────────────────────────┐
│                   PyWebView 桌面壳                    │
│  main.py: 启动 Uvicorn + 创建原生窗口 + JS↔Python 桥  │
└──────────────────────┬──────────────────────────────┘
                       │ (HTTP + JS Bridge)
          ┌────────────┴────────────┐
          ▼                         ▼
┌──────────────────┐    ┌──────────────────────┐
│  FastAPI 后端      │    │   React SPA 前端     │
│  bricks/          │    │   Vite + Tailwind    │
│  port=0 动态分配   │    │   authedFetch 通信    │
└──────────────────┘    └──────────────────────┘
```

**三层之间完全解耦**：
1. **后端**（FastAPI）— 纯 HTTP 服务，不依赖桌面壳，可独立启动
2. **前端**（React SPA）— 通过 `fetch()` 与后端通信，不直接依赖桌面壳
3. **桌面壳**（PyWebView）— 启动后端、创建窗口、暴露原生桥方法

### 3.2 外观三层固定叠层（前端 CSS z 轴）

```
z-0:   BackgroundLayer（背景层）
       - 全屏固定，显示背景图片/颜色/渐变
       
z-1:   MaskLayer（遮罩层）
       - pointer-events: none
       - backdrop-filter: blur(毛玻璃)
       - 全屏覆盖

z-10:  .business-layer（业务层）
       - 设置打开时 invisible
       - 正常 UI 交互
```

### 3.3 启动流程

```
main.py 启动
  │
  ├─ _ensure_venv()       → 确认 .venv 存在且依赖已装
  ├─ dotenv.load_dotenv() → 加载 .env
  ├─ sys.path 插入 backend/ → 让 import app 可用
  │
  ├─ Uvicorn 启动（port=0 动态分配）
  │   └─ create_app()
  │       ├─ init_api_token()     → 生成随机 Token
  │       ├─ configure_logging()  → JSON 日志
  │       ├─ 注册中间件（CORS + 请求日志）
  │       ├─ 遍历 registry 挂载砖块路由
  │       ├─ 挂载 /api/bricks（发现）
  │       ├─ 挂载 /api/system（健康/模型）
  │       └─ 可选挂载 SPA
  │
  ├─ read_bound_port()   → 从 Uvicorn server.servers 读实际端口
  ├─ _wait_for_server()  → 轮询 /api/health 直到就绪
  ├─ _resolve_window_size() → 读 Data/.window_size
  │
  └─ webview.create_window()
      ├─ 注入 js_api=AppApi（resize_window, open_external, pick_directory 等）
      └─ webview.start()
```

---

## 四、砖块系统（Brick System）

### 4.1 砖块契约

每个砖块是一个 Python 模块包，在 `backend/app/bricks/<name>/` 下，通过 `base.py` 中定义的三个核心类型注册：

**BrickManifest**：砖块的声明元信息
```python
@dataclass
class BrickManifest:
    name: str              # 唯一标识（如 "chat"）
    title: str             # 中文展示名（如 "对话"）
    description: str       # 功能描述
    is_core: bool          # 核心砖（不可禁用）
    can_accept_files: bool # 是否接受文件
    is_streaming: bool     # 是否流式响应
    is_enabled: bool       # 是否启用
```

**Brick**：砖块实例
```python
@dataclass
class Brick:
    manifest: BrickManifest
    router: APIRouter | None          # FastAPI 子路由
    mounts: list[MountSpec]           # 静态挂载点
    capabilities: dict                # 暴露给其他砖块的能力
```

**BrickRegistry**：全局注册表（单例）
```python
class BrickRegistry:
    def register(self, brick) -> None   # 注册砖块
    def get(self, name) -> Brick | None # 按名获取
    def all(self) -> list[Brick]        # 全部砖块
    def manifests(self) -> list[Manifest] # 全部清单
```

### 4.2 砖块互不调用原则

> **核心约束：砖块之间严格不直接 import。**
> 
> 跨砖能力通过 `Brick.capabilities` 公共字典暴露，消费者通过 `registry.get("name").capabilities["key"]` 在运行时取用。

**例**：chat 砖需要调用模型的流式生成
```python
# chat/brick.py
def _models_capability(name: str):
    models_brick = registry.get("models")
    if models_brick:
        return models_brick.capabilities.get(name)
    return None

# 运行时取流
create_stream = _models_capability("create_stream")
if create_stream is None:
    raise HTTPException(503, detail="模型后端未启用")
async for delta in create_stream(messages, model=model, ...):
    ...
```

### 4.3 全部砖块一览

| 砖块 | 类别 | 核心 | 路由 | 暴露的能力 | 消费的能力 |
|---|---|---|---|---|---|
| **chat** | 核心 | ✅ | `/api/chat` (SSE), `/api/chat/file-support` | — | `models.create_stream`, `usage.check_quota`, `usage.record_usage` |
| **models** | 可选 | ❌ | `/api/models/discover` | `create_stream`, `is_model_file_capable`, `file_handling_mode`, `model_supports_files` | — |
| **file** | 可选 | ❌ | `/api/files/upload`, `/api/files/{id}/content` | `read_upload` | — |
| **parse** | 可选 | ❌ | `/api/parse`, `/api/parse/{job_id}`, `/api/parse/{job_id}/result` | — | — |
| **crypto** | 可选 | ❌ | `/api/crypto/{status,encrypt,decrypt,...}` | `encrypt_bytes`, `decrypt_bytes`, `is_enabled` | `storage.{encrypt_all_plaintext, decrypt_all_encrypted}` |
| **storage** | 可选 | ❌ | `/api/storage/{files,categories,stats,...}` | `get_store`, `store_file`, `read_file_content`, `find_config_file`, `delete_file`, `encrypt_all_plaintext`, `decrypt_all_encrypted`, `load_app_settings` | `crypto.{encrypt_bytes, decrypt_bytes}` |
| **settings** | 核心 | ✅ | `/api/settings` | `load_app_settings` | `crypto.{encrypt_bytes, decrypt_bytes}` |
| **conversations** | 可选 | ❌ | `/api/conversations` | — | `storage.{get_store, store_file, read_file_content, find_config_file, delete_file}` |
| **usage** | 可选 | ❌ | `/api/token-usage` | `check_quota`, `record_usage` | `settings.load_app_settings` |
| **offline** | 核心 | ✅ | `/api/offline` | `is_offline` | — |
| **agent** | 可选 | ❌ | `/api/agent/{run,tools,characters,affinity}` | `agent_tools`, `register_tool` | `models.create_stream`, `settings.load_app_settings`, `adjudicator.check_action` |
| **ollama** | 可选 | ❌ | `/api/ollama/{health,guide,catalog,download,...}` | — | — |
| **adjudicator** | 可选 | ❌ | `/api/adjudicator/{rules,check,history,...}` | `check_action` | — |
| **sandbox** | 可选 | ❌ | 沙箱隔离 | — | — |

---

## 五、后端详解

### 5.1 应用工厂（backend/app/main.py）

`create_app()` 是 FastAPI 应用工厂，执行顺序：

1. `init_api_token()` — 生成启动随机 Token
2. `configure_logging()` — JSON 结构化日志
3. 创建 FastAPI 实例
4. 注册 CORS 中间件
5. 注册请求日志中间件（记录 method/path/status/duration）
6. 遍历 `registry.all()`，挂载所有已启用砖块的 router
7. 挂载 `/api/bricks` 发现端点和 `/api/system` 系统端点
8. 遍历砖块，挂载各砖的静态挂载点（StaticFiles）
9. 若 `frontend/dist/index.html` 存在，挂载 SPA 并注入 `__API_BASE__` 和 `__API_TOKEN__`

### 5.2 启动随机 Token 鉴权（backend/app/security.py）

- 每次启动生成 `secrets.token_hex(32)`（64字符）
- 写入系统临时文件 `palm_api_token`
- 注入前端 `window.__API_TOKEN__`
- 敏感端点通过 `Depends(require_api_token)` 保护，使用 Bearer 头恒定时间比较
- dev 模式缺少 `__API_TOKEN__` 时需 `VITE_API_TOKEN` 环境变量

### 5.3 统一日志（backend/app/core/logging.py）

- JSON 单行格式：`{"ts","level","logger","rid","msg"}`
- `RequestIdFilter` 注入每请求唯一 `request_id`（UUID hex[:12]）
- `contextvars` 在异步上下文透传
- 第三方库日志（uvicorn/httpx/urllib3）统一压制到 WARNING

### 5.4 配置系统（backend/app/core/config.py）

`Settings` 数据类集中管理所有配置，均可用环境变量覆盖：

```python
HOST                    # 127.0.0.1
PORT                    # 8000（桌面壳启动时 port=0 动态分配）
CORS_ALLOW_ORIGINS      # 允许的跨域源
CORS_ALLOW_ORIGIN_REGEX # loopback 正则
FRONTEND_DIST           # frontend/dist 绝对路径
SERVE_FRONTEND          # "auto" | "true" | "false"
UPLOAD_DIR              # backend/uploads
STORAGE_POOL_DIR        # 项目根 Data/
```

---

## 六、各砖块实现细节

### 6.1 chat 砖块（核心）

**路由**：
- `POST /api/chat` — SSE 流式对话
- `GET /api/chat/file-support` — 模型文件能力查询

**核心流程**：
```
ChatRequest → resolve_chat_messages()
  ├─ 检查配额（usage.check_quota）→ 超额则 429
  ├─ 注入默认 system prompt
  ├─ 按文件模式处理附件
  └─ 取流（models.create_stream）→ 缺失则 503
  
SSE 事件格式：
  data: {"id": "<chatId>", "model": "...", "created": <ts>,
         "delta": "...", "reasoning": "..."}
  data: {"id": ..., "usage": {"prompt_tokens": N, ...}}
  data: [DONE]
```

**配额拦截**：流末自动记账，含真实用量回落字符估算兜底。

### 6.2 models 砖块（可选）

**路由**：
- `POST /api/models/discover` — 模型发现

**三协议**（backend/app/bricks/models/provider.py）：
1. **Mock**：本地回显模式，不依赖任何外部服务
2. **OpenAI 兼容**：`POST {base_url}/v1/chat/completions`，取 `delta.reasoning_content`/`reasoning`/`thinking`
3. **Anthropic 原生**：`POST {base_url}/v1/messages`，`max_tokens>=2048` 时开启 `thinking`，捕获 `thinking_delta`

**capabilities**：`create_stream`（核心）、`is_model_file_capable`、`file_handling_mode`、`model_supports_files`

### 6.3 file 砖块（可选）

**路由**：
- `POST /api/files/upload` — 上传文件（Depends 鉴权）
- `GET /api/files/{id}/content` — 读取文件内容（Depends 鉴权）

### 6.4 parse 砖块（可选）

**路由**：
- `POST /api/parse` — 提交解析任务（异步，返回 job_id）
- `GET /api/parse/{job_id}` — 查询任务状态
- `GET /api/parse/{job_id}/result` — 获取解析结果

**异常码**：UNSUPPORTED_FILE(4001)、PROCESS_FAILED(5001)、ENGINE_UNAVAILABLE(5002)

**依赖**：backend/tools/ 下的 doc2struct.py（多格式文档→结构化JSON + 内嵌图OCR）、img_ocr.py（RapidOCR）

### 6.5 storage 砖块（可选）

**路由**：
- `POST /api/storage/categories` — 创建分类
- `GET /api/storage/categories` — 列出分类（Depends 鉴权）
- `DELETE /api/storage/categories/{name}` — 删除分类
- `POST /api/storage/files` — 上传文件到分类
- `GET /api/storage/files` — 列表文件（Depends 鉴权）
- `GET /api/storage/files/{id}/content` — 读取文件（Depends 鉴权）
- `DELETE /api/storage/files/{id}` — 删除文件
- `GET /api/storage/stats` — 容量统计（Depends 鉴权）
- `GET /api/storage/breakdown` — 占比分析（Depends 鉴权）
- `GET /api/storage/encryption` — 加密状态（Depends 鉴权）
- `POST /api/storage/categories/{name}/cleanup` — 触发清理

**5 个固定分类**（带颜色）：
| 分类名 | 颜色 | 用途 |
|---|---|---|
| 配置文件 | `#9ca3af` | 应用配置 JSON |
| 对话记录 | `#f97316` | 会话聊天记录 |
| 用户文件 | `#3b82f6` | 用户上传文件 |
| 数据库 | `#22c55e` | 数据库文件 |
| 插件 | `#ec4899` | 插件文件 |

**存储原语**（经 capabilities 暴露）：
- `get_store()` — 返回 PoolStore 单例
- `store_file(category, name, data)` — 存储文件（含加密+索引）
- `read_file_content(file_id)` — 读取文件内容（加密自动解密）
- `find_config_file(category, filename)` — 按名查找
- `delete_file(file_id)` — 删除文件

### 6.6 crypto 砖块（可选）

**核心设计**：
1. **硬件指纹绑定**：`SHA256(主板序列号 + 卷序列号)` 双要素
   - 主板信息：Win 读注册表 `HKLM\HARDWARE\DESCRIPTION\System\BIOS`
   - 卷序列号：系统盘 `volume serial`
2. **SM4-CBC 加解密**（国密标准）
3. **主密钥**（Master Encryption Key, MEK）：16 字节随机数
   - 以硬件指纹派生的密钥密封落盘（`.crypto_keystore`）
   - 32 hex 明文即恢复密钥
4. **恢复密钥**：MEK 的 32 hex 明文，可脱离硬件解密
   - 前端永不显示恢复密钥文本
   - 通过 PyWebView 原生对话框「保存到文件」
   - 导入恢复密钥仅校验 32 hex 格式
5. **加密总开关**（默认关闭）：持久化到 `.crypto_state.json`

**路由**：
- `GET /api/crypto/status` — 状态（绑定/指纹前缀/算法）
- `POST /api/crypto/encrypt` — 加密文件
- `POST /api/crypto/decrypt` — 解密文件
- `POST /api/crypto/encrypt-text` — 加密文本
- `POST /api/crypto/decrypt-text` — 解密文本
- `GET /api/crypto/recovery-key` — 获取恢复密钥（Depends 鉴权）
- `GET /api/crypto/recovery-checksum` — 校验码（Depends 鉴权）
- `POST /api/crypto/recovery-key/import` — 导入恢复密钥
- `GET /api/crypto/encryption` — 加密开关状态
- `POST /api/crypto/encryption` — 开关加密（SSE 流式进度）

**密钥轮转**：`POST /api/crypto/rotate` 支持 dry_run 事务，复用 storage 的 `reencrypt_all` 全量重加密「对话记录」分类。

### 6.7 settings 砖块（核心）

- 独立落盘 `Data/settings.json`（不在 storage 分类下）
- GET/POST 均 `Depends(require_api_token)`
- 复用 crypto 的加密能力做透明加密
- 启动时检测自身文件缺失，经 storage 能力迁移旧设置（拆分兼容）

### 6.8 conversations 砖块（可选）

- 以 `<convId>.json` 为固定文件名 upsert 到「对话记录」分类
- 全部读端点 `Depends(require_api_token)` + 审计日志
- 底层落盘委托 storage 存储原语（复用单例、加密、索引）

### 6.9 usage 砖块（可选）

- 落盘 `Data/.token_usage.json`（隐藏文件，原子写 + threading.Lock）
- 按天/月聚合 + 逐请求明细（上限 5000 条）
- `check_quota()` 经 settings 砖能力读配额做拦截
- `record_usage()` 由 chat 砖在流末调用

### 6.10 offline 砖块（核心）

- 导入期调 `patch_httpx()` 全局拦截
- 拦截范围：外网 httpx 请求（放行 127.0.0.1/localhost/::1）
- 切换缓存：修改全局标志位，不重建 httpx 客户端

### 6.11 agent 砖块（可选）

**核心组件**：
1. **ReAct 循环引擎**：自主规划（Plan → Execute → Observe → Re-plan）
2. **工具注册系统**：内置工具 + 各砖块通过 `agent_tools` capability 注册的外部工具
3. **角色扮演引擎**（`bricks/agent/roleplay/`）：
   - 角色卡片：`CharacterCard`（性格、声音、示例对话、话痨程度等）
   - 内置角色：「沈墨」（清冷谋士）、「小桃」（元气少女）
   - 好感度系统（±100）：文本启发式计算（正/负/强负向词 + 互动长度黏合）
   - 记忆持久化：按 conversation_id 持久化好感度 + 近期对话

**路由**：
- `POST /api/agent/run` — 运行 Agent（SSE）
- `GET /api/agent/tools` — 工具列表
- `GET /api/agent/characters` — 角色列表
- `GET /api/agent/characters/{id}` — 角色详情
- `POST /api/agent/characters` — 创建角色
- `POST /api/agent/characters/import` — 从 Markdown 导入
- `GET /api/agent/affinity` — 好感度查询
- `POST /api/agent/affinity` — 好感度设定

---

## 七、前端详解

### 7.1 技术栈

- **框架**：React 18 + TypeScript
- **构建**：Vite 5（代码分割为 vendor-react/vendor-katex/vendor-markdown/vendor-icons）
- **样式**：Tailwind CSS 3 + tailwind-merge + class-variance-authority
- **UI 组件**：Radix UI（Avatar/Dialog/ScrollArea/Separator/Slot）
- **图标**：Lucide React
- **Markdown 渲染**：marked + DOMPurify + highlight.js + KaTeX

### 7.2 组件层次

```
<App>
  ├─ <BackgroundLayer />     → z-0 背景层
  ├─ <MaskLayer />           → z-1 毛玻璃遮罩
  └─ <div.business-layer>    → z-10 业务层
      ├─ <ChatSidebar />     → 左侧边栏（聊天/Agent/存储）
      ├─ <TopBar />          → 顶部栏（设置按钮）
      └─ <main>
          ├─ <RoleplayStatusBar />  → 角色好感度显示
          ├─ <ConversationHeader /> → 会话标题
          ├─ <MessageList /> / <Welcome />
          └─ <ChatInput />         → 输入框 + 模型选择
  <SettingsDialog />         → 设置弹窗（覆盖层）
```

### 7.3 API 通信

**统一入口**：`frontend/src/api/client-infra.ts`

```typescript
// API 地址优先级：
// 1. window.__API_BASE__ → 后端 SPA 注入
// 2. VITE_API_URL       → .env 环境变量
// 3. window.location.origin → 同源回退

// Token 优先级：
// 1. window.__API_TOKEN__ → 后端注入
// 2. VITE_API_TOKEN      → dev 模式

// 鉴权 fetch:
async function authedFetch(input, init) {
  const headers = new Headers(init.headers);
  if (API_TOKEN) headers.set("Authorization", `Bearer ${API_TOKEN}`);
  return fetch(input, { ...init, headers });
}
```

每个功能模块有独立客户端文件：
- `client-chat.ts` — SSE 流式聊天（ReadableStream 逐行解析）
- `client-health.ts` — 健康检查、模型列表、设置、发现
- `client-crypto.ts` — 加密状态、恢复密钥
- `client-storage.ts` — 存储分类/文件/占比
- `client-file.ts` — 文件上传/解析
- `client-conversations.ts` — 会话记录备份恢复
- `client-usage.ts` — Token 用量查询
- `client-agent.ts` — Agent 流式运行

### 7.4 状态管理

- **设置**（`use-settings.ts`）：localStorage（缓存/兜底） + 后端 GET/POST `/api/settings` 异步持久化
- **聊天**（`use-chat.ts`）：对话状态、消息列表、流式接收
- **外观**（`use-appearance.ts`）：主题/背景/窗口大小副作用，从设置读取应用

### 7.5 构建产物

- `frontend/dist/` — 构建后 SPA
- `frontend/dist/index.html` — FastAPI 注入 `__API_BASE__` + `__API_TOKEN__`
- 代码分割策略：
  - `vendor-react`：react + react-dom（~130KB）
  - `vendor-katex`：KaTeX（~400KB，仅 math 用到）
  - `vendor-markdown`：marked + DOMPurify + highlight.js
  - `vendor-icons`：lucide-react（~200KB）

---

## 八、PyWebView 桌面壳（main.py）

### 8.1 核心能力

| 桥方法 | 前端调用 | 说明 |
|---|---|---|
| `resize_window(w, h)` | `window.pywebview.api.resizeWindow(w, h)` | 调整 OS 窗口大小（≤0 最大化） |
| `open_external(url)` | `window.pywebview.api.openExternal(url)` | 默认浏览器打开链接 |
| `pick_directory()` | `window.pywebview.api.pickDirectory()` | 原生文件夹选择器 |
| `pick_files()` | `window.pywebview.api.pickFiles()` | 原生文件选择器 |
| `save_recovery_key(content, name)` | `window.pywebview.api.saveRecoveryKey(c, n)` | 原生保存对话框 |

### 8.2 启动参数

```python
webview.create_window(
    "P.A.L.M · AI Assistant",
    url,                    # 后端 SPA 地址或 Vite 开发服务器
    width=w, height=h,      # 从 Data/.window_size 读取
    min_size=(900, 600),
    js_api=api,
)
```

### 8.3 错误回退

PyWebView 无法创建原生窗口时：
1. 显示 GUI 消息框
2. 写入 error.log
3. 自动回退到系统默认浏览器打开 UI
4. 用户可在浏览器正常使用

---

## 九、安全体系

| 机制 | 说明 |
|---|---|
| **API Token** | 每次启动随机生成 64 hex，注入前端，敏感端点 Bearer 鉴权 |
| **文件端点** | file/parse/conversations/agent 等端点均 `Depends(require_api_token)` |
| **硬件指纹加密** | SM4-CBC + HMAC-SM3 签名，绑定主板和磁盘 |
| **恢复密钥** | 32 hex 脱离硬件解密，前端永不显示明文 |
| **CORS** | 仅允许 loopback 来源 + 环境变量指定源 |
| **日志防泄漏** | 日志不记录敏感信息 |

---

## 十、数据流示例

### 10.1 一次聊天请求

```
用户输入 → ChatInput
  → useChat.sendMessage()
    → 前端 authedFetch POST /api/chat
      → [后端] chat/brick.py
        → usage.check_quota()
          → settings.load_app_settings() 读配额
          → token_ledger.current_usage() 查已用量
          → 超额返回 429
        → resolve_chat_messages() 注入 system prompt + 文件处理
        → models.create_stream(messages, model, ...)
          → provider.py（OpenAI/Anthropic/Mock）
          → 经 httpx 流式调用外部 API
          → 返回 ChatDelta 流
        → 拼装 SSE 事件流
          → 逐步 yield {id, model, delta, reasoning, usage}
        → 流末 usage.record_usage() 记账
  → 前端 client-chat.ts 逐行解析 SSE
    → ReadableStream.getReader() 模式
    → 更新 MessageList 状态
  → 用户看到流式回复
```

### 10.2 一次 Agent 运行

```
用户输入 → ChatInput（Agent 模式）
  → agentRun()
    → POST /api/agent/run
      → 解析人设（角色卡片/自由文本）
      → Memory.initialize() 恢复好感度+近期对话
      → Agent.run(message, _llm_with_provider, adj_check)
        → ReAct 循环：
          1. 规划（生成步骤列表）
          2. 执行（调用 LLM + 工具）
          3. 观察（工具返回结果）
          4. 再规划（失败自动重规划）
        → 每步 yield AgentEvent (thinking / action / observation / delta / done)
      → 流末：adjust_affinity_from_turn() 计算好感度增量
      → Memory.set_affinity() 累加好感度
      → Memory.shutdown() 持久化
    → SSE 回到前端
```

### 10.3 文件存储（加密）

```
用户上传文件
  → POST /api/storage/files
    → storage 砖
      → crypto.is_enabled？
        → 是：crypto.encrypt_bytes(plaintext)
          → SM4-CBC 加密 + HMAC-SM3 签名
          → 返回加密包
        → 否：明文
      → PoolStore.store_file()
        → 写入 Data/<category>/<uuid+ext>
        → 更新 pool.json（FileRecord 含 encrypted 标志）
```

### 10.4 外观设置持久化（前端→后端→持久化）

```
用户修改主题/背景
  → useSettings().update(key, value)
    → 立即写入 localStorage（缓存/兜底）
    → 异步 POST /api/settings（完整 settings 对象）
      → settings 砖
        → crypto.is_enabled？
          → 是：crypto.encrypt_bytes()
        → 原子写 Data/settings.json
  → useAppearance(settings) 副作用触发
    → 应用 CSS 主题/背景图/毛玻璃
    → 若窗口大小变化：resize_window() → AppApi 桥
```

---

## 十一、复刻指南

### 11.1 环境要求

- **Python** 3.10+
- **Node.js** 18+
- **Windows** (PyWebView 跨平台可用，部分硬件指纹代码兼容 Linux)
- **可选依赖**：Edge WebView2 Runtime（桌面壳专用，无则回退浏览器）

### 11.2 复刻步骤

#### 后端
```bash
# 1. 创建虚拟环境
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2. 启动后端（独立运行，不启动桌面壳）
.venv\Scripts\python.exe -c "import uvicorn; uvicorn.run('app.main:create_app', factory=True, host='127.0.0.1', port=8000)"
```

#### 前端
```bash
cd frontend
npm install
npm run dev    # 开发热重载
npm run build  # 生产构建 → dist/
```

#### 桌面壳
```bash
python main.py  # 自动启动后端 + 创建原生窗口
```

### 11.3 砖块添加流程

1. 在 `backend/app/bricks/` 下建子包 `<name>/`
2. 创建 `__init__.py` 和 `brick.py`
3. 在 `brick.py` 中定义路由和 capabilities
4. 实例化 `Brick` 并调用 `registry.register(brick)`
5. 在 `bricks/__init__.py` 加一行 `from . import <name>`

### 11.4 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `HOST` | `127.0.0.1` | 后端监听地址 |
| `PORT` | `8000` | 后端监听端口（桌面壳用 port=0） |
| `CORS_ALLOW_ORIGINS` | `localhost:5173,...` | 跨域允许源 |
| `SERVE_FRONTEND` | `auto` | 是否托管 SPA |
| `FRONTEND_DIST` | `frontend/dist` | SPA 构建目录 |
| `UPLOAD_DIR` | `backend/uploads` | 上传文件目录 |
| `STORAGE_POOL_DIR` | `Data/` | 存储池根目录 |
| `VITE_API_URL` | — | 前端 dev 模式 API 地址 |
| `VITE_API_TOKEN` | — | 前端 dev 模式 Token |
| `PALM_TEST_PAGE` | — | 打开测试页而非 SPA |

---

## 十二、架构决策记录（ADR）

### ADR-1：砖块互不调用
**决策**：砖块之间不直接 import，通过注册表 capabilities 字典运行时分发。  
**原因**：避免导入期循环依赖，运行时替换/降级透明，可选砖缺失不影响核心功能。

### ADR-2：文件系统即数据库
**决策**：不使用关系型数据库，所有数据以 JSON 文件落盘。  
**原因**：桌面应用数据量小，JSON 文件直观可调试，文件系统操作在本地开发中足够。

### ADR-3：SM4 国密
**决策**：采用 SM4-CBC + HMAC-SM3 国密标准。  
**原因**：满足国内合规要求，gmssl 库纯 Python 无需编译。

### ADR-4：双要素硬件指纹
**决策**：主板信息 + 卷序列号（SHA256）。  
**原因**：换主板或系统盘才导致解密失效，重装系统/换网卡不影响，兼顾安全性和可用性。

### ADR-5：后端 port=0 动态分配
**决策**：Uvicorn 以 port=0 启动，OS 分配端口，避免端口冲突。  
**原因**：同一台机器可能运行多个实例或端口被其他程序占用。

### ADR-6：随机 Token 鉴权
**决策**：每次启动生成一次性随机 Token，不设持久化密钥。  
**原因**：本地桌面应用无需持久化密钥，重启即刷新可防止进程残留泄露。

---

*本文档记录了 P.A.L.M 项目 v1.0.0 的完整架构。所有砖块、数据流、通信模式和安全机制均按当前实现详细描述。*

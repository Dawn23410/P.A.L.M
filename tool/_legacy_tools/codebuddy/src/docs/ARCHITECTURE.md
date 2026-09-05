# 系统架构概览

> 本文档描述 P.A.L.M 的整体架构、数据流和核心设计决策。

---

## 1. 整体架构图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                             用户浏览器                                       │
│                     http://localhost:43210                                   │
└───────────────────────────┬─────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          前端 (React SPA)                                    │
│                                                                             │
│  路由层 (react-router-dom)                                                  │
│    /dashboard  /modules  /tts  /tts/custom-voice  /tts/voice-design         │
│    /tts/voice-clone  /tts/gs-basic  /tts/gs-advanced  /tts/gs-clone         │
│                                                                             │
│  ┌────────────────┐  ┌─────────────────────────────────────┐                │
│  │  页面组件层     │  │  Hooks 层 (状态/数据获取)            │               │
│  │  pages/        │  │  usePerformance  useModuleStatus     │               │
│  │                │  │  useConsole                           │               │
│  └───────┬────────┘  └──────┬──────────────────────────────┘                │
│          │                  │                                               │
│          ▼                  ▼                                               │
│  ┌────────────────────────────────────────────────────┐                     │
│  │  Store 层 (zustand)                                 │                     │
│  │  configStore.ts ←→ localStorage (500ms 防抖持久化) │                     │
│  │  themeStore.ts  ←→ CSS 变量 + 跟随系统               │                     │
│  │  configSchema.ts ← 单点真相 (默认值+类型+表单元数据)  │                     │
│  └───────────────────────┬────────────────────────────┘                     │
│                          │                                                  │
│                          ▼                                                  │
│  ┌──────────────────────────────────────────┐                              │
│  │  API 层                                    │                              │
│  │  apiUtils.ts — 通用 fetch (超时+错误处理)  │                              │
│  │  qwenTts.ts  — http://127.0.0.1:8000      │                              │
│  │  gptSoVits.ts — http://127.0.0.1:9880     │                              │
│  │                 http://127.0.0.1:5000      │                              │
│  └──────────────────────────────────────────┘                              │
└───────────────────────────┬─────────────────────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────────┐
        ▼                   ▼                       ▼
┌──────────────┐  ┌──────────────────┐  ┌─────────────────────┐
│ 模块管理器    │  │ palm-backend     │  │ TTS 运行时           │
│ Python 9090   │  │ Python 8080      │  │ Python 5000/8000    │
│              │  │                  │  │                     │
│ app.py       │  │ server.py        │  │ GSV Runtime Server  │
│ module_      │  │ CPU/内存/GPU     │  │ (端口 5000)         │
│ manager.py   │  │ 网络/磁盘        │  │ 整合包 CRUD         │
│              │  │ 2s 刷新缓存      │  │ 文件扫描            │
│ 模块安装/     │  │                  │  │                     │
│ 卸载/启停    │  │ monitor.py       │  │ Qwen3-TTS API       │
│ MANIFEST     │  │ CLI 监视器       │  │ (端口 8000)         │
│ 校验         │  │                  │  │ 语音合成/设计/克隆  │
│ 7z 解压       │  │                  │  │ 模型管理            │
│ 生命周期     │  │                  │  │                     │
└──────────────┘  └──────────────────┘  └─────────────────────┘
```

---

## 2. 数据流

### 2.1 配置持久化流

```
用户操作表单
  → configStore.set() 更新 zustand state
  → zustand subscribe 监听变更
  → 500ms 防抖 (debounce) 收集批量变更
  → JSON.stringify → localStorage.setItem('palm-config')
  → 下次页面加载: localStorage.getItem → JSON.parse → 深度合并到 schema 默认值
```

### 2.2 模块安装流

```
用户上传 .7z 文件
  → POST /api/module/validate (前端验证)
  → POST /api/module/install (后端执行)
      → [1] py7zr 解压到临时目录 (防 Zip Slip)
      → [2] 解析 MANIFEST.json (5 必填字段校验)
      → [3] 检查是否已安装 (重名冲突)
      → [4] 校验 entry 文件存在
      → [5] 移动到 runtime/modules/<name>-v<version>/
      → [6] 后台执行 postInstall 钩子
      → [7] 计算 SHA-256, 注册 ModuleState
      → [失败] 自动回滚: 删除临时目录 + 已移动文件
  → 前端 GET /api/modules 刷新列表
```

### 2.3 性能监控流

```
Dashboard.tsx 挂载
  → usePerformance() Hook 启动 setInterval(2s)
  → fetch http://127.0.0.1:8080/api/metrics
  → palm-backend server.py 收集:
      - cpuinfo → CPU 型号/频率/使用率/温度
      - psutil → 内存/网络/磁盘
      - pynvml → GPU 使用率
      - WMI (Windows) → 内存频率
  → 缓存 2s 结果
  → 前端 setState 更新图表

usePerformance Hook 卸载
  → clearInterval 停止轮询
```

### 2.4 TTS 合成流

```
用户填写参数点击"生成"
  → 从 configStore 读取当前选中的模型 (qwen3-tts / gpt-sovits)
  → qwenTts.ts / gptSoVits.ts 调用对应 API
  → 后端返回 WAV 音频 Blob
  → 前端创建 ObjectURL → <audio> 播放
  → 提供下载按钮
```

---

## 3. 服务端口分配

| 服务 | 端口 | 启动方式 | 说明 |
|---|---|---|---|
| Vite 前端 Dev Server | 43210 | `npm run dev` | React 开发服务器 |
| 模块管理 API | 9090 | `manager/app.py` | FastAPI + uvicorn |
| palm-backend 性能监控 | 8080 | launcher 自动启动 | FastAPI + psutil |
| GSV Runtime Server | 5000 | launcher 自动启动 | 文件操作 + 整合包管理 |
| GPT-SoVITS TTS 合成 | 9880 | 由 GSV 启动 | 语音合成 API |
| Qwen3-TTS API | 8000 | 独立模块启动 | 模型推理 API |

---

## 4. 核心设计决策

### 4.1 配置即代码 — configSchema.ts

`configSchema.ts` 是配置系统的"单点真相"（Single Source of Truth），它同时定义了：

- **默认值** — 新用户首次使用时的初始配置
- **TypeScript 类型** — 编译期类型检查
- **表单元数据** — 动态渲染表单的字段配置（标签、提示、最小值/最大值、步长等）

这样做的优点是：添加一个新配置项只需修改这一个文件，表单渲染逻辑自动适配，类型错误在编译期即可发现。

### 4.2 前端本地持久化

所有模块配置保存在 `localStorage` 中，不与后端耦合。这带来了两个好处：

- **解耦** — 即使后端服务暂时不可用，前端配置界面也可以正常使用
- **离线可用** — 配置修改不依赖网络请求

但缺点是多端同步需要额外的实现。

### 4.3 原子回滚机制

模块安装的每一步失败都会自动清理已产生的脏文件。解压时使用 `py7zr.extract()` 的 `filter` 参数防 Zip Slip 攻击，确保安全性。

### 4.4 轻量化 API 架构

前端直接通过 `fetch` 轮询多个后端服务（8080/9090/5000/9880/8000），不做 API 网关聚合。选择这种架构的原因是：

- 各服务独立部署、独立开发
- 减少中间件依赖
- 服务间无共享状态，天然解耦

### 4.5 GSVP 自定义二进制格式

GPT-SoVITS 整合包使用自定义文件格式（魔数 `GSVP\0\1`），其设计意图包含：

- 魔数伪装 — 使用自定义魔数替代标准 7z 魔数，实现"文件类型伪装"（防扫描/防误删）
- XOR 简单混淆 — 文件名层 XOR 加密，防止明文字符串泄露文件结构
- 浏览器端创建 — `gsvPackage.ts` 支持在浏览器端直接创建/解析 GSVP 包

---

## 5. 安全考量

- **Zip Slip 防护** — 解压时检查路径穿越（`../` 和绝对路径）
- **路径配置** — 通过 API 获取模块存储路径，不硬编码
- **子进程隔离** — 模块入口以子进程运行，终止时强制杀死进程树
- **文件类型验证** — 上传时检查文件魔数和扩展名
- **超时保护** — 所有 API 调用有超时限制，防止死锁

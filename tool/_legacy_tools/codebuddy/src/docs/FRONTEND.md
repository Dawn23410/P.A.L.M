# 前端架构

> 本文档描述 P.A.L.M 前端代码的结构、路由、状态管理和组件设计。

---

## 1. 技术选型

| 层 | 选择 | 理由 |
|---|---|---|
| 框架 | React 18 | 组件化、生态成熟 |
| 语言 | TypeScript | 类型安全、IDE 友好 |
| 构建 | Vite 5 | 极快的 HMR、原生 ESM |
| UI 库 | Ant Design 5 | 丰富的桌面级组件、支持主题定制 |
| 状态管理 | zustand | 轻量、TypeScript 友好、无样板代码 |
| 路由 | react-router-dom v6 | 嵌套路由、Outlet 布局 |
| 图表 | @ant-design/charts | 与 Ant Design 风格统一 |

---

## 2. 路由设计

路由在 `src/main.tsx` 中定义：

```tsx
<BrowserRouter>
  <Routes>
    <Route element={<Layout />}>
      <Route index element={<Navigate to="/dashboard" replace />} />
      <Route path="/dashboard" element={<Dashboard />} />
      <Route path="/modules" element={<ModuleManagement />} />
      <Route path="/tts" element={<TtsMainPage />} />
      <Route path="/tts/custom-voice" element={<TtsCustomVoice />} />
      <Route path="/tts/voice-design" element={<TtsVoiceDesign />} />
      <Route path="/tts/voice-clone" element={<TtsVoiceClone />} />
      <Route path="/tts/gs-basic" element={<GsBasicConfig />} />
      <Route path="/tts/gs-advanced" element={<GsAdvancedConfig />} />
      <Route path="/tts/gs-clone" element={<GsVoiceClone />} />
    </Route>
  </Routes>
</BrowserRouter>
```

路由结构采用 **嵌套路由（Outlet）** 模式，`Layout` 组件作为外层壳，提供侧边栏和顶部栏，子路由在 `<Outlet />` 位置渲染。

### 路由组织策略

- **扁平路由** — 所有页面都是同级路由，不使用深层嵌套
- **TTS 分组** — `/tts/*` 下的路由共享 TTS 引擎选择（Qwen3-TTS / GPT-SoVITS），通过 `configStore` 状态管理当前选中引擎
- **重定向** — 根路径 `/` 自动跳转到 `/dashboard`

---

## 3. 状态管理

### 3.1 配置状态 — configStore.ts

```typescript
interface ConfigState {
  config: ConfigSchema;
  get: <K extends keyof ConfigSchema>(key: K) => ConfigSchema[K];
  set: <K extends keyof ConfigSchema>(key: K, value: ConfigSchema[K]) => void;
  reset: (moduleId?: ModuleId) => void;
}
```

特点：

- **500ms 防抖持久化** — 频繁的 `set()` 调用会被合并，最后只写一次 localStorage
- **深层合并** — 加载时从 localStorage 读取的值通过深度合并与 schema 默认值合并，确保新增配置项有默认值
- **模块级重置** — `reset('tts')` 仅重置指定模块的配置到默认值

### 3.2 配置 Schema — configSchema.ts

```typescript
const configSchema = {
  // 模块切换（不持久化）
  activeTab: { type: 'internal', default: 'dashboard' },
  // TTS 配置
  tts: {
    selectedModel: { type: 'persist', default: 'qwen3-tts' },
    selectedSection: { type: 'persist', default: 'voice' },
    qwenSize: { type: 'persist', default: '0.6B' },
    // ...
  },
  // 其他模块配置...
};
```

`configSchema` 也被转换为 TypeScript 类型 `ConfigSchema`，用于编译期类型检查。

### 3.3 主题状态 — themeStore.ts

```typescript
interface ThemeState {
  darkMode: boolean;
  toggle: () => void;
  followSystem: boolean;
}
```

支持三种模式：
- **手动切换** — 用户通过侧边栏按钮切换明暗
- **跟随系统** — 使用 `window.matchMedia('(prefers-color-scheme: dark)')` 监听系统主题变化

---

## 4. 组件结构

### 4.1 Layout 组件（`components/Layout.tsx`）

核心布局组件，包含：
- **侧边栏** — 固定宽度 240px，包含 Logo、导航菜单、主题切换
- **顶部栏** — 显示当前时间（实时更新）、页面标题
- **内容区** — `<Outlet />` 渲染子路由页面

导航项配置：

```typescript
const navItems = [
  { path: '/dashboard', label: '仪表盘', icon: <DashboardOutlined /> },
  { path: '/modules',   label: '模块管理', icon: <AppstoreOutlined /> },
  { path: '/tts',       label: '语音合成', icon: <SoundOutlined /> },
];
```

### 4.2 页面组件

所有页面组件位于 `src/pages/` 目录，无共享的页面级抽象组件（如 PageHeader、PageContainer），由各页面自行编排内容。

### 4.3 自定义 Hooks

| Hook | 文件 | 用途 | 数据来源 |
|---|---|---|---|
| `usePerformance()` | `hooks/usePerformance.ts` | 系统性能数据采集 | `GET :8080/api/metrics` (2s 轮询) |
| `useModuleStatus()` | `hooks/useModuleStatus.ts` | 模块状态查询 | `GET :8080/api/modules` |
| `useConsole()` | `hooks/useConsole.ts` | 交互式控制台 | 本地状态管理 |

---

## 5. API 层

API 封装位于 `src/api/` 目录：

```
api/
├── apiUtils.ts       # 通用工具：fetch 封装、超时、错误处理
├── qwenTts.ts        # Qwen3-TTS API (端口 8000)
└── gptSoVits.ts      # GPT-SoVITS API (端口 9880/5000)
```

### 通用工具（apiUtils.ts）

```typescript
// GET 请求
export async function apiGet<T>(url: string, timeout = 10000): Promise<T>
// POST 请求（JSON 体）
export async function apiPost<T>(url: string, body?: unknown, timeout = 30000): Promise<T>
// 获取音频 Blob
export async function apiGetAudioBlob(url: string, body: unknown): Promise<Blob>
```

所有 API 请求都自带：
- 超时控制（默认 GET 10s，POST 30s）
- AbortController 取消机制
- 统一的 JSON 解析和错误处理

---

## 6. 目录结构速览

```
src/
├── index.html              # HTML 入口
├── main.tsx                # React 根组件 + 路由
├── vite-env.d.ts           # Vite 类型声明
├── components/
│   └── Layout.tsx          # 侧边栏 + 顶部栏 + Outlet
├── pages/
│   ├── Dashboard.tsx        # 仪表盘
│   ├── ModuleManagement.tsx # 模块管理
│   ├── TtsMainPage.tsx      # TTS 主页
│   ├── TtsCustomVoice.tsx   # Qwen3 语音合成
│   ├── TtsVoiceDesign.tsx   # Qwen3 音色设计
│   ├── TtsVoiceClone.tsx    # Qwen3 语音克隆
│   ├── GsBasicConfig.tsx    # GPT-SoVITS 基础配置
│   ├── GsAdvancedConfig.tsx # GPT-SoVITS 高级参数
│   └── GsVoiceClone.tsx     # GPT-SoVITS 语音克隆
├── hooks/
│   ├── usePerformance.ts    # 性能监控
│   ├── useModuleStatus.ts   # 模块状态
│   └── useConsole.ts        # 控制台
├── store/
│   ├── configStore.ts       # 配置持久化 Store
│   ├── configSchema.ts      # 配置 Schema + 类型
│   └── themeStore.ts        # 主题 Store
├── api/
│   ├── apiUtils.ts          # API 工具
│   ├── qwenTts.ts           # Qwen3-TTS API
│   └── gptSoVits.ts         # GPT-SoVITS API
├── utils/
│   └── gsvPackage.ts        # GSVP 包工具
├── styles/
│   ├── styles.css           # 全局样式系统
│   └── qwen-tts.css         # TTS 专用样式
├── assets/
│   └── favicon.svg          # 品牌 Logo
└── docs/                    # 开发文档
```

---

## 7. 页面功能速览

| 页面 | 功能 | 后端依赖 |
|---|---|---|
| **仪表盘** | 系统性能图表（CPU/内存/GPU/网络/磁盘）、模块状态概览、交互式控制台 | 8080 |
| **模块管理** | 已安装模块卡片列表、上传安装 `.7z` 包、卸载模块 | 9090 |
| **TTS 主页面** | 选择引擎（Qwen3-TTS / GPT-SoVITS）和功能分区 | - |
| **Qwen3 语音合成** | 文本输入 → 选择音色 → 生成 WAV | 8000 |
| **Qwen3 音色设计** | 调整音色参数 → 生成试听 | 8000 |
| **Qwen3 语音克隆** | 上传参考音频 → 克隆参数 → 生成 | 8000 |
| **GPT-SoVITS 基础** | 整合包管理（上传/创建/载入/删除） | 5000, 9880 |
| **GPT-SoVITS 高级** | 情感标签配置、高级 TTS 参数 | 9880 |
| **GPT-SoVITS 克隆** | 克隆参数配置（语速/top_k/top_p） | 9880 |

# 开发指南

> 本文档帮助开发者快速上手 P.A.L.M 项目的开发工作。

---

## 1. 环境准备

### 1.1 必需工具

| 工具 | 最低版本 | 用途 |
|---|---|---|
| Node.js | ≥ 18 | 前端构建 |
| npm / pnpm | 随 Node.js | 包管理 |
| Python | ≥ 3.10 | 后端服务 |
| Git | 任意 | 版本控制 |

### 1.2 前端依赖

```bash
cd Codebuddy
npm install
```

主要依赖（`package.json`）：

| 包名 | 用途 |
|---|---|
| react, react-dom | 前端框架 |
| react-router-dom | 路由 |
| antd, @ant-design/icons | UI 组件库 |
| zustand | 状态管理 |
| @ant-design/charts | 图表（仪表盘用） |
| crypto-js | SHA-256 计算 |
| typescript | 类型检查 |

### 1.3 Python 后端依赖

```bash
# 模块管理后端
cd manager
python -m venv venv
venv\Scripts\pip install -r requirements.txt
# 依赖: fastapi, uvicorn[standard], py7zr, pydantic
```

```bash
# palm-backend 模块
cd runtime/modules/palm-backend
python -m venv venv 2>/dev/null || true
pip install fastapi uvicorn[standard] psutil py-cpuinfo pynvml
```

---

## 2. 启动开发环境

### 2.1 前端开发服务器

```bash
npm run dev
```

- 启动在 `http://localhost:43210`
- 支持 HMR（热模块替换）
- TypeScript 类型检查在编辑器中实时运行

### 2.2 后端服务

**模块管理 API（端口 9090）：**

```bash
cd manager
venv\Scripts\python app.py
```

**性能监控（端口 8080）：**

```bash
cd runtime/modules/palm-backend
python server.py
```

### 2.3 一键启动（完整环境）

```bash
python launcher.py
```

启动器会自动处理端口冲突、等待服务就绪、打开浏览器。

---

## 3. 项目开发工作流

### 3.1 添加新页面

1. 在 `src/pages/` 下创建新组件
2. 在 `src/main.tsx` 中添加路由
3. 在 `src/store/configSchema.ts` 中添加配置项（如有需要）
4. 在 `src/components/Layout.tsx` 侧边栏添加导航项

**路由注册示例（main.tsx）：**

```tsx
<Route path="/my-new-page" element={<MyNewPage />} />
```

**侧边栏添加示例（Layout.tsx）：**

```tsx
{ navItems: { path: '/my-new-page', label: '新页面', icon: <NewIcon /> } }
```

### 3.2 添加新配置项

1. 在 `configSchema.ts` 中 `ConfigSchema` 接口添加字段
2. 在 `defaultConfig` 中添加默认值
3. 如需要表单渲染，在对应位置添加表单元数据
4. 在页面组件中通过 `useConfigStore()` 读取/写入

### 3.3 连接新后端服务

1. 在 `src/api/` 下创建新的 API 封装文件
2. 封装 fetch 调用，使用 `apiUtils.ts` 的通用错误处理
3. 在页面组件中调用

```typescript
// src/api/myService.ts
import { apiPost } from './apiUtils';

const API_BASE = 'http://127.0.0.1:3000';

export async function myAction(params: MyParams): Promise<MyResult> {
  return apiPost(`${API_BASE}/api/action`, params);
}
```

### 3.4 创建新模块包

参见 [模块开发指南](MODULE_DEV.md)。

---

## 4. 构建与部署

### 4.1 前端构建

```bash
npm run build
```

构建产物输出到 `dist/` 目录：
- `dist/index.html`
- `dist/assets/*.js` (Vite 打包、代码分割)
- `dist/assets/*.css` (提取的样式)

### 4.2 预览构建产物

```bash
npm run preview
```

会在本地启动一个静态服务器预览构建产物。

### 4.3 部署方式

P.A.L.M 是桌面级应用，不涉及传统意义上的远程部署。常见使用方式：

1. **开发模式运行** — `npm run dev` + 各后端进程
2. **构建后静态服务** — `npm run build` 后用任意静态服务器托管 `dist/`
3. **完整打包** — 通过 `.7z` 备份整个项目目录（含 node_modules + venv）

---

## 5. 代码规范

### 5.1 TypeScript

- 使用 `interface` 而非 `type`（对象类型）
- 显式标注函数返回值类型
- 使用 `as const` 保护常量对象

### 5.2 React 组件

- 函数组件 + Hooks，无 class 组件
- 使用 `useCallback` / `useMemo` 优化重渲染
- 避免在渲染函数中创建新的对象/函数（除非必要）

### 5.3 命名规范

| 类型 | 规范 | 示例 |
|---|---|---|
| 组件文件 | PascalCase | `ModuleManagement.tsx` |
| Hook 文件 | camelCase, `use` 前缀 | `usePerformance.ts` |
| API 封装 | camelCase | `qwenTts.ts` |
| CSS 文件 | kebab-case | `qwen-tts.css` |

### 5.4 Git

- 提交信息使用中文或英文，保持同一 repo 内一致
- 新功能分支命名：`feat/xxx`、`fix/xxx`

---

## 6. 调试技巧

### 6.1 检查配置状态

```typescript
// 在浏览器控制台查看当前配置
const config = JSON.parse(localStorage.getItem('palm-config') || '{}');
console.table(config);
```

### 6.2 重置配置

```typescript
localStorage.removeItem('palm-config');
```

### 6.3 检查模块状态

```bash
# 模块管理 API 健康检查
curl http://127.0.0.1:9090/

# 查看所有已安装模块
curl http://127.0.0.1:9090/api/modules

# 查看模块完整性
curl http://127.0.0.1:9090/api/modules/with-status

# 性能监控
curl http://127.0.0.1:8080/api/metrics
```

### 6.4 日志查看

- 前端日志：浏览器 DevTools → Console
- 后端日志：终端窗口输出（launcher.py 包含彩色日志）
- 使用 `kill_python.cmd` 可强制停止所有 Python 进程

### 6.5 常见问题

| 问题 | 原因 | 解决 |
|---|---|---|
| 端口被占用 | 另一个进程使用了同一端口 | 修改端口配置或终止冲突进程 |
| 模块无法安装 | `.7z` 包格式不正确 | 检查 MANIFEST.json 是否完整 |
| 前端页面空白 | vite 未启动或路由错误 | 检查 `npm run dev` 是否正常 |
| API 返回 500 | 后端服务未启动 | 确认对应端口的服务已运行 |
| GPU 信息为空 | 无 NVIDIA GPU 或 pynvml 未安装 | `pip install pynvml` |

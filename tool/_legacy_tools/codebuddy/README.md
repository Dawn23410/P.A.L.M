# P.A.L.M

**P**arameter **A**dministration & **L**ifecycle **M**anager

桌面 AI 模块化平台的后端参数配置与生命周期管理中心。

---

## 概述

P.A.L.M 是一个可插拔的桌面级 AI 模块化控制台，提供了一个统一的前端控制面板，用于管理多个 AI 功能模块的配置、安装、启动与监控。它让用户无需直接操作终端或配置文件，即可对 AI 模块进行生命周期管理。

### 核心能力

- **模块化插件体系** — 支持通过 `.7z` 包安装/卸载独立功能模块，每个模块自带 MANIFEST 清单
- **模块生命周期管理** — 从上传、验证、安装、启动到卸载的完整链路，失败时自动回滚
- **统一配置面板** — 所有已安装模块的参数配置收敛到前端，通过 localStorage 本地持久化
- **系统性能监控** — 实时展示 CPU、内存、GPU、网络、磁盘的负载与温度
- **TTS 语音合成** — 集成 Qwen3-TTS 与 GPT-SoVITS 两大语音引擎
- **一键启动** — launcher.py 自动拉起所有服务（运行时、模块管理、前端）

---

## 快速开始

### 环境要求

- Node.js ≥ 18
- Python ≥ 3.10
- npm 或 pnpm

### 启动

**方式一：一键启动（推荐）**

```bash
# Windows
双击 启动.bat
# 或
python launcher.py
```

启动器会依次拉起：
1. GSV Runtime Server (端口 5000)
2. 模块管理 API (端口 9090)
3. 所有已安装模块 (如 palm-backend → 端口 8080)
4. Vite 前端开发服务器 (端口 43210)
5. 自动打开浏览器

**方式二：分步启动**

```bash
# 1. 安装前端依赖
npm install

# 2. 启动模块管理后端
cd manager
python -m venv venv
venv\Scripts\pip install -r requirements.txt
venv\Scripts\python app.py

# 3. 启动前端开发服务器
npm run dev
```

### 访问

打开浏览器访问 `http://localhost:43210/dashboard`

---

## 技术栈

| 层 | 技术 | 版本 |
|---|---|---|
| 前端框架 | React + TypeScript | 18.3 / 5.6 |
| 构建工具 | Vite | 5.4 |
| UI 库 | Ant Design | 5.21+ |
| 状态管理 | zustand | 4.5 |
| 路由 | react-router-dom | 6.x |
| 模块管理后端 | Python FastAPI + uvicorn | - |
| 系统监控 | psutil + cpuinfo + pynvml | - |
| 归档处理 | py7zr (LZMA2) | - |
| 持久化 | localStorage (500ms 防抖) | - |

---

## 项目结构

```
P.A.L.M/
└── Codebuddy/
    ├── src/                     # 前端源码（React SPA）
    │   ├── pages/               # 页面组件
    │   ├── components/          # 通用组件
    │   ├── hooks/               # 自定义 Hook
    │   ├── store/               # zustand 状态管理
    │   ├── api/                 # API 封装层
    │   ├── utils/               # 工具函数
    │   ├── styles/              # CSS 样式
    │   └── docs/                # 开发文档
    ├── manager/                 # 模块管理后端（Python FastAPI）
    ├── runtime/                 # 运行时环境
    │   └── modules/             # 已安装模块
    ├── launcher.py              # 一键启动引擎
    └── package.json
```

---

## 路由 / 页面

| 路由 | 页面 | 说明 |
|---|---|---|
| `/dashboard` | 仪表盘 | 系统性能概览、模块状态、控制台 |
| `/modules` | 模块管理 | 模块卡片列表、上传安装/卸载 |
| `/tts` | TTS 主页面 | 引擎选择（Qwen3-TTS / GPT-SoVITS） |
| `/tts/custom-voice` | Qwen3-TTS 语音合成 | 文本转语音参数配置 |
| `/tts/voice-design` | Qwen3-TTS 音色设计 | 音色特征参数设计 |
| `/tts/voice-clone` | Qwen3-TTS 语音克隆 | 参考音频克隆 |
| `/tts/gs-basic` | GPT-SoVITS 基础配置 | 整合包管理、模型配置 |
| `/tts/gs-advanced` | GPT-SoVITS 高级参数 | 情感标签、高级设置 |
| `/tts/gs-clone` | GPT-SoVITS 语音克隆 | 克隆参数配置 |

---

## 相关文档

| 文档 | 说明 |
|---|---|
| [架构概览](src/docs/ARCHITECTURE.md) | 系统架构、数据流、组件关系 |
| [开发指南](src/docs/DEVELOPER.md) | 环境搭建、开发工作流、构建部署 |
| [API 文档](src/docs/API.md) | 全部后端 API 接口说明 |
| [模块开发指南](src/docs/MODULE_DEV.md) | 如何创建和打包模块 |
| [前端架构](src/docs/FRONTEND.md) | 前端路由、状态管理、组件设计 |
| [后端服务](src/docs/BACKEND.md) | 后端各服务职责与配置 |
| [设计规格](src/docs/design-spec.json) | 设计系统和组件规格 |
| [GSVP 包规范](src/docs/gsv-package-spec.md) | GPT-SoVITS 整合包格式规范 |

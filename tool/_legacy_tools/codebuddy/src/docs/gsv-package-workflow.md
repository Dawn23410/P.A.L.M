# GSV 整合包创建与加载流程

## 一、架构概述

整合包系统分为两大流程，前后端协作完成：

```
前端 (React)
  GsBasicConfig.tsx  →  创建表单 + 本地压缩打包
  GsConfigPanel      →  包列表展示 + 操作
  gptSoVits.ts       →  API 调用层

后端 (GPT-SoVITS API :9880)
  GET  /packages/path      →  搜索路径
  GET  /packages/search    →  扫描 config.json
  POST /packages/load      →  载入 .gsvp → 解压
  POST /packages/download  →  复制到下载目录
```

---

## 二、文件格式

### 2.1 文件扩展名

| 类型 | 扩展名 |
|------|--------|
| 整合包文件 | `.gsvp` |
| 内部压缩格式 | 7z (LZMA) |
| 配置文件 | `config.json` |

### 2.2 魔数定义

| 阶段 | 魔数 (前 6 字节) | ASCII |
|------|-------------------|-------|
| 7z 原始魔数 | `37 7A BC AF 27 1C` | `7z¼¯'`|
| **自定义 GSVP 魔数** | **`47 53 56 50 00 01`** | **`GSVP\0\1`** |

### 2.3 文件内部结构

```
.gsvp 文件
├── [魔数 6B] 47 53 56 50 00 01  ← 替换后的自定义魔数
├── [LZMA 压缩数据]
│   ├── [config JSON len 4B]
│   ├── [config JSON]
│   ├── [GPT 文件 len 4B]
│   ├── [GPT 文件数据]
│   ├── [SoVITS 文件 len 4B]
│   ├── [SoVITS 文件数据]
│   ├── [音频文件 len 4B]
│   └── [音频文件数据]
└── [LZMA 压缩结束]
```

---

## 三、创建整合包流程

### 3.1 操作入口

GSV 模型下 → 顶部配置栏 → `创建整合包` 按钮 → 弹出 Modal

### 3.2 表单填写

```
包名 [可莉_ZH                            ]
─────────────────────────────────────────────
GPT 模型路径  [可莉_ZH-e10.ckpt      ] [选择]  ← 仅 .ckpt
SoVITS 模型路径 [可莉_ZH_e10_s530_l32.pth] [选择] ← 仅 .pth
参考音频路径  [ref.wav                ] [选择]  ← 仅 .wav
参考文本      [今天天气真好...            ]
─────────────────────────────────────────────
参考语种 [中文 ▼]  模型版本 [请选择版本 ▼]
自动识别: V4   ← 选择模型文件后自动检测
─────────────────────────────────────────────
[确认创建]
```

### 3.3 创建流程（前端本地处理）

```
用户点击 "确认创建"
  ↓
Step 1 ── 校验
         ├── GPT 文件？     → 否则警告
         ├── SoVITS 文件？  → 否则警告
         ├── 音频文件？     → 否则警告
         ├── 参考文本？     → 否则警告
         └── 模型版本？     → 否则警告

Step 2 ── 并行计算 MD5
         ├── GPT      → SparkMD5
         ├── SoVITS   → SparkMD5
         └── 音频     → SparkMD5

Step 3 ── 构建 config.json
         └── 含 version, created_at, 文件+MD5, 参数

Step 4 ── 压缩打包（前端 LZMA）
         ├── 各文件读为 Uint8Array
         ├── 拼接为自描述格式 (len + data) × 4
         ├── LZMA 压缩 (mode=6)
         └── 魔数替换: 7z → GSVP

Step 5 ── 下载
         ├── 文件名: gsv-package-xxx.gsvp
         └── 浏览器下载

Step 6 ── 回调父组件
         ├── 传递元数据
         ├── 自动添加到包列表
         └── 关闭弹窗
```

---

## 四、载入整合包流程

### 4.1 操作入口

GSV 模型下 → 顶部配置栏 → `添加整合包` 按钮 → 选择 .gsvp 文件

### 4.2 搜索路径

页面顶部显示：
```
整合包路径: /path/to/gpt-sovits/GSV/packages
```

### 4.3 载入流程（API 后端处理）

```
用户选择 .gsvp 文件
  ↓
前端 POST /packages/load { path: "xxx.gsvp" }
  ↓
后端处理:
  ├── 1. 校验路径合法性
  ├── 2. 修改扩展名: .gsvp → .7z
  ├── 3. 还原魔数: GSVP → 7z (前 6 字节)
  ├── 4. 7z 解压 (LZMA)
  ├── 5. 解析数据段
  │     ├── config.json
  │     ├── models/{gpt}.ckpt
  │     ├── models/{sovits}.pth
  │     └── reference/{audio}.wav
  ├── 6. 以压缩包名创建文件夹
  └── 7. 放入整合包目录
  ↓
返回 { success, name, path }
  ↓
前端刷新包列表
```

### 4.4 包列表自动发现

页面初始化时调用 `GET /packages/search`：

```
扫描整合包目录下每个子文件夹
  → 检查是否存在 config.json
  → 读取并解析 config.json
  → 提取 name, refLang, modelVersion, cutMethod
  → 返回所有 PackageEntry
```

---

## 五、整合包卡片

每个已载入的整合包显示为一条水平卡片：

```
📂 可莉_ZH    参考语种: 中文  模型版本: V4    [使用中]  使用该模型  下载  删除
```

| 元素 | 说明 |
|------|------|
| 图标 | 📂 `FolderOpenOutlined` |
| 名称 | monospace, 12px, 600w, 溢出省略 |
| 属性 | 参考语种、模型版本 |
| 使用中 | 绿色标签，仅当前激活显示 |
| 使用该模型 | 点击设置 activePkg（已使用时显示"正在使用该模型"） |
| 下载 | 调用 API 将 .gsvp 复制到下载目录 |
| 删除 | 从列表中移除 |

---

## 六、API 端点

| 端点 | 方法 | 请求 | 返回 |
|------|------|------|------|
| `/packages/path` | GET | — | `{ path: string }` |
| `/packages/search` | GET | — | `PackageEntry[]` |
| `/packages/load` | POST | `{ path: string }` | `{ success, name, path }` |
| `/packages/download` | POST | `{ path: string }` | `{ success, dest }` |

### PackageEntry 结构

```typescript
interface PackageEntry {
  name: string;           // 整合包名称（文件夹名）
  path: string;           // 完整路径
  configPath: string;     // config.json 路径
  refLang: string;        // 参考语种
  modelVersion: string;   // 模型版本
  cutMethod: string;      // 切句方式
}
```

---

## 七、关键技术依赖

| 库 | 用途 | 版本 |
|-----|------|------|
| `lzma` | 浏览器端 LZMA 压缩/解压 | ^1.x |
| `spark-md5` | 浏览器端 MD5 哈希 | ^3.x |
| `antd` | UI 组件 | ^5.x |

---

## 八、核心文件清单

| 文件 | 职责 |
|------|------|
| `src/pages/GsBasicConfig.tsx` | 创建整合包表单 + 前端压缩流程 |
| `src/pages/TtsMainPage.tsx` (GsConfigPanel) | 配置栏 + 包列表 + API 调用 |
| `src/utils/gsvPackage.ts` | MD5、config.json、LZMA 压缩、魔数操作 |
| `src/api/gptSoVits.ts` | 整合包 API 定义 |
| `docs/gsv-package-spec.md` | 整合包规范文档 |

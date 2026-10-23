# P.A.L.M 模块管理 API 文档

> 基于 MODULE_PACKAGE_SPEC.md 规范实现的模块全生命周期管理 RESTful API
>
> **Base URL**: `http://127.0.0.1:9090`
>
> **Swagger UI**: `http://127.0.0.1:9090/docs`

---

## 目录

1. [系统概览](#1-系统概览)
2. [配置查询](#2-配置查询)
3. [包管理](#3-包管理)
4. [模块状态查询](#4-模块状态查询)
5. [完整性检测](#5-完整性检测)
6. [模块上传验证](#6-模块上传验证)
7. [模块安装](#7-模块安装)
8. [模块卸载](#8-模块卸载)
9. [模块生命周期控制](#9-模块生命周期控制)

---

## 1. 系统概览

### GET /

健康检查端点。

**Response `200`:**

```json
{
  "status": "ok",
  "service": "palm-module-manager",
  "version": "1.0.0"
}
```

---

## 2. 配置查询

### GET /api/config

获取系统路径配置。

**Response `200`:**

```json
{
  "modules_dir": "D:\\Desktop\\Codebuddy\\runtime\\modules",
  "packages_dir": "D:\\Desktop\\Codebuddy\\runtime\\packages"
}
```

---

## 3. 包管理

### GET /api/packages

列出 `packages/` 目录下所有待安装的 `.7z` 包文件。

**Response `200`:**

```json
{
  "packages": [
    {
      "filename": "palm-backend-0.3.0.7z",
      "size": 9239,
      "modified": 1718726400.0
    }
  ]
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `filename` | string | 包文件名 |
| `size` | int | 文件大小（字节） |
| `modified` | float | 最后修改时间（Unix 时间戳） |

---

### DELETE /api/packages/{filename}

删除 `packages/` 目录下指定的 `.7z` 包文件。

**Path Parameters:**

| 参数 | 类型 | 说明 |
|------|------|------|
| `filename` | string | 要删除的包文件名 |

**Response `200`:**

```json
{
  "success": true,
  "message": "Package 'palm-backend-0.3.0.7z' deleted"
}
```

**Response `404`:**

```json
{
  "detail": "Package 'xxx' not found"
}
```

---

## 4. 模块状态查询

### GET /api/modules

列出所有已安装模块及其运行状态（含汇总统计）。

**Response `200`:**

```json
{
  "modules": [
    {
      "name": "palm-backend",
      "version": "0.3.0",
      "type": "backend",
      "description": "P.A.L.M 系统性能监控 API",
      "status": "running",
      "pid": 12345,
      "port": 8080,
      "startedAt": "2026-06-18T22:00:00",
      "error": "",
      "path": "D:\\Desktop\\Codebuddy\\modules\\palm-backend-v0.3.0"
    }
  ],
  "summary": {
    "total": 1,
    "running": 1,
    "stopped": 0
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | 模块名 |
| `version` | string | 语义化版本 |
| `type` | string | 模块类型（backend/frontend/service/tool） |
| `description` | string | 模块描述 |
| `status` | string | 运行状态：`running` / `stopped` / `error` |
| `pid` | int\|null | 进程 ID（运行中时有值） |
| `port` | int\|null | 服务端口 |
| `startedAt` | string\|null | 启动时间（ISO 8601） |
| `error` | string | 错误信息 |
| `path` | string | 模块在磁盘上的绝对路径 |

### GET /api/modules/with-status

列出所有已安装模块，并附带完整性检测状态（未安装/已安装/损坏）。

**Response `200`:**

```json
{
  "modules": [
    {
      "name": "palm-backend",
      "version": "0.3.0",
      "type": "backend",
      "description": "P.A.L.M 系统性能监控 API",
      "status": "已安装",
      "integrity": {
        "status": "valid",
        "expected": "abc123...",
        "actual": "abc123..."
      },
      "port": 8080,
      "path": "D:\\Desktop\\Codebuddy\\runtime\\modules\\palm-backend-v0.3.0",
      "running": true
    }
  ]
}
```

### GET /api/modules/integrity

全量运行所有已安装模块的完整性检测（SHA-256）。

**Response `200`:**

```json
{
  "palm-backend": {
    "status": "valid",
    "expected": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "actual": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
  }
}
```

### GET /api/module/{name}

获取单个模块的完整详情（含原始 `MANIFEST.json`）。

**Response `200`:**

```json
{
  "name": "palm-backend",
  "version": "0.3.0",
  "type": "backend",
  "description": "P.A.L.M 系统性能监控 API",
  "status": "running",
  "pid": 12345,
  "port": 8080,
  "startedAt": "2026-06-18T22:00:00",
  "error": "",
  "path": "D:\\Desktop\\Codebuddy\\modules\\palm-backend-v0.3.0",
  "manifest": {
    "module": "palm-backend",
    "version": "0.3.0",
    "type": "backend",
    "description": "P.A.L.M 系统性能监控 API",
    "entry": "server.py",
    "config": { "port": 8080 },
    ...
  }
}
```

**Error `404`:**

```json
{
  "detail": "Module 'xxx' not found"
}
```

---

## 5. 完整性检测

完整性检测通过计算模块目录的 SHA-256 哈希值与安装时记录的值比对，判断模块文件是否被篡改。

### 检测结果状态

| 状态 | 说明 |
|------|------|
| `valid` | 哈希值匹配，模块完整 |
| `invalid` | 哈希值不匹配，模块可能被修改 |
| `unknown` | 无安装记录，无法检测（新安装模块尚未计算） |
| `error` | 检测过程出错 |

---

## 6. 模块上传验证

### POST /api/module/validate

上传并验证一个 `.7z` 模块包，不实际安装。

通过 `multipart/form-data` 上传文件。

**Request:** `multipart/form-data` 格式，字段名为 `file`，值为 `.7z` 文件。

**Response `200`（验证通过）:**

```json
{
  "valid": true,
  "module": "my-module",
  "version": "1.0.0",
  "description": "我的模块",
  "entry": "server.py",
  "port": 3000
}
```

**Response `200`（验证失败）:**

```json
{
  "valid": false,
  "error": "MANIFEST validation failed",
  "details": ["Missing required field: 'entry'"]
}
```

---

## 7. 模块安装

### POST /api/module/install

安装模块。执行 6 步链路：

```
解压 → 验证 MANIFEST → 校验 → 检查依赖 → postInstall → 注册
```

任一环节失败时自动回滚，清理已产生的脏文件。

**Request Body:**

```json
{
  "filename": "palm-backend-0.3.0.7z"
}
```

**Response `200`（成功）:**

```json
{
  "success": true,
  "module": {
    "name": "palm-backend",
    "version": "0.3.0",
    "type": "backend",
    "description": "P.A.L.M 系统性能监控 API",
    "path": "D:\\Desktop\\Codebuddy\\modules\\palm-backend-v0.3.0",
    "port": 8080,
    "status": "stopped"
  }
}
```

**Response `400`（失败）:**

```json
{
  "detail": {
    "success": false,
    "error": "MANIFEST validation failed",
    "details": ["Missing or empty required field: 'module'"]
  }
}
```

### 安装前置条件

| 条件 | 说明 |
|------|------|
| 文件格式 | 仅支持 `.7z` 格式 |
| 包位置 | 必须位于 `packages/` 目录下 |
| MANIFEST | 必须包含 5 个必需字段：`module`, `version`, `type`, `description`, `entry` |
| 版本号 | 必须符合 semver 规范（`X.Y.Z`） |
| entry | 指向的文件必须在包内存在 |
| 不重复 | 同名模块不可重复安装 |

### 安全机制

- **Zip Slip 防护**：解压后逐文件校验路径是否在目标目录内，发现穿越立即回滚
- **原子回滚**：任何步骤失败，自动删除已创建的临时文件和目录
- **依赖警告**：读取 `dependencies` 字段时输出 deprecate 日志（当前版本不做严格隔离）

---

## 8. 模块卸载

### POST /api/module/uninstall

卸载模块。执行流程：

```
停止运行 → preUninstall 钩子 → 清理目录 → 移除注册信息
```

**Request Body:**

```json
{
  "name": "palm-backend"
}
```

**Response `200`:**

```json
{
  "success": true,
  "message": "Module 'palm-backend' uninstalled"
}
```

**Response `400`:**

```json
{
  "detail": {
    "success": false,
    "error": "Module 'xxx' not found"
  }
}
```

---

## 9. 模块生命周期控制

### POST /api/module/start

启动指定模块。根据 `MANIFEST.json` 中的 `entry` 字段类型自动选择启动方式：
- `.py` → Python 子进程
- `.bat`/`.cmd` → shell 子进程
- `.js`/`.mjs` → Node.js 子进程
- 其他 → 直接执行

**Request Body:**

```json
{
  "name": "palm-backend"
}
```

**Response `200`:**

```json
{
  "success": true,
  "module": "palm-backend",
  "pid": 12345,
  "entry": "server.py"
}
```

### POST /api/module/stop

停止指定模块。通过 `taskkill /F /T /PID` 强制终止进程树。

**Request Body:**

```json
{
  "name": "palm-backend"
}
```

**Response `200`:**

```json
{
  "success": true,
  "message": "Module 'palm-backend' stopped"
}
```

### POST /api/module/start-all

启动所有已安装的模块（按字母顺序，模块间 0.5s 缓冲）。

**Response `200`:**

```json
{
  "success": true,
  "results": [
    { "module": "palm-backend", "success": true, "pid": 12345 }
  ]
}
```

### POST /api/module/stop-all

停止所有正在运行的模块。

**Response `200`:**

```json
{
  "success": true,
  "results": [
    { "module": "palm-backend", "success": true }
  ]
}
```

---

## 附录：一键启动流程

`启动.bat` → `launcher.py` 执行以下流程：

```
┌──────────────────────────────────────────────────────┐
│ 1. 启动模块管理 API 服务 (uvicorn, 端口 9090)         │
│    ↓                                                 │
│ 2. 扫描 modules/ 目录，读取所有 MANIFEST.json         │
│    ↓                                                 │
│ 3. 异步启动每个模块（按 entry 类型执行子进程）          │
│    ↓                                                 │
│ 4. 等待所有模块完成初始化（给每个模块 5 秒）            │
│    ↓                                                 │
│ 5. 启动 Vite 前端开发服务器 (端口 43210)               │
│    ↓                                                 │
│ 6. 打开浏览器 → 自动关闭启动脚本窗口                    │
└──────────────────────────────────────────────────────┘
```

## 附录：错误码速查

| HTTP 状态码 | 业务含义 | 说明 |
|-------------|----------|------|
| 200 | 成功 | 操作正常完成 |
| 400 | 业务错误 | 模块未找到、校验失败、安装失败等（详见 `detail` 字段） |
| 404 | 资源不存在 | 指定模块未安装 |
| 500 | 服务器错误 | 未捕获的内部异常 |

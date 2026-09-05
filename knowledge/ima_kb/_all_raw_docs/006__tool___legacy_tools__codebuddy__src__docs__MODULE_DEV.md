# 模块开发指南

> 本文档说明如何创建一个 P.A.L.M 可安装的功能模块包。

---

## 1. 模块包格式

P.A.L.M 的模块以 `.7z` 压缩包的形式分发和安装。一个合法的模块包必须包含：

```
<module-name>-v<semver>/
├── MANIFEST.json          # [必需] 模块元数据清单
├── <entry-file>           # [必需] 模块入口文件
├── scripts/               # [可选] 生命周期脚本
│   ├── start.bat          # 启动入口（可替代 entry）
│   ├── stop.bat           # 停止入口
│   └── install.bat        # 安装后钩子
├── config/                # [可选] 默认配置
└── README.md              # [推荐] 模块说明文档
```

**打包命令：**

```bash
# 确保包内目录结构正确（包内必须有 <name>-v<version>/ 前缀目录）
7z a -mx=9 my-module-v1.0.0.7z my-module-v1.0.0/
```

> `-mx=9` 启用 LZMA2 极限压缩模式

---

## 2. MANIFEST.json 规范

### 2.1 必需字段

```json
{
  "module": "my-module",
  "version": "1.0.0",
  "type": "backend",
  "description": "我的模块",
  "entry": "server.py"
}
```

| 字段 | 类型 | 说明 | 约束 |
|---|---|---|---|
| `module` | string | 模块名称 | 字母数字+连字符，全局唯一 |
| `version` | string | 语义化版本号 | 符合 semver 规范（`X.Y.Z`） |
| `type` | string | 模块类型 | 可选值：`backend`, `frontend`, `service`, `tool` |
| `description` | string | 简短描述 | 建议 20 字以内 |
| `entry` | string | 入口文件 | 相对于包内模块目录的路径，必须在包内实际存在 |

### 2.2 可选字段

```json
{
  "author": "开发者名",
  "dependencies": {
    "python": ">=3.10",
    "node": ">=18"
  },
  "config": {
    "port": 8080,
    "debug": false
  },
  "deploy": {
    "port": 8080,
    "env": {
      "MY_VAR": "value"
    }
  }
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `author` | string | 模块作者 |
| `dependencies` | object | 运行时依赖声明（当前为信息性，不强制执行） |
| `config` | object | 模块默认配置 |
| `deploy` | object | 部署配置 |
| `deploy.port` | number | 模块占用的端口号（用于去重校验） |
| `deploy.env` | object | 启动时注入的环境变量 |

### 2.3 完整示例

```json
{
  "module": "my-module",
  "version": "1.0.0",
  "type": "backend",
  "description": "我的功能模块",
  "author": "developer",
  "entry": "server.py",
  "dependencies": {
    "python": ">=3.10"
  },
  "config": {
    "port": 8080,
    "debug": false
  },
  "deploy": {
    "port": 8080,
    "env": {}
  }
}
```

---

## 3. 模块类型说明

| 类型 | 说明 | entry 示例 |
|---|---|---|
| `backend` | Python 后端服务，使用 uvicorn/FastAPI | `server.py` |
| `frontend` | 前端应用，在浏览器中运行 | 不常用（前端直接在 P.A.L.M 中实现） |
| `service` | 后台服务进程 | `service.py` / `start.bat` |
| `tool` | 命令行工具或脚本 | `tool.py` / `tool.bat` |

---

## 4. 入口文件自动检测

模块管理器会根据 `entry` 文件扩展名自动选择子进程启动方式：

| 扩展名 | 启动方式 |
|---|---|
| `.py` | `python <entry>` |
| `.bat` / `.cmd` | `cmd /c <entry>` |
| `.js` / `.mjs` | `node <entry>` |
| 其他 | 直接执行（需要可执行权限） |

---

## 5. 生命周期脚本（可选）

### 5.1 scripts/start.bat

如果提供了 `start.bat`，它会替代 `entry` 字段成为实际的启动入口。适用于需要复杂启动前置条件的模块。

### 5.2 scripts/stop.bat

如果提供了 `stop.bat`，`/api/module/stop` 会先执行此脚本，再执行 `taskkill`。适用于需要优雅退出的模块（保存状态、关闭连接等）。

### 5.3 scripts/install.bat

安装后钩子脚本，在模块文件移动完成后由后台线程异步执行。适用于：
- 安装 Python 依赖

  ```bat
  cd /d "%~dp0.."
  pip install -r requirements.txt
  ```

- 初始化数据目录
- 编译资源文件

---

## 6. 完整模块开发示例

### 6.1 创建目录结构

```
my-service-v1.0.0/
├── MANIFEST.json
├── server.py
├── requirements.txt
├── scripts/
│   ├── start.bat
│   └── stop.bat
└── README.md
```

### 6.2 MANIFEST.json

```json
{
  "module": "my-service",
  "version": "1.0.0",
  "type": "service",
  "description": "示例服务模块",
  "author": "developer",
  "entry": "server.py",
  "dependencies": {
    "python": ">=3.10"
  },
  "deploy": {
    "port": 3000,
    "env": {
      "LOG_LEVEL": "INFO"
    }
  }
}
```

### 6.3 server.py

```python
import os
from fastapi import FastAPI
import uvicorn

app = FastAPI(title="My Service")

@app.get("/")
def root():
    return {"status": "ok", "service": "my-service"}

if __name__ == "__main__":
    port = int(os.getenv("PORT", "3000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
```

### 6.4 scripts/install.bat

```bat
@echo off
cd /d "%~dp0.."
pip install -r requirements.txt
```

### 6.5 打包

```bash
7z a -mx=9 my-service-v1.0.0.7z my-service-v1.0.0/
```

### 6.6 安装

将 `.7z` 文件放入 `packages/` 目录，然后通过 P.A.L.M 前端模块管理页面上传并安装，或调用 API：

```bash
curl -X POST http://127.0.0.1:9090/api/module/install \
  -H "Content-Type: application/json" \
  -d '{"filename": "my-service-v1.0.0.7z"}'
```

---

## 7. 最佳实践

- **模块命名** — 使用小写字母和连字符，如 `my-awesome-module`
- **端口管理** — 在 `deploy.port` 中声明端口号，避免端口冲突
- **优雅退出** — 提供 `stop.bat` 脚本处理清理逻辑
- **依赖安装** — 提供 `install.bat` 自动化安装 Python 依赖
- **单进程** — 一个模块只启动一个主进程，通过子进程管理更复杂的情况
- **日志输出** — 推荐将日志写入模块目录下的 `logs/` 文件夹
- **最小化包体** — 打包时排除 `__pycache__`、`.git`、`node_modules` 等目录

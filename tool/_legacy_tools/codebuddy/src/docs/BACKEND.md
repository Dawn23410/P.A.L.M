# 后端服务

> 本文档描述 P.A.L.M 项目的所有后端服务及其职责。

---

## 1. 服务总览

| 服务 | 端口 | 技术栈 | 职责 |
|---|---|---|---|
| 模块管理 API | 9090 | FastAPI + py7zr | 模块全生命周期管理 |
| palm-backend | 8080 | FastAPI + psutil + pynvml | 系统性能监控 |
| GSV Runtime Server | 5000 | FastAPI + 文件系统 | 整合包管理、文件操作 |
| GPT-SoVITS TTS | 9880 | GPT-SoVITS API | 语音合成推理 |
| Qwen3-TTS API | 8000 | FastAPI + Qwen3 | 语音合成推理 |

---

## 2. 模块管理 API

**位置**：`Codebuddy/manager/`

**文件**：
- `app.py` — FastAPI 应用入口，路由定义
- `module_manager.py` — 模块管理器核心类（单例）

### 2.1 核心类：ModuleManager

```python
class ModuleManager:
    _instance = None  # 单例

    def __init__(self):
        self.modules_dir: Path      # = <runtime>/modules/
        self.packages_dir: Path     # = <runtime>/packages/
        self.modules: dict[str, ModuleState]  # 模块状态注册表
        self.lock: asyncio.Lock     # 并发锁

    # --- 包管理 ---
    def list_packages(self) -> list[dict]
    def delete_package(self, filename: str) -> bool

    # --- 模块状态查询 ---
    def list_modules(self) -> list[ModuleState]
    def get_module(self, name: str) -> ModuleState | None

    # --- 完整性检测 ---
    def check_integrity(self, module_path: Path) -> dict
    def check_all_integrity(self) -> dict[str, dict]

    # --- 安装卸载 ---
    async def validate_package(self, filename: str) -> dict
    async def install(self, filename: str) -> dict
    async def uninstall(self, name: str) -> dict

    # --- 生命周期控制 ---
    async def start(self, name: str) -> dict
    async def stop(self, name: str) -> dict
    async def start_all(self) -> list[dict]
    async def stop_all(self) -> list[dict]
```

### 2.2 数据类

```python
@dataclass
class ModuleInfo:
    module: str           # 模块名
    version: str          # 版本号
    type: str             # backend/frontend/service/tool
    description: str      # 描述
    author: str           # 作者
    entry: str            # 入口文件路径
    dependencies: dict    # 依赖声明
    config: dict          # 默认配置
    deploy: dict          # 部署配置

@dataclass
class ModuleState:
    name: str             # 模块名
    version: str          # 版本号
    path: str             # 磁盘路径
    manifest: dict        # 原始 MANIFEST 内容
    status: str           # running/stopped/error
    pid: int | None       # 进程 ID
    port: int | None      # 服务端口
    started_at: str | None  # 启动时间
    error: str            # 错误信息
```

### 2.3 路由

参见 [API 文档](API.md)。

### 2.4 安装链路详解

```
POST /api/module/install
  └─ ModuleManager.install()
      ├─ [1] py7zr.SevenZipFile.extract() 解压到临时目录
      │    ├─ filter: 防 Zip Slip（检查路径穿越）
      │    └─ 失败 → 删除 tempdir → return error
      ├─ [2] parse_manifest() 解析 MANIFEST.json
      │    └─ 校验 5 个必填字段 + semver
      ├─ [3] 检查 modules_dir 中是否已存在同名模块
      ├─ [4] stat(entry) 校验入口文件存在
      ├─ [5] shutil.move() 移到 modules/<name>-v<version>/
      ├─ [6] 异步线程执行 postInstall 钩子
      └─ [7] 计算 SHA-256 → 注册 ModuleState
```

---

## 3. palm-backend 性能监控

**位置**：`Codebuddy/runtime/modules/palm-backend/`

**文件**：
- `server.py` — FastAPI 性能监控服务（端口 8080）
- `monitor.py` — CLI 终端版本监视器（调试用）

### 3.1 路由

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 健康检查 |
| GET | `/api/performance` | 全量性能快照 |
| GET | `/api/metrics` | 全量性能快照（别名） |
| GET | `/api/modules` | 预定义模块状态列表 |

### 3.2 性能数据采集

```python
def get_performance_snapshot() -> dict:
    return {
        "cpu": {
            "model": str,           # CPU 型号
            "baseFreq": float,      # 基础频率 (GHz)
            "currentFreq": float,   # 当前频率 (GHz)
            "usage": float,         # 使用率 (%)
            "temperature": float | None  # CPU 温度 (°C)
        },
        "memory": {
            "speed": float | None,  # 内存频率 (MHz)
            "total": float,         # 总内存 (GB)
            "available": float,     # 可用内存 (GB)
            "usage": float          # 使用率 (%)
        },
        "gpus": [{
            "model": str,           # GPU 型号
            "usage": float          # 使用率 (%)
        }],
        "network": {
            "uploadSpeed": float,   # 上传速率 (Bytes/s)
            "downloadSpeed": float  # 下载速率 (Bytes/s)
        },
        "disks": [{
            "mount": str,           # 挂载点
            "total": int,           # 总容量 (Bytes)
            "used": int             # 已用 (Bytes)
        }]
    }
```

### 3.3 技术依赖

| 库 | 用途 |
|---|---|
| `psutil` | CPU/内存/磁盘/网络/进程信息 |
| `py-cpuinfo` | CPU 型号和特性 |
| `pynvml` | NVIDIA GPU 信息 |

### 3.4 缓存策略

- 数据 2 秒缓存，轮询请求不重复采集
- 使用 `time.monotonic()` 控制刷新间隔
- GPU 信息仅在 `pynvml` 可用时采集

---

## 4. GSV Runtime Server

**位置**：`Codebuddy/runtime/server.py`

**端口**：5000

**职责**：提供 GPT-SoVITS 整合包（GSVP）的后端文件操作接口。

### 4.1 路由

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 健康检查 |
| POST | `/packages/upload` | 上传 GSVP 包 |
| GET | `/packages/search` | 扫描已存在的整合包 |
| POST | `/packages/load` | 载入整合包（解压到运行时） |
| POST | `/packages/create` | 创建整合包（上传文件模式） |
| POST | `/packages/create-from-paths` | 创建整合包（路径模式） |
| GET | `/packages/progress` | 创建进度轮询 |
| POST | `/files/scan-mates` | 扫描配套文件 |
| POST | `/files/read` | 从后端读取文件内容 |

### 4.2 整合包格式

GSVP（GPT-SoVITS Package）是一种自定义二进制包格式：

```
魔数: 0x475356500001 ("GSVP\0\1")
结构:
  [魔数 6B] [版本 2B] [头部长度 4B] [XOR 密钥 2B]
  [填充 8B] [条目数 4B]
  [条目...]  ← 每个条目: [被 XOR 混淆的文件名] [文件内容]
```

参见 [GSVP 包规范](gsv-package-spec.md)。

---

## 5. GPT-SoVITS TTS

**端口**：9880（语音合成）

**路由**：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/status` | 健康检查 |
| POST | `/tts` | 文本转语音合成 |
| POST | `/voice-clone` | 语音克隆 |
| POST | `/models/set` | 切换模型 |

---

## 6. Qwen3-TTS API

**端口**：8000

**路由**：

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/health` | 健康检查 |
| GET | `/api/v1/models` | 列出可用模型 |
| GET | `/api/v1/models/current` | 当前加载的模型 |
| POST | `/api/v1/models/load` | 加载模型 |
| POST | `/api/v1/models/download` | 下载模型 |
| POST | `/api/v1/custom-voice/generate` | 语音合成 → 返回 WAV Blob |
| POST | `/api/v1/voice-design/generate` | 音色设计 → 返回 WAV Blob |
| POST | `/api/v1/voice-clone/generate` | 语音克隆 → 返回 WAV Blob |

---

## 7. 一键启动引擎

**文件**：`Codebuddy/launcher.py`

### 7.1 启动流程

```
启动.bat
  └─ python launcher.py
       ├─ [1/5] 启动 GSV Runtime Server (端口 5000)
       │         runtime/server.py → subprocess.Popen
       │         └─ 轮询 GET :5000/ 直到返回 200
       │
       ├─ [2/5] 启动模块管理 API (端口 9090)
       │         uvicorn manager.app:app → subprocess.Popen
       │         └─ 轮询 GET :9090/ 直到返回 200
       │
       ├─ [3/5] 扫描 modules/ 目录, 读取 MANIFEST.json
       │         构建已安装模块列表
       │
       ├─ [4/5] 启动所有已安装模块 (子进程)
       │         按字母顺序启动, 模块间 0.5s 缓冲
       │         每个模块等待最多 5s 初始化
       │
       └─ [5/5] 启动 Vite 前端开发服务器 (端口 43210)
                  npm run dev → subprocess.Popen
                  └─ 等待 3s → 打开浏览器
```

### 7.2 端口冲突处理

如果指定端口已被占用，启动器会递增端口号并重试，最多尝试 10 次。

### 7.3 终止清理

使用 `kill_python.cmd` 可强制终止所有 Python 进程：

```batch
taskkill /F /IM python.exe
```

---

## 8. 后端配置速查

### 端口配置文件位置

端口配置分散在各服务的启动参数中，没有统一的配置文件。如需修改：

| 服务 | 修改位置 |
|---|---|
| 模块管理 (9090) | `manager/app.py` 中 `uvicorn.run()` 的 `port` 参数 |
| palm-backend (8080) | `runtime/modules/palm-backend/server.py` 中 `uvicorn.run()` 的 `port` 参数 |
| Runtime (5000) | `runtime/server.py` 或 `runtime/server_fastapi.py` 中端口参数 |
| Vite (43210) | `vite.config.ts` 中 `server.port` |

### log 输出

- 模块管理后端：`print()` 输出到终端
- launcher.py：带色彩的 `print()` 输出
- 各服务：Python print / uvicorn 日志

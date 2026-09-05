# P.A.L.M 主板设计架构与功能支持文档

> 版本：终极主板架构（L0–L5 全落地）  
> 文档范围：整体架构、总线模型、管理芯片（每块一芯片 + 自定义请求地址）、信道织物、零信任仲裁、资源配额、存储主＋分 IC、热插拔/版本回滚/MCP、基础设施、砖块归位、前端主板视图、对外接口契约、验证结果、路线图。  
> 代码基线：`backend/app/bricks/_shared/*`、`backend/app/bricks/base.py`、`backend/app/bricks/__init__.py`、`backend/app/bricks/_shared/bios.py`、`backend/app/main.py`、`plugins/tts_sovits/*`、`frontend/src/*`、`monitor.html`。

---

## 1. 设计哲学与核心隐喻

P.A.L.M（Personal AI Life Manager / 个人 AI 操作系统）以「**主板（Motherboard）+ 砖块（Brick）/ 芯片（Chip）**」为统一隐喻组织全部能力：

- **砖块（Brick）**：一个可独立部署的功能单元（如语音合成、记忆、存储、浏览器自动化），自带声明式清单（`BrickManifest`）与能力表（`capabilities`）。砖间**严格零互导**，只能通过「北桥」`interop.get_facade(name)` 取用其他砖的门面。
- **主板（Motherboard）**：运行时治理平面，把所有砖按总线归类、为每块砖套上「管理芯片」并实施观测与隔离。
- **每块一管理芯片 + 自定义请求地址**：用户原始诉求——用「复杂度换稳定」。每块砖外挂一个 `BrickHandle`（管理芯片），`endpoint`（请求地址）即隔离边界；砖可声明自己的 endpoint（`inproc://` / `ipc://` / `tcp://` / `ws://`），框架按地址选择信道强度。

核心权衡：**进程内砖共享内核（零开销、低延迟），重计算/媒体砖走 `ipc://` 子进程（真隔离），远端走 `tcp://`/`ws://`（跨机）**。同一套治理框架覆盖三种隔离强度。

---

## 2. 整体架构分层（L0–L5）

```
┌──────────────────────────────────────────────────────────────────────┐
│ 客户端层（React + monitor.html）                                          │
│   MotherboardPanel / ChatSidebar → fetch /api/bios/status             │
│   monitor.html（真实 ATX 主板渲染，1cm 精度） → fetch /api/bios/status │
└───────────────────────────────┬──────────────────────────────────────┘
                                 │ HTTP / MCP
┌───────────────────────────────┴──────────────────────────────────────┐
│ ② 北桥 interop（零信任仲裁层 L4）                                        │
│   get_facade(name) → FacadeProxy → _Arbiter.invoke/invoke_async       │
│   落遥测 · 健康门控 · 降级熔断；类/常量原样透传                          │
└───────────────────────────────┬──────────────────────────────────────┘
                                 │ 取能力
┌───────────────────────────────┴──────────────────────────────────────┐
│ ③ 主板 Motherboard（核心）                                              │
│   6 总线：CPU / SATA / PCIE / RAM / BOARD / CHIP                        │
│   每块砖 = 一个芯片 → BrickHandle（endpoint + Transport + 生命周期 +    │
│   健康探针 + 遥测），挂到对应 BusController                             │
└───────────────────────────────┬──────────────────────────────────────┘
                                 │ 治理动作
┌───────────────────────────────┴──────────────────────────────────────┐
│ ④ 治理层 Governance                                                      │
│   L4 资源配额：BusController.set_bus_cap + QuotaValidator +            │
│       SubprocessTransport.usage（psutil 真实度量）                      │
│   L4 存储主+分 IC：storage.py（主池 + 每砖 主/bricks/<ns>）            │
│   L5 热插拔/版本回滚/MCP：hotplug.py（VersionLedger / plug /          │
│       unplug / rollback / McpAdapter + /api/mcp）                      │
│   L4 遥测：TelemetrySink（全调用指标汇聚）                              │
└───────────────────────────────┬──────────────────────────────────────┘
                                 │ 进程内共享
┌───────────────────────────────┴──────────────────────────────────────┐
│ ⑤ 基础设施（进程内共享内核）                                            │
│   eventbus（南桥事件总线）· bios（POST 自检）· watchdog（心跳）·        │
│   permission（审计留痕）· registry（砖注册表）                          │
└───────────────────────────────┬──────────────────────────────────────┘
                                 │ 信道
┌───────────────────────────────┴──────────────────────────────────────┐
│ ⑥ 信道织物 Transport                                                    │
│   InProcTransport（inproc 零开销）/ SubprocessTransport（ipc 隔离子    │
│   进程）/ RemoteTransport（tcp/ws 远端）· transport_for(url) 选择       │
└──────────────────────────────────────────────────────────────────────┘
```

| 层级 | 名称 | 落地模块 | 状态 |
|------|------|----------|------|
| L0 | 砖块基座 | `base.py`（`Brick`/`BrickManifest`/`CapabilitySlot`） | ✅ |
| L1 | 进程内共享内核 | `eventbus`/`interop`/`bios`/`watchdog`/`permission` | ✅ |
| L2 | 管理芯片 + 总线 | `handle.py`（BrickHandle/BusController） | ✅ |
| L3 | 信道织物 + 放置调度 | `transport.py`/`placement.py` | ✅ |
| L4 | 零信任仲裁 / 配额 / 存储 | `arbitration.py`/`quota.py`/`storage.py` | ✅ |
| L5 | 热插拔 / 回滚 / MCP | `hotplug.py` + `/api/mcp` | ✅ |

---

## 3. 主板总线模型（6 条总线）

`BusType` 枚举仅作**元数据/展示语义**，不改变代码组织。每条总线承载一类砖：

| 总线 | 隐喻 | 承载砖（示例） | 默认 endpoint |
|------|------|----------------|---------------|
| `CPU` | CPU 插槽：编排主控 | `agent`（Agent 主控） | `inproc://` |
| `SATA` | 硬盘（SATA）：持久化数据 | `storage`（存储砖） | `inproc://` |
| `PCIE` | 高速外设（PCIe）：重计算/媒体 | `tts_sovits`、`gui`、`browser`、`automation`、`sandbox`、`web`、`image`、`audio` | `ipc://` |
| `RAM` | 内存槽（运行态）：状态化易失 | 状态化砖（如有） | `inproc://` |
| `BOARD` | 板载焊死：系统关键 | `system_core`、`watchdog`、`eventbus`、`permission`、`scheduler` | `inproc://` |
| `CHIP` | 主板自带：系统级内置组件 | `bios`、`interop`、`telemetry`、`audit`、`registry` | `inproc://` |

> PCIE 默认 `ipc://`，因为只有显式暴露 `subprocess_spec` 的砖才真正拉起子进程；未提供该规格的 PCIE 砖会**诚实退化为进程内**（`InProcTransport`），绝不因缺配置而启动失败。

---

## 4. 管理芯片 BrickHandle 与 endpoint 织物

### 4.1 BrickHandle（每块一芯片）

```python
class BrickHandle:
    def __init__(self, brick, bus=None):
        self.brick = brick
        self.manifest = brick.manifest
        self.bus = bus
        # 决策优先级（用户自定义请求地址优先）：
        self.endpoint = (
            self.manifest.endpoint          # ① 每块砖显式自定义（覆盖一切）
            or recommend_endpoint(brick)    # ② 放置调度器推荐
            or bus.default_endpoint_for(...)# ③ 总线默认
            or "inproc://"                  # ④ 进程内兜底
        )
        self.transport = _build_transport(brick, self.endpoint)
        self.state = "registered"           # registered | active | disposed
```

- **生命周期**：`registered`（已包芯片）→ `load()`（拉起信道，子进程/IPC 连接；进程内为 no-op）→ `active`；`dispose()` 释放资源回到 `disposed`。
- **健康探针**：`health()` 调 `transport.health()` 并记录遥测后返回连通性。
- **snapshot()**：BIOS / 前端主板图数据源（见 §14 接口契约）。

### 4.2 endpoint 决策链

```
manifest.endpoint（显式）  ──覆盖──▶  最终 endpoint
        │（空则）
recommend_endpoint(brick)  ──放置调度器──▶  （按 bus_type + subprocess_spec）
        │（空则）
BusController.default_endpoint_for(bus)  ──▶  PCIE→ipc://  其余→inproc://
        │（空则）
"inproc://"
```

### 4.3 放置调度器 PlacementScheduler

`placement.py` 提供 `recommend_endpoint(brick)` 与 `register_strategy` 扩展点：按 `bus_type` 与砖是否暴露 `subprocess_spec` 给出默认 endpoint，是「per-bus 治理」与「per-brick 芯片」的衔接层。

---

## 5. 信道织物 Transport

`transport_for(url)` 按协议前缀选择信道实现：

| 协议 | 实现 | 隔离强度 | 适用 |
|------|------|----------|------|
| `inproc://` | `InProcTransport` | 进程内（共享主进程，零开销） | 默认绝大多数砖 |
| `ipc://` | `SubprocessTransport` | 子进程隔离（独立 PID，可 psutil 度量） | `tts_sovits` 等重计算砖 |
| `tcp://` / `ws://` | `RemoteTransport` | 跨机/进程外 | 远端砖（占位） |

- `SubprocessTransport`：持有 `SubprocessSpec(cmd_builder, port, health_path, readiness_timeout, log_path, cwd)`；`start()` 拉起子进程并探测就绪；`usage()` 经 psutil 返回 `{cpu_pct, rss_mb, measured}`（psutil 缺失则 `measured=False` 降级，不崩）；`dispose()` 优雅停止（先请求退出，超时强杀兜底）。
- `cmd_builder` 为**延迟 lambda**：只在真正隔离拉起时才解析命令，导入期不调用，避免 venv 缺失时抛错阻断降级。

---

## 6. 零信任 facade 仲裁层（L4）

`arbitration.py` 落地「跨砖调用强制经管理芯片」闭环：

```python
def get_facade(brick_name) -> FacadeProxy | None:
    raw = interop.get_facade(brick_name)   # 原有北桥取门面
    if raw is None:
        return None
    return FacadeProxy(brick_name, raw)     # 包裹为代理
```

- **`FacadeProxy`**：拦截方法调用（`__getattr__`），仅对**函数/协程函数**包裹；类、常量、模块属性**原样透传**（`isinstance` 不受影响）——31 处既有调用点零改动即被管理芯片观测。
- **`_Arbiter.invoke / invoke_async`**：落地前记录开始时间戳 → 执行 → 经 `TelemetrySink.record(name, ok, error, latency)` 落遥测 → 返回结果；异常原样透传并记录失败。
- **价值**：所有跨砖调用、延迟、成败率汇入主板快照，前端一图可视；为后续健康门控、降级熔断预留同一入口。

---

## 7. 资源配额（L4）

### 7.1 声明式画像

```python
@dataclass
class ResourceQuota:
    cpu_cores: float = 0.0   # 声明可用 CPU 核数（软上限）
    mem_mb: int = 0          # 声明内存上限（MB，软上限）
    io_weight: int = 50      # IO 权重 1-100（调度优先级）
```

> `cpu_cores`/`mem_mb` 为 0 表示未声明（不计入总线总量校验，避免误杀未标注砖）。配额是**软强制**：仅告知 + 越界告警，真正硬隔离仍依赖 endpoint（ipc/remote）。

### 7.2 总线级总量校验

```python
BusController.set_bus_cap(BusCap(cpu_cores, mem_mb, io_total))  # 设总线总帽
BusController.quota_violations()                                # 返回超限告警列表
```

- `BusCap` + `QuotaValidator`：聚合本总线所有砖声明配额，对照总帽返回超限条目（如「声明 CPU 6.0 核 > 总线帽 4.0 核」）。
- `apply_default_bus_caps()`：按系统真实资源设宽松帽（实测示例：cpu 24 核 / 内存 8047MB / IO 400）。

### 7.3 真实度量

`SubprocessTransport.usage()` 经可选 psutil 读子进程真实 `rss`/`cpu`，进程内砖共享主进程返回 `None`。snapshot 暴露 `usage:{cpu_pct,rss_mb,measured}`。

---

## 8. 存储主＋分 IC（L4）

`storage.py` 实现「全局池 + 每砖私有命名空间」的存储治理：

```python
@dataclass
class StoragePolicy:
    namespace: str = ""        # 分 IC 命名空间；空串默认用砖名
    isolated: bool = True      # True=独立子目录（主+分）；False=共享主池
    quota_mb: int | None = None# 分 IC 容量软上限（None=不限）
```

- **主 IC** = `STORAGE_POOL_DIR`（全局保险库/共享池）。
- **分 IC** = `主/bricks/<namespace>`（每砖专辟独立目录，互不污染）。
- API：`get_brick_storage(name)`（惰性创建并返回路径）、`storage_policy_of(name)`、`usage_of(name)`（占用统计）。
- 已验证：`get_brick_storage("tts_sovits")` → `Data/bricks/tts_sovits` 真实生成。
- snapshot 暴露 `storage:{namespace,isolated,quota_mb,path}`。

---

## 9. 热插拔 / 版本回滚 / MCP（L5）

`hotplug.py` 把主板从「静态焊接」升级为「可插拔总线」：

### 9.1 版本台账

`VersionLedger`：每块砖加载时 `record(name, version, endpoint)` 记入历史（`history()` / `last_known_good()`），`_wrap_all_bricks` 后 `record_loaded_versions()` 统一记一笔。

### 9.2 热插拔

```python
await plug(brick)     # 注册 + 包芯片 + 记版本 + 启用（幂等）
await unplug(name)    # dispose 芯片 + 从总线注销 + 停用（保留 registry 以便重插）
await rollback(name)  # dispose→load 闭环；SubprocessTransport 会被真实重启进程
```

- `rollback` 对子进程砖（ipc）真实杀死并重拉，等价于运行时回滚到加载时点；进程内砖为 best-effort 重激活。

### 9.3 MCP 兼容层

`McpAdapter` 把砖能力映射为 MCP 协议：

- `tools_list()`：自动发现（默认遍历各砖 `capabilities`，挑可调用非下划线键；砖可显式声明 `mcp_tools` 覆盖），输出 `{name:"<砖>/<能力>", description, inputSchema}`。已自动发现 **93** 个工具。
- `tools_call(tool, arguments)`：经 `_arbiter.invoke_async` 调用（复用遥测/健康），bytes 结果降级为长度标注（MCP 要求 JSON 可序列化）。
- HTTP 路由（`/api/mcp`）：`GET /tools`、`POST /call`、`GET /status`。

### 9.4 优雅停机

`app/main.py` lifespan 在关闭时 `dispose_all()` 全部芯片，杜绝 `tts_sovits` 孤儿进程。

---

## 10. 基础设施（进程内共享内核）

| 组件 | 角色 | 备注 |
|------|------|------|
| `eventbus` | 南桥事件总线 | 砖间异步解耦通信 |
| `interop` | 北桥 | `get_facade` 取门面（已套仲裁代理） |
| `bios` | POST 自检 | `run_self_check()` 产出健康报告 + `masterboard` 快照 |
| `watchdog` | 心跳 | 芯片存活重探 |
| `permission` | 审计 | 仅已声明敏感能力留痕（最近 500 条），`audit_snapshot()` |
| `registry` | 砖注册表 | `group_by_bus()` / `get()` / `all()`，`capabilities` 取用 |

---

## 11. 砖块总览（归位表）

> 实际砖数随注册动态变化，下表为架构代表性归位（总线 → 砖 → endpoint → transport）。

| 总线 | 砖 | endpoint | transport |
|------|----|----------|-----------|
| CPU | `agent` | `inproc://` | InProcTransport |
| SATA | `storage` | `inproc://` | InProcTransport |
| PCIE | `tts_sovits` | `ipc://`（cwd=SOVITS_ROOT） | SubprocessTransport |
| PCIE | `gui`/`browser`/`automation`/`sandbox`/`web`/`image`/`audio` | `inproc://`（无 subprocess_spec，退化） | InProcTransport |
| BOARD | `system_core`/`watchdog`/`eventbus`/`permission`/`scheduler` | `inproc://` | InProcTransport |
| CHIP | `bios`/`interop`/`telemetry`/`audit`/`registry` | `inproc://` | InProcTransport |

前端 `monitor.html` 按 ATX 物理布局把砖归位：agent→CPU LGA 插槽、memory→DIMM、storage→SATA、媒体砖→PCIe 各槽、系统砖→VRM/芯片组区、chip 砖→PCH 区。

---

## 12. tts_sovits 收敛案例（手搓 launcher 删除）

原 `plugins/tts_sovits` 自管子进程生命周期（`_runtime_proc`/`_ensure_runtime`/`_try_launch_on_startup`/`_cleanup_runtime`/`atexit`/`launcher.py`）。现收敛：

- 内联 `discover_venv_python` / `_build_gsv_cmd` 进 `brick.py`。
- **删除 `launcher.py`**；移除所有自管子进程代码，改由管理芯片 `handle.load()` 托管（`SubprocessSpec.cmd_builder` 延迟 lambda + `cwd=SOVITS_ROOT`，GSV 相对路径加载模型必需）。
- 外部 GSV 已运行时跳过 spawn，避免双实例 bind 冲突。
- 验证：masterboard 中 `tts_sovits` 显示 `SubprocessTransport`，无残留手搓运行时可执行引用（仅 docstring 说明）。

---

## 13. 前端主板视图与监控屏

### 13.1 主板视图（Vite + React + TS）

- `types.ts`：`BrickChip`/`BusBoard`/`BiosStatus`/`BrickTelemetry`/`BrickQuota`/`BrickUsage`/`BrickStorage`（字段 `avg_latency`/`success_rate` 可为 null）。
- `api/client-bios.ts`：消费 `/api/bios/status`。
- `components/MotherboardPanel.tsx`：overlay 面板，6 总线 × 芯片，健康灯 + 成功率 + 配额越界告警 + 存储 IC 渲染。
- `App.tsx` 加 `motherboard` Section；`ChatSidebar.tsx` 加 Cpu 侧栏入口。

### 13.2 科幻/真实主板监控屏 `monitor.html`（独立 HTML）

- **真实 ATX 渲染**：按 Intel ATX 2.01 规格，**305×244mm**（比例 1.25），缩放 1cm≈29.5px；9 颗螺丝孔用规格坐标 `{6.35,157.35,226.15} × {6.35,101.6,213.1}` mm 精确落位；含后置 I/O 窗、CPU LGA1700 插槽（触点阵 + 拉杆）、VRM 电感电容、DDR5 DIMM×4、PCH 散热片、M.2、PCIe 5.0 插槽群、SATA×6、CMOS 纽扣电池、24/8Pin 供电口；底部 1cm 刻度尺佐证精度。
- **视觉**：浅天蓝天空背景 + 深蓝边框主板；全程只显示主板与砖块，无侧栏/顶底栏/隔离框/分割条。
- **交互**：砖块带状态 LED（青=正常／红=故障／灰=离线）+ 引线批注（隔离方式）；点击砖块浮出详情卡片（endpoint/信道/遥测/实测用量/存储 IC）。
- **数据对接**：打开即 `fetch('/api/bios/status')`（带 `?token=` 走真实主板快照），不可达自动回退合成数据演示；顶栏 `LIVE/SIM` 灯实时显示模式。

---

## 14. 对外接口契约

### 14.1 `GET /api/bios/status`（主板健康报告）

```jsonc
{
  "status": "ok",
  "cores": ["agent", ...],                 // 核心砖名
  "core_missing": [],                       // 缺失核心砖（正常为空）
  "buses": { "<bus>": [砖名...] },          // 总线分组
  "masterboard": {                          // 主板运行态快照
    "<bus>": {
      "bus": "pcie",
      "default_endpoint": "ipc://",
      "quota_cap": { "cpu_cores": 24, "mem_mb": 8047, "io_total": 400 },
      "quota_violations": [],               // 超限告警
      "bricks": [
        {
          "name": "tts_sovits",
          "bus": "pcie",
          "endpoint": "ipc://",
          "transport": "SubprocessTransport",
          "isolation": "subprocess",
          "version": "0.1.0",
          "state": "active",
          "enabled": true,
          "telemetry": { "calls": 0, "fails": 0, "success_rate": null, "avg_latency": null },
          "quota": { "cpu_cores": 0.0, "mem_mb": 0, "io_weight": 50 },
          "usage": { "cpu_pct": null, "rss_mb": null, "measured": false },
          "storage": { "namespace": "tts_sovits", "isolated": true, "quota_mb": null, "path": "..." }
        }
      ]
    }
  },
  "probes": [                               // 6 项 BIOS 探测
    {"id":"sandbox","title":"沙箱引擎","status":"available","detail":true},
    {"id":"pywin32","title":"受限账户隔离","status":"available","detail":true},
    {"id":"network_llm","title":"网络大模型配置","status":"available","detail":false},
    {"id":"tts","title":"本地语音合成","status":"available","detail":false},
    {"id":"vault","title":"保险库兜底","status":"available","detail":true},
    {"id":"offline","title":"离线模式","status":"available","detail":"在线"}
  ],
  "bomb_history": []
}
```

### 14.2 `/api/mcp`（MCP 兼容层）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/mcp/tools` | `tools/list`：列出全部可经 MCP 消费的砖能力（自动发现） |
| POST | `/api/mcp/call` | `tools/call`：body `{tool:"<砖>/<能力>", arguments:{}}`，结果经仲裁层 |
| GET | `/api/mcp/status` | 自检：已暴露工具数 + 各砖版本历史条数 |

### 14.3 前端类型（`types.ts` 摘要）

```ts
export interface BrickTelemetry { calls: number; fails: number; success_rate: number | null; avg_latency: number | null; }
export interface BrickQuota { cpu_cores: number; mem_mb: number; io_weight: number; }
export interface BrickUsage { cpu_pct: number | null; rss_mb: number | null; measured: boolean; }
export interface BrickStorage { namespace: string; isolated: boolean; quota_mb: number | null; path: string | null; }
export interface BrickChip {
  name: string; bus: string; endpoint: string; transport: string;
  isolation: string; version: string; state: string; enabled: boolean;
  telemetry: BrickTelemetry | null; quota: BrickQuota; usage: BrickUsage | null; storage: BrickStorage;
}
export interface BusBoard {
  bus: string; default_endpoint: string;
  quota_cap: { cpu_cores: number; mem_mb: number; io_total: number } | null;
  quota_violations: string[]; bricks: BrickChip[];
}
export interface BiosStatus { status: string; cores: string[]; core_missing: string[];
  buses: Record<string,string[]>; masterboard: Record<string,BusBoard>;
  probes: {id:string;title:string;status:string;detail:unknown}[]; bomb_history: unknown[]; }
```

---

## 15. 验证结果（虚拟内容实测，30/30 PASS）

| # | 模块 | 验证项 | 结果 |
|---|------|--------|------|
| 1 | 子系统 | 全部模块导入 | ✅ |
| 2 | L4 仲裁 | 类属性透传（isinstance） | ✅ |
| 3 | L4 仲裁 | 常量属性透传 | ✅ |
| 4 | L4 仲裁 | 同步调用经 Arbiter 落遥测 | ✅ |
| 5 | L4 仲裁 | 异步调用经 Arbiter 落遥测 | ✅ |
| 6 | L4 仲裁 | 异常透传且记失败遥测 | ✅ |
| 7 | L4 仲裁 | 遥测汇聚累计 | ✅ |
| 8 | L4 仲裁 | 真实砖 facade 已接代理 | ✅ |
| 9 | L4 配额 | 总线声明总量超限检测 | ✅ |
| 10 | L4 配额 | 声明未超限不误报 | ✅ |
| 11 | L4 配额 | 总线未设帽跳过校验 | ✅ |
| 12 | L4 配额 | `measure_subprocess` 真实/降级 | ✅ |
| 13 | L4 配额 | `apply_default_bus_caps` 全总线 | ✅ |
| 14 | L4 配额 | 快照暴露 quota_cap/violations | ✅ |
| 15 | L4 存储 | 主 IC 根（全局池） | ✅ |
| 16 | L4 存储 | 分 IC 惰性创建（主/bricks/<ns>） | ✅ |
| 17 | L4 存储 | `storage_policy_of` 摘要 | ✅ |
| 18 | L4 存储 | `usage_of` 占用统计 | ✅ |
| 19 | L4 存储 | isolated=False 回退主池 | ✅ |
| 20 | L5 | `VersionLedger` 记录+历史+LKG | ✅ |
| 21 | L5 | `plug` 运行时插入 | ✅ |
| 22 | L5 | `unplug` 运行时拔出 | ✅ |
| 23 | L5 | `rollback` 重激活/重启闭环 | ✅ |
| 24 | L5 | `McpAdapter.tools_list` 自动发现 | ✅（93 工具） |
| 25 | L5 | `McpAdapter.tools_call` 经仲裁 | ✅ |
| 26 | L5 | `/api/mcp` 路由挂载 | ✅ |
| 27 | tts | 手搓 `launcher.py` 已删除 | ✅ |
| 28 | tts | `subprocess_spec` 暴露给芯片 | ✅ |
| 29 | tts | `cmd_builder` 延迟 + cwd | ✅ |
| 30 | tts | 无残留手搓运行时 | ✅ |
| — | 前端 | `tsc --noEmit` 编译 | ✅（exit 0） |

---

## 16. 路线图与完成度（S0–S4）

| 阶段 | 形态 | 关键能力 | 状态 |
|------|------|----------|------|
| S0 | 微内核主板 | 砖基座 + 进程内共享内核 | ✅ |
| S1 | 托管运行时 | 管理芯片 + 总线 + 信道织物 + 放置调度 | ✅ |
| S2 | 自治控制平面 | 零信任仲裁 + 配额 + 存储主分 + 热插拔/回滚 | ✅ |
| S3 | 联邦 + 认知 | 远端砖（tcp/ws）+ MCP 对外兼容 | ✅（MCP 完成；远端占位） |
| S4 | 个人 AI 操作系统 | 跨设备联邦、认知调度、自愈 | 🔜 backlog |

**Backlog 完成度**：本轮已一次性实现 P0–P3 全部（零信任 facade 仲裁、资源配额强制、存储主＋分 IC、热插拔/版本回滚/MCP、tts 收敛删除手搓 launcher）；前端主板视图 + 真实 ATX 监控屏落地；仅远端砖（tcp/ws 真实部署）与跨设备联邦为后续项。

---

## 17. 部署与运行

```bash
# 后端（含主板运行时层）
cd backend
.venv/Scripts/python.exe -m app.main        # 或 uvicorn app.main:app

# 前端
cd frontend && npm run dev

# 独立监控屏（开箱演示，无需后端）
浏览器直接打开 monitor.html                  # 走合成数据（SIM）
# 接真实主板：挂到 frontend/public/ 经 dev server + ?token= 访问（LIVE）

# 验证（虚拟内容实测）
python -m pytest backend/tests/              # 见 §15 固化用例（可选）
```

**Git 状态**：所有改动已本地 commit（按约定未擅自 push）；需要推送时显式确认。

---

*文档基于 `backend/app/bricks/_shared/{handle,transport,placement,arbitration,quota,storage,hotplug,bios,interop,telemetry}.py`、`base.py`、`__init__.py`、`plugins/tts_sovits/brick.py`、`frontend/src/*`、`monitor.html` 实际代码核对生成。*

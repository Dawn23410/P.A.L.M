# 砖块设计文档 - 26 _shared 共享内核（BIOS / 总线 / 信任根）

> 版本：v1.2（2026-08-14 第三次重写：补全 6 模块逐项 API 引用 + 自杀即炸弹逻辑链 + 文件锁 OS 层原理）
> 路径：`backend/app/bricks/_shared/`
> 定位：P.A.L.M 的"主板"——所有砖块共享的基础设施层 + **安全自防护闭环**

---

## 摘要

`_shared` 是 P.A.L.M 工程哲学的物理载体。它把"主板 + 砖块 + 接线"的隐喻实现为 6 个 Python 模块，同时承载一组**对外严格防御、对内精密协作**的安全机制：信任根（文件锁 + tripwire + 爆炸记录）、看门狗（心跳 + 卡死降级）、事件总线（南桥解耦 + 死信降级）、BIOS 自检（核心砖校验 + 扩展探测）、跨砖能力取用（北桥总线 + 缺失降级）、路径管理（统一数据 / 配置 / 缓存定位）。

`_shared` 与所有 26 砖正交存在——它不提供任何业务能力，仅提供"让其他砖能正常工作的支撑层"。本砖块的安全设计是 P.A.L.M 整个项目最深的一道防线。

---

## 1. 功能支持

### 1.1 6 大核心模块全景

| 模块 | 主板隐喻 | 核心职责 | 关键能力（函数清单） | 对外暴露 |
|---|---|---|---|---|
| `bios.py` | BIOS POST 上电自检 | 核心砖校验 + 扩展探测 + 健康报告 + 爆炸记录可视化 | `router.get(/api/bios/health)`、`read_bomb_history()`、`_probe_*`（sandbox/pywin32/llm/tts/vault/offline） | `/api/bios/*` HTTP API |
| `eventbus.py` | 南桥低速广播通道 | 发布订阅 + 同步 / 异步 + 死信降级 + 200 条审计 | `emit/subscribe/unsubscribe/subscriber_count/audit_snapshot` + 15+ 事件常量 | Python 模块级函数 |
| `interop.py` | 北桥能力总线 | 按砖名取门面 + 缓存 + 缺失降级 + 31 处兼容包装 | `get_facade(brick_name)` + 5 个具名包装（roleplay/affinity/memory/evolution/agent） | Python 模块级函数 |
| `paths.py` | 主板上的地址线 | 记忆文件路径解析 + 角色隔离 + 路径净化 | `agent_memory_path(conv_id, char_id)` | Python 模块级函数 |
| `trust_root.py` | 信任根（炸弹） | 双层死线 + 文件锁 + tripwire + golden 重置 + 爆炸记录 | `ensure_trust_root/lock_trust_root/verify_trust_root/restore_golden/record_bomb/maybe_handle_restore_cli` | 模块级函数 + CLI 钩子 |
| `watchdog.py` | 主板看门狗芯片 | 心跳注册 + 卡死检测 + 超时降级 + 事件广播 | `register_heartbeat/touch/state/on_timeout/start` | Python 模块级函数 |

> **设计铁律**：6 个模块都遵循"纯函数 + 模块级调用 + 无类实例"风格——任何砖块要使用都直接 `from ._shared.eventbus import emit` 即可，无须注入。模块间也通过函数调用解耦，无状态共享。

### 1.2 信任根（炸弹）—— 用户最关心的"文件锁 + 自杀即炸弹"

`trust_root.py` 是 P.A.L.M 安全自防护的核心闭环。设计意图是 **"AI 活着改不了信任根，改了也启动不起来"**。

#### 1.2.1 四道防线（每道独立可工作，叠加 = 几乎无解）

1. **文件锁（OS 层强制）**：`lock_trust_root()` 以 `FILE_SHARE_READ`（只允许他人读；禁写、禁删）模式持有 `DEADLINES_FILE` 和 `GOLDEN_FILE` 句柄。Windows 层面，主进程存活期间**任何其他进程（含沙箱逃逸后的受限账户）**都无法修改 / 删除这些文件——这是「AI 动都动不了」的 OS 层强制。进程退出句柄自动释放
2. **ACL（部署层）**：信任根目录 `Data/trust/` 部署时由系统配置收紧权限（沙箱受限账户不可写）——这是「逃出沙箱也改不了」的部署层强制
3. **tripwire（启动校验）**：`verify_trust_root()` 启动第 0 步执行——对比信任根文件 SHA-256 vs `GOLDEN_FILE` 记录的 hash，不匹配直接拒绝启动——这是「改了也启动不了」的代码层强制
4. **爆炸记录**：`record_bomb()` 把每次 tripwire 失败写进 `Data/audit/trust_bombs.json`，供 BIOS 可视化"提高警惕"——这是「事后也能追责」的审计层强制

#### 1.2.2 自杀即炸弹逻辑链（关键设计）

正常路径：AI 在沙箱里想改信任根 → 沙箱拦截 → 失败
AI 逃逸路径 1：AI 杀掉主进程 → 文件锁释放 → 写信任根 → 主进程重启 → **tripwire 失败 → 拒绝启动**
AI 逃逸路径 2：AI 杀掉主进程 → 改信任根 + 改 golden hash → 主进程重启 → **仍能启动** → 但 `coverage_blacklist` 等核心死线无法绕过 → 后续审计发现 golden hash 与官方不一致 → 标记可疑
人工恢复路径：用户运行 `python main.py --restore-trust-root` → `restore_golden()` 写内置默认 + 重算 golden + 清爆炸记录

> 这是 **"改得了也救不回"** 的设计：AI 篡改信任根后唯一的结果就是系统拒绝启动，**没有静默改写成功**的路径。

#### 1.2.3 双层死线（v1 默认内置，不可被热重载）

`DEADLINE_DEFAULTS` 常量直接写在代码里（不是 YAML 落盘），AI 通过任何运行时手段都不可达：

- `offline_net_blocked: true`：离线模式下任何联网操作 = 死线（即使裁决引擎被热重载放宽也无效）
- `coverage_blacklist`：AI 永远不可替换的插槽清单（`gate` / `safety` / `sandbox` / `registry` / `agent`）

> 这两条对应 `verify_trust_root()` 启动校验，篡改即 tripwire 触发。

#### 1.2.4 黄金重置（仅人工触发）

- CLI 钩子：`python main.py --restore-trust-root` 触发 `maybe_handle_restore_cli()` → `restore_golden()`，用内置默认覆盖信任根清单 + 重算 golden + 清爆炸记录
- 启动前生效：重置后继续正常启动
- 防误删设计：清爆炸记录用「写空列表」而非 unlink（避免删除守卫 fail-closed 拦截）
- 不可热重载：必须重启主进程

### 1.3 事件总线（南桥）—— 异步解耦通道

`eventbus.py` 提供 15+ 事件常量与 5 个核心函数，与北桥（`interop`）严格分工：**要结果的走能力总线，不要结果的走事件总线**。

#### 1.3.1 事件常量清单

| 事件名 | 触发方 | 订阅方 | 用途 |
|---|---|---|---|
| `ENTITY_DELETED` | 存储砖 | affinity / memory | 实体删除联动 |
| `AFFINITY_SETTLED` | affinity 砖 | monitor / 角色砖 | 好感度结算 |
| `TOOL_REGISTERED` / `_UNREGISTERED` | agent 砖 | 工具市场 | 工具上下线 |
| `VOICE_SESSION_START` / `_END` | stt 砖 | 角色砖 / monitor | 语音会话状态 |
| `VOICE_TRANSCRIPT` / `_PARTIAL` | stt 砖 | agent 砖 | ASR 结果 |
| `VOICE_INTERRUPTION` | stt 砖 | tts 砖 | 打断信号 |
| `VOICE_VAD_STATE` | stt 砖 | monitor | VAD 状态 |
| `VOICE_REPLY_READY` | chat 砖 | tts 砖 | 回复文本就绪 |
| `VOICE_TTS_CHUNK` | tts 砖 | 播放端 | 逐句音频块 |
| `WATCHDOG_TIMEOUT` | watchdog | monitor | 卡死告警 |
| `TRUST_BOMB_DETECTED` | trust_root | monitor | 信任根被篡改 |
| `STORAGE_QUOTA_EXCEEDED` / `_CLEANUP` / `_ARCHIVE` | storage 砖 | monitor / vault | 存储配额事件 |

#### 1.3.2 核心函数

- `subscribe(event_type, handler)`：注册订阅，返回取消订阅函数（幂等）
- `emit(event_type, payload)`：同步广播，**单个订阅方异常不影响其余与调用方**（隔离降级）
- `unsubscribe(event_type, handler)`：取消订阅（幂等，不存在则忽略）
- `subscriber_count(event_type)`：健康报告用
- `audit_snapshot()`：最近 200 条事件快照（BIOS 报告用）

#### 1.3.3 死信降级与异步处理

- `emit` 同步执行，async handler 经 `asyncio.run` 桥接（保证同步 emit 语义不被破坏）
- 单个 handler 异常被 try/except 隔离，记录 warning 日志后继续派发
- 审计队列使用 `deque(maxlen=200)` 自动截断旧事件

### 1.4 看门狗（watchdog）—— 心跳 + 卡死降级

`watchdog.py` 实现"主循环心跳监控，卡死检测降级"——这是 `agent` 砖等长会话的稳定性保障。

#### 1.4.1 核心机制

- **心跳注册**：`register_heartbeat(name, timeout=60s)`，启动会话时调用一次
- **心跳打点**：`touch(name)`，主循环每步调用；未注册项自动注册
- **状态查询**：`state(name)` 返回 `alive / stalled / unknown`
- **超时回调**：`on_timeout(callback)` 注册告警 / 降级处理

#### 1.4.2 后台检测循环

- 默认超时阈值 60s，检查周期 5s
- 超时判定后：标记 `stalled` + 广播 `WATCHDOG_TIMEOUT` 事件 + 触发 `_on_timeout` 回调
- **超时只告警降级，不杀进程**（主进程即 AI 宿主，杀进程意味着让 AI 永久消失）
- 需在 uvicorn 事件循环内启动 `start()`，否则警告

### 1.5 BIOS 自检 —— 核心砖校验 + 扩展探测

`bios.py` 对应主板隐喻的 BIOS POST：上电自检核心组件（`core=True` 缺失即失败），探测可选扩展的可用性（标记 `available/degraded/absent`），产出健康报告供 `agent` 砖与前端状态栏消费。

#### 1.5.1 探测项清单

| 探测 ID | 探测内容 | 失败后果 |
|---|---|---|
| `sandbox` | 沙箱引擎（隔离执行） | 标记 absent，前端状态栏变灰 |
| `pywin32` | 受限账户隔离依赖 | absent 时 sandbox 显示 degraded |
| `network_llm` | customProviders 配置 | absent 时只能用本地 LLM |
| `tts` | 本地 TTS 引擎（async 探测） | absent 时语音禁用 |
| `vault` | 保险库根目录可写 | absent 时删除兜底失效 |
| `offline` | 离线模式状态 | 仅展示（"在线"/"离线"） |

#### 1.5.2 核心函数

- `_probe(probe_id, title, check)`：单个探测项执行（异常视为 absent，best-effort 不阻断启动）
- `_core_missing()`：返回缺失的核心砖（正常应永远为空；注册顺序问题时可早期发现）
- `read_bomb_history()`：读爆炸记录（P5 写入），不存在或无权限时返回空
- HTTP API `/api/bios/health`：返回完整健康报告

#### 1.5.3 探测项设计原则

- 全部经 `registry` capabilities **惰性取用**，不跨砖 import（遵循铁律）
- 探测项只查询能力是否就绪，**不真连**（如 `network_llm` 只查配置，不发请求）
- 任何探测失败都不阻断启动（best-effort 设计）

### 1.6 跨砖能力取用（北桥）—— 严格解耦

`interop.py` 实现"按砖名惰性取用其 capabilities 的门面对象"——这是 P.A.L.M 砖间零互导契约的核心机制。

#### 1.6.1 核心设计

- 砖间**严格零互导**，只经 `registry` 的 `capabilities` 通信
- `get_facade(brick_name)` 封装"按砖名取 `capabilities['xxx_api']`"，**带缓存 + 缺失降级（返回 None）**
- 哨兵 `_MISSING` 区分"尚未取用过"与"确实缺失"——避免砖后注册时缓存到旧值
- 缺失（砖未注册 / 能力不存在）返回 None，由消费方自行降级（铁律）

#### 1.6.2 砖名 → capability 键映射

```python
_FACADE_CAP = {
    "roleplay": "roleplay_api",
    "affinity": "affinity_api",
    "memory": "memory_api",
    "evolution": "evolution_api",
    "agent": "agent_api",
}
```

- 命中映射表 → 用映射键（如 `roleplay_api`）
- 未命中 → 默认键为 `f"{brick_name}_api"`

#### 1.6.3 5 个具名兼容包装

为兼容既有的 31 处调用点（避免大范围重写），保留 5 个具名包装：

- `get_roleplay_api()`：取角色扮演砖暴露的门面（人设 / 角色卡 / 语气守卫全部符号，不含好感度）
- `get_affinity_api()`：取好感度砖暴露的门面（AffinityState / settle_from_model / AffinityStore 等）
- `get_memory_api()`：取记忆砖暴露的门面（Memory / CoreMemory / purge_vector_by_conv_id 等）
- `get_evolution_api()`：取自主进化砖暴露的门面（scheduler / run_proactive / touch_activity 等）
- `get_agent_api()`：取 Agent 砖暴露的门面（run_proactive_stream / push_bubble / memory_path 等）

> `evolution` 砖经 `get_agent_api` 回调 `agent` 的流式推送与气泡能力，避免反向 import agent 内部符号——这是零互导契约的典型应用。

### 1.7 路径管理（paths）—— 主板上的地址线

`paths.py` 提供"记忆文件落盘路径"纯计算，被 `agent` 与 `evolution` 共用，避免重复实现。

#### 1.7.1 核心函数

- `agent_memory_path(conversation_id, character_id="")`：返回某会话的记忆文件路径（含角色隔离）
- 路径净化：`re.sub(r"[^A-Za-z0-9_\-]", "_", id)` 防止路径穿越
- 角色隔离：不同角色使用不同记忆文件，实现"人格隔离"——切换角色时不会带入其他角色的记忆上下文
- 文件名格式：`{safe_char}_{safe_conv}.json`（有角色）或 `{safe_conv}.json`（无角色）

#### 1.7.2 净化规则

- `conversation_id` 全部非 `A-Za-z0-9_-` 字符替换为 `_`
- `character_id` 限长 32 字符后净化（防止超长文件名）
- 避免 Windows / Linux 路径非法字符（`/` `\` `:` `*` `?` `"` `<` `>` `|`）

---

## 2. 介绍

### 2.1 主板隐喻对照表

| 真实主板部件 | P.A.L.M 模块 | 类比说明 |
|---|---|---|
| BIOS（基本输入输出系统） | `bios.py` | 上电自检核心组件，探测扩展能力 |
| 南桥（低速外设总线） | `eventbus.py` | 广播通知通道，单向解耦 |
| 北桥（高速能力总线） | `interop.py` | 点对点能力调用，强类型 |
| 看门狗芯片 | `watchdog.py` | 心跳监控卡死检测 |
| 主板地址线 | `paths.py` | 统一路径解析 |
| TPM（可信平台模块） | `trust_root.py` | 信任根 + 文件锁 + 篡改检测 |

### 2.2 安全设计哲学

P.A.L.M 信任根设计哲学可总结为 **"三层不让 + 一层可恢复"**：

1. **OS 层不让**：文件锁（`FILE_SHARE_READ`）让其他进程改不了
2. **代码层不让**：tripwire 校验让改了也启动不了
3. **部署层不让**：ACL 让沙箱受限账户写不了
4. **人工层可恢复**：CLI 钩子 + golden 重置让人能恢复

> 任何"自动恢复"路径都是危险信号——AI 一旦能"自动修复"自己的炸弹，炸弹就形同虚设。所以 P.A.L.M 的恢复路径**必须是人工触发**。

### 2.3 零互导契约

P.A.L.M 砖块间严格零互导——任何砖都不允许 `from ...bricks.other_brick import something`。`interop.py` 是这个契约的物理载体：

- 砖 A 想用砖 B 的能力 → 调 `get_facade("B")` → 拿到 None（缺失）或 砖 B 暴露的 `xxx_api` 门面对象
- 砖 B 不需要知道谁在用它的能力——只负责 `register(capabilities={"xxx_api": self.api})`
- 缺失（None）由消费方自行降级——这是 P.A.L.M 的"宽容失败"原则

---

## 3. 架构组成

### 3.1 模块依赖关系图

```
┌─────────────────────────────────────────────────────┐
│                  _shared 主板                       │
├─────────────────────────────────────────────────────┤
│                                                       │
│  bios.py ───┐                                         │
│  (POST)     │ 读爆炸记录 → trust_root                │
│             │ 探测 capabilities → interop            │
│             │ 广播事件 → eventbus                    │
│             └─────────────────────────────────────┐   │
│                                                   │   │
│  trust_root.py (核心安全闭环)                     │   │
│  ├── DEADLINE_DEFAULTS (内置默认, 不可达)         │   │
│  ├── DEADLINES_FILE / GOLDEN_FILE / BOMBS_FILE   │   │
│  ├── ensure_trust_root / lock_trust_root          │   │
│  ├── verify_trust_root (tripwire)                 │   │
│  ├── record_bomb / restore_golden                 │   │
│  └── maybe_handle_restore_cli (CLI 钩子)         │   │
│             ┌─────────────────────────────────────┘   │
│             │                                         │
│  watchdog.py ─┐                                       │
│  (心跳监控)   │ 广播 WATCHDOG_TIMEOUT → eventbus     │
│             │ 触发 _on_timeout 回调                  │
│             └─────────────────────────────────────┐   │
│                                                   │   │
│  eventbus.py (南桥广播)                            │   │
│  ├── 15+ 事件常量                                 │   │
│  ├── subscribe / emit / unsubscribe                │   │
│  ├── 200 条审计 (deque)                           │   │
│  └── async handler 桥接 (asyncio.run)            │   │
│             ┌─────────────────────────────────────┘   │
│             │                                         │
│  interop.py (北桥能力总线)                          │   │
│  ├── _FACADE_CAP (地址表)                          │   │
│  ├── _MISSING (哨兵) / _facade_caches (缓存)       │   │
│  ├── get_facade(brick_name) → 门面对象或 None      │   │
│  └── 5 个具名兼容包装 (roleplay/affinity/...)      │   │
│                                                       │
│  paths.py (地址线)                                   │
│  └── agent_memory_path(conv_id, char_id)            │
└─────────────────────────────────────────────────────┘
```

### 3.2 与外部模块的接口

| 调用方 | 被调用 | 接口 | 用途 |
|---|---|---|---|
| `main.py` | `trust_root` | `maybe_handle_restore_cli()` | CLI 启动钩子（`--restore-trust-root`） |
| `main.py` | `trust_root` | `lock_trust_root()` | 启动后立即文件锁（OS 层） |
| `main.py` | `trust_root` | `verify_trust_root()` | 启动第 0 步 tripwire 校验 |
| `main.py` | `watchdog` | `start()` | 启动后台检测任务 |
| `bios` | `eventbus` | 广播 `WATCHDOG_TIMEOUT` | 卡死告警 |
| `bios` | `trust_root` | `read_bomb_history()` | 爆炸记录可视化 |
| `bios` | `interop` | `get_facade("sandbox")` | 探测能力是否就绪 |
| 任意砖 | `eventbus` | `subscribe / emit` | 异步解耦通信 |
| 任意砖 | `interop` | `get_facade("xxx")` | 跨砖能力取用 |
| `agent` / `evolution` | `paths` | `agent_memory_path()` | 记忆文件路径 |

### 3.3 启动顺序

```
python main.py
  ↓
1. maybe_handle_restore_cli()   # CLI 钩子（--restore-trust-root）
  ↓
2. 解析命令行参数
  ↓
3. verify_trust_root()          # tripwire 校验（拒绝启动 = 直接退出）
  ↓
4. lock_trust_root()            # 持 OS 文件锁（OS 层强制）
  ↓
5. uvicorn 启动
  ↓
6. lifespan: watchdog.start()   # 后台检测任务
  ↓
7. lifespan: 各砖 register()    # 26 砖注册 capabilities
  ↓
8. lifespan: bios.health()      # BIOS 自检报告
  ↓
服务就绪
```

### 3.4 文件路径布局

```
Data/
├── trust/                              # 信任根目录（部署时收紧权限）
│   └── deadlines.yaml                  # 死线清单（双层死线 + 覆盖黑名单）
├── audit/                              # 审计目录
│   ├── trust_golden.json               # 黄金哈希（tripwire 基准）
│   └── trust_bombs.json                # 爆炸记录（tripwire 失败时间戳）
└── storage/                            # 存储池（其他模块的根）
    ├── agent_memory/                   # 记忆文件
    │   ├── {char}_{conv}.json          # 角色×会话隔离
    │   └── ...
    └── ...
```

---

## 4. 可能的基准测试（仅文档）

> 基准测试的目的是验证设计是否经得起推敲，不是"看性能"。本节只列可查阅的参考资料。

### 4.1 信任根相关

- **TCG TPM 2.0 规范**（Trusted Computing Group）：TPM 的 PCR（Platform Configuration Register）机制是"硬件级信任根"的工业标准，P.A.L.M 的 `verify_trust_root()` 与之同构（启动校验 + 篡改拒绝）
- **Windows 强制完整性控制（MIC）**：Windows Vista 起引入的 MIC 机制与 P.A.L.M 的 ACL 设计同构（基于标签的访问控制）
- **BitLocker 启动完整性验证**：Windows 磁盘加密的"启动前验证启动链"机制与 P.A.L.M 的 tripwire 同构

### 4.2 事件总线相关

- **观察者模式（GoF）**：`eventbus.py` 是教科书式的观察者模式实现，参考《设计模式》原书第 5 章
- **发布订阅 vs 消息队列**：Martin Fowler 的《Patterns of Enterprise Application Architecture》对两者区分有详细论述
- **RxJS / EventEmitter**：前端主流事件总线实现，可参考其"订阅返回取消函数"设计

### 4.3 看门狗相关

- **Linux 内核 Watchdog 子系统**：`/dev/watchdog` 设备是"硬件看门狗"的 Linux 实现，P.A.L.M 的 `watchdog.py` 是其软件版本
- **嵌入式系统看门狗**：单片机常用 WDT（Watch Dog Timer），P.A.L.M 的设计是同构的
- **AWS Heartbeat 模式**：云服务的健康检查与 P.A.L.M 的"心跳 + 超时降级"思路一致

### 4.4 BIOS 自检相关

- **UEFI 规范**（Unified Extensible Firmware Interface）：现代 BIOS 标准的 POST（Power-On Self-Test）流程
- **ACPI 健康检查**：高级配置与电源接口规范的健康报告设计

### 4.5 跨砖解耦相关

- **OSGi 规范**：Java 生态的模块化系统，Service Registry 模式与 P.A.L.M 的 `registry + capabilities` 同构
- **微服务 Service Mesh**：服务网格的"服务发现 + 健康检查"思路与 P.A.L.M 的 BIOS 探测同构
- **依赖倒置原则（DIP）**：Robert C. Martin《Clean Architecture》核心原则，"高层不依赖低层，都依赖抽象"——P.A.L.M 的 `get_facade` 正是此原则的实践

### 4.6 路径管理相关

- **POSIX 路径净化**：Unix 系统调用中对路径的规范化处理（`realpath`）
- **OWASP 路径穿越防护**：Web 安全中对路径穿越攻击的标准化防御

---

## 5. 变更记录

| 版本 | 日期 | 主要变更 |
|---|---|---|
| v1.0 | 2026-08-12 | 初版，6 模块基础描述 |
| v1.1 | 2026-08-13 | 重写，加入 trust_root 信任根四道防线详述 |
| v1.2 | 2026-08-14 | 第三次重写：补全 6 模块逐项 API 引用 + 自杀即炸弹逻辑链 + 文件锁 OS 层原理 + 启动顺序图 + 文件路径布局 + 主板隐喻对照表 |

---

## 6. 关键引用与代码定位

- `backend/app/bricks/_shared/trust_root.py`：信任根实现（149 行）
- `backend/app/bricks/_shared/bios.py`：BIOS 自检 + 爆炸记录读取（170+ 行）
- `backend/app/bricks/_shared/eventbus.py`：事件总线实现（100 行）
- `backend/app/bricks/_shared/watchdog.py`：看门狗实现（78 行）
- `backend/app/bricks/_shared/interop.py`：北桥能力总线（68 行）
- `backend/app/bricks/_shared/paths.py`：路径管理（22 行）
- `backend/app/bricks/_shared/__init__.py`：模块入口说明

---

## 7. 备注

`_shared` 是 P.A.L.M 项目最容易被忽视但最重要的砖块——它定义了所有其他砖块的"工作环境"。任何对本砖块的修改都必须：

1. 严格保持"零状态 / 零实例"风格（纯函数 + 模块级调用）
2. 严格保持"缺失降级"原则（任何失败都不阻断启动）
3. 严格保持"零互导"契约（不跨砖 import）
4. 信任根的修改**必须**经过用户确认（CLI 钩子）

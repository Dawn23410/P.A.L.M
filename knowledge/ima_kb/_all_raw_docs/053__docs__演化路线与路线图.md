# P.A.L.M 演化路线与终极主板架构（Roadmap）

> 本文档把「架构检查 → 运行时层落地」之后的演化方向固化为官方路线图。
> 数据来源：2026-08-14 架构检查（联网趋势校验）+ 代码实测（masterboard 快照、传输层、调度器现状）。
> 配套代码：`backend/app/bricks/base.py`、`_shared/{transport,handle,telemetry,eventbus,watchdog,bios}.py`、`bricks/__init__.py`、`permission.py`。

---

## 0. 一句话定位

**P.A.L.M 的终极形态是一台「为一个人而生的 AI 计算机」——个人 AI 操作系统（Personal AI OS）。**
主板隐喻不是修辞：我们已经在搭的，正是 2026 年业界公认胜出的「微内核 + 控制平面」式 Agent 运行时。

---

## 1. 科技趋势校验（2026 实况，恰好印证当前设计）

| 趋势 | 2026 实况 | 对应已建能力 |
|---|---|---|
| **MCP 赢下工具层** | SDK 月下载从 ~10 万 → **9700 万**（18 个月 970×），1 万+ server，Linux 基金会治理，主流模型全部原生支持；A2A 赢下 Agent 间协作（150+ 组织） | 北桥能力总线只需包一层 MCP 适配器即接入生态（预留 P3） |
| **个人 AI OS 是范式转移** | 「AI 不再是你去的地方，而是你生活的环境」；微软 Aion 1.0 把 14B agent 模型烧进 Windows；elizaOS 走 local-first，plugin 是一等公民（install/launch/track 跨重启存活） | 本地优先 + 个人角色（梦瑶）+ 砖即一等公民，正处在这一波 |
| **微内核 / 控制平面 = 生产级事实标准** | 「模型动作变成系统调用——经校验、沙箱、可审计；幻觉降级为一次失败的 syscall，而非生产事故」 | `BrickRegistry`（控制平面）+ `BrickHandle`（受管单元）+ 能力总线（类 syscall）+ watchdog/审计/熔断（沙箱/审计） |
| **自治运行时 + 混合记忆** | elizaOS 管 plugin 生命周期、跨运行时调度；端侧路由把任务派到最便宜模型（<20ms，零 token）；MemGPT 式四层记忆 + 「梦境」自动凝练 | `BusController` + endpoint 织物 + 遥测 + 看门狗已是这些能力的原始构件；缺「放置调度器」把 endpoint 决策智能化 |

**关键结论**：担心的「终极主板」不是空中楼阁——它就是 2026 年 Agent 架构的终点形态，而最难、最易塌的那部分（一个 30+ 砖不崩的微内核控制平面）已经站着了。

---

## 2. 当前架构分层完成度（实测，非估计）

| 层 | 内容 | 完成度 | 实测证据 |
|---|---|---|---|
| **L0 主板骨架** | 六总线 `BusType`、微内核 `BrickRegistry`、`BrickManifest`（含 endpoint/version/isolation） | **100%** | `base.py` 完整；`registry.group_by_bus()` 六总线分组就绪 |
| **L1 双总线** | 北桥能力总线 `interop.get_facade` + 南桥事件总线 `eventbus`（pub/sub） | **100%** | `_shared/interop.py`、`_shared/eventbus.py` 均已落地，无需重造 |
| **L2 管理芯片 + 传输 + 总线控制器** | `BrickHandle` · `transport`(InProc/Subprocess/Remote) · `BusController` | **框架 100% / 接线 ~20%** | 29 砖全部包成 handle（masterboard 实测）；但**全仓 0 砖暴露 `subprocess_spec`**，PCIE 默认 `ipc://` 全部安全退化成 `inproc` —— 隔离能力休眠 |
| **L3 健康地基** | watchdog 心跳 · `CapabilitySlot` 超时熔断+半开恢复+指标 · `TelemetrySink` 遥测 | **90%** | watchdog 已实现；Slot 硬化已实现；遥测采集已实现，**前端未渲染**（南桥事件未可视化） |
| **L4 安全治理** | 基于能力的权限声明 · 调用审计 · facade 仲裁代理 | **70%** | 权限声明 + 审计已实现；**facade 取能力仍直返 callable，未强制过仲裁代理**（零信任只做一半） |
| **L5 插件生态** | 清单发现 · 生命周期 · 热插拔 · 版本回滚 · MCP | **50%** | `brick.yaml` 元数据 + `_discover_plugins()` 自动发现已实现；热插拔/回滚/MCP 未做 |
| **L6 存储架构** | 统一 storage 砖 · 主+分 IC 拆分（每砖声明策略 / storage 执行） | **35%** | 仅统一 storage 砖；「主+分」停留在讨论，未编码 |

---

## 3. 终极演化形态：S0 → S4

- **S0 微内核主板（已实现）** — 六总线、`BrickRegistry`、`BrickManifest`、双总线（北桥能力 / 南桥事件）。= 内核 + syscall 接口。

- **S1 托管运行时（已落地 80%，即本轮「全搞」成果）** — `BrickHandle` 管理芯片、`transport` 织物（inproc/ipc/tcp/ws）、`BusController`、遥测、看门狗、审计、插件自动发现。= 生产级微内核 harness。
  **缺口**：Subprocess/Remote 尚未接到业务砖、前端未渲染主板、资源配额未强制。

- **S2 自治控制平面（下一步）** — 放置调度器（按资源/隐私画像给每块砖选最便宜可行的 endpoint）、ipc 砖的系统调用级沙箱（CPU/内存/网络配额）、热重载 + 版本回滚、facade **强制过仲裁代理**（工具网关的权限拦截层）。= 「会自己管理自己的 OS」。

- **S3 联邦 + 认知** — 北桥加 MCP 适配器（内部砖暴露成 MCP server / 消费外部 1 万+ server）+ A2A 节点（多 Agent 协作）；南桥事件流升级为**事件溯源式认知**（agent 的「自传记忆」+ 学习回路）；存储主+分 IC（每砖声明策略 / storage 执行的治理数据飞地）。= 「接入生态、持续学习」。

- **S4 个人 AI 操作系统（终极）** — 主权、本地优先、具身（GUI 自动化砖 = 它在桌面世界的「身体」）、自演化（self_evolution + 自治控制器重配主板）、隐私内建（每个字节可追溯到其归属砖与能力调用、端到端审计）。本质：**「一个人 AI 能力的 Android/iOS」**——在你的硬件上跑你的模型、你的 Agent、你的数据、你的能动性，只在重活时选择性上云。

---

## 4. 工作量研判

**已做的是高风险的硬骨头，剩下的是低风险的加性层。**
一个能扛 30+ 砖而不塌的微内核控制平面，是整个项目里最易写崩、最需要架构功力的部分——它已经站着了。
S2 的放置调度器 / 沙箱 / 仲裁是在已有 `BusController`/`transport`/`telemetry` 上长出来的；
S3 的 MCP 适配器是「在能力总线外包一层协议」，不碰内核。
**从 S1 → S4 不需要重写任何地基，全是搭上层建筑。**

---

## 5. 落地优先级 backlog

| 优先级 | 任务 | 收益 | 落点层 | 风险 |
|---|---|---|---|---|
| **P0** | 前端接 `masterboard`（实时主板健康灯） | 终极主板可见闭环立刻成形 | L3→100% | 低（后端 API 已就绪 `/api/bios/status`） |
| **P0** | tts_sovits 暴露 `subprocess_spec`，收敛进 `SubprocessTransport` | 证明「每砖管理芯片 + 自定义地址」真能跑隔离 | L2→100% | 低（不自动 load，懒 spawn 路径不变） |
| **P1** | facade 取能力强制过仲裁代理（而非直返 callable） | 零信任闭环 | L4→100% | 中（需 audit 所有 facade 取用点） |
| **P1** | `BusController` 加资源配额强制（CPU/内存/IO） | 治理真正落地 | L2→ | 中 |
| **P1** | `PlacementScheduler` 放置调度器骨架 | 自治控制平面起点 | S2 | 低（纯后端加性） |
| **P2** | 存储主+分 IC 拆分（每砖声明策略 / storage 执行） | 治理数据飞地、解耦 | L6→ | 中 |
| **P2** | 插件热插拔（不停机 load/dispose）+ 版本回滚 | 内核健壮性 | L5→ | 中 |
| **P3** | MCP 兼容层（北桥包适配器，内部砖不必改） | 接入 1 万+ server 生态 | S3 | 大/可选 |

---

## 6. 三个岔路口（影响终极形态的细节）

1. **协议分叉**：MCP 赢了，但 UTCP（「不要 wrapper server，直接调原生 API」，延迟降 ~50%）是反主流赌注。我们 `endpoint` 织物的 `tcp://`/`ws://` 天然能支持 UTCP 式直连模式——这是别的框架没有的对称性优势，保留。
2. **OS 原生 Agent（Windows Aion / Apple Intelligence）**：要么吃掉 Agent 层（威胁），要么被编排（机会）。GUI 自动化砖作为「具身层」无论哪种都成立。
3. **主权监管**：预测 2027 年区域 AI 生态碎片化——本地优先的 P.A.L.M 反而因此受益。

---

## 7. 本次（2026-08-14）已落地清单

- ✅ `base.py`：`BrickManifest` 增 endpoint/version/isolation；`CapabilitySlot` 超时熔断 + 半开恢复 + 单能力指标
- ✅ `_shared/transport.py`：InProc/Subprocess/Remote 三传输 + `transport_for()`
- ✅ `_shared/handle.py`：`BrickHandle` + `BusController` + `masterboard_snapshot()`
- ✅ `_shared/telemetry.py`：`TelemetrySink` 每砖指标
- ✅ `permission.py`：能力调用审计（最近 500 条）
- ✅ `bricks/__init__.py`：`brick.yaml` 元数据 + `_discover_plugins()` 自动发现 + `_wrap_all_bricks()` 全砖包芯片
- ✅ `bios.py`：`/api/bios/status` 输出 `masterboard`
- ✅ gui 死代码清理（删 `RunGuiIntentTool` + 移除无消费者 `GUI_TOOL_GROUPS`）+ game 注释修正

**后续 P0（待做）**：前端渲染 masterboard + tts_sovits 收敛进 SubprocessTransport + PlacementScheduler 骨架（见 P0/P1 行）。

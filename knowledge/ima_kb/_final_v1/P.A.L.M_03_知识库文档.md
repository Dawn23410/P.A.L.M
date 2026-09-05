# P.A.L.M 系统架构白皮书（终极架构版）

> 本文档以当前工作区 C:/Users/24459/Desktop/P.A.L.M/palm/ 真实代码为唯一依据，描述"终极架构"（2026-08-18 定稿）的完整架构。读者应能凭本文档 + 模块深度解析篇（第 4 篇）+ 复刻指南篇（第 6 篇）重建等价系统。旧主板/砖块/总线体系不在本文描述范围内（已归档）。

---

## 第一部分 架构哲学

### 1.1 五条铁律

1. **依赖单向**：ports ← domain/services/adapters ← bootstrap。越层即 lint 报错（工程层强校验）。
2. **服务容器**：palm/_core/container.py 提供 Container + ServiceHandle.capability；业务代码经 `container.get(名)` 惰性取用，缺失归一 None（铁律：缺失归一降级，业务侧必须判空）。
3. **装配唯一**：palm/bootstrap/app.py 是唯一出现"注册"概念的地方；业务模块零注册、零全局状态。
4. **门面收敛**：敏感能力经门面（facade）收敛——网卡门面（_core/net/）是唯一出网出口（fail-closed）；裁决内核（_core/guardrail/）统一裁决。
5. **契约先行**：15 个 Port ABC 定义能力契约，可独立 import，ABC 强制验证通过。

### 1.2 与旧体系的对应关系

| 旧概念（已归档） | 新概念 |
|---|---|
| 主板（bootstrap/主板） | palm/bootstrap/app.py 装配层 |
| 砖块（Brick） | 服务（container 注册名） |
| BusType（cpu/pcie/ram/sata/chip/board） | 无（取消总线隐喻） |
| registry（注册表） | container（服务容器） |
| capabilities 字典 | ServiceHandle.capability(键) |
| palm_sdk（运行基座） | palm/_core/（功能收敛） |
| Manifest | 无 |

### 1.3 目录总览

```
palm/
├── _core/        # 基础设施（与业务无关的横切能力）
├── adapters/     # 适配器（外部 IO/系统能力：存储/加密/模型/显示/GUI/IO）
├── bootstrap/    # 装配层（唯一注册点）
├── domain/       # 领域层（业务概念与规则：进化/记忆/规划/角色扮演）
├── ports/        # 契约层（15 个 Port ABC）
└── services/     # 服务层（业务流程编排：agent/chat/evolution/ops）
```

---

## 第二部分 分层架构详解

### 2.1 契约层 ports/（15 个 Port ABC）

ports/ports/ 下 15 个文件，每个定义一类能力契约：

| Port | 职责 |
|---|---|
| agent_port | Agent 执行契约（run/stream/工具注册） |
| audio_port | 音频（TTS/STT/合成/播放） |
| crypto_port | 本机加解密（encrypt/decrypt/指纹） |
| device_port | 设备能力（硬件/GPU/系统信息） |
| display_port | 显示层（壁纸/悬浮组件/部件） |
| guard_port | 裁决契约（guardrail 5 档） |
| gui_port | GUI 自动化（automate 入口） |
| memory_port | 记忆（写入/检索/权重） |
| model_port | 模型供应商（流式对话/文件能力） |
| ops_port | 运维（用量/调度/遥测） |
| persist_port | 持久化契约 |
| storage_port | 存储（文件池/配置） |
| sys_port | 系统级（路径/进程/环境） |
| tool_port | 工具（100+ 工具集契约） |
| ui_port | 前端 UI 契约 |

**关键性质**：可独立 import（无运行时依赖）、ABC 强制验证（子类必须实现全部抽象方法）、总出口聚合（一个入口导出全部 Port）。

### 2.2 适配器层 adapters/

| 适配器 | 文件 | 能力 |
|---|---|---|
| storage | pool.py | store_file/read_file_content/delete_file/get_store/load_app_settings/find_config_file——文件池抽象（Data/storage_pool） |
| io | app_settings.py | 应用设置读写（settings.json） |
| crypto | keystore.py + operations.py | 指纹采集（boot）、encrypt_data/decrypt_data；指纹失败仅置禁用不阻断 |
| model | provider.py | 模型供应商：stream_chat（流式）、is_model_file_capable、file_handling_mode——云端 LLM 统一出口 |
| gui | automation_orchestrator.py | automate(software_id, intent) 单一入口 + L0-L3 执行器链 |
| display | （壁纸引擎 + 悬浮组件） | 显示层能力 |

适配器是"世界接触面"：只有适配器可以碰外部 IO（文件、网络、GPU、系统 API）。业务层不直接碰任何外部 IO。

### 2.3 领域层 domain/

领域层承载业务概念与规则，不依赖服务层与适配器（依赖方向向下兼容契约层）：

| 子域 | 核心文件 | 职责 |
|---|---|---|
| roleplay | character/persona/affinity_engine/affinity_store/affection/dynamics_engine/pollution_guard/game_service/xp/state/import_skill | 角色扮演、好感度双线、动态机制、游戏结算、Markdown 技能导入 |
| memory | core_memory/archived_memory/vector_memory/memory_writer/token_budget/weights/ | 分层记忆、事实写入、token 预算、记忆权重 |
| planning | planner.py/schemas.py | 规划引擎领域模型 |
| evolution | proactive/idle_orchestrator/offline_digest/habit_engine/fallback_engine/background_tasks | 自主进化、闲置推测、每日简报、习惯、兜底 |

### 2.4 服务层 services/

服务层编排业务流程，是"应用服务"：

| 服务组 | 文件 | 职责 |
|---|---|---|
| chat | chat_service/conversation_store/hub/engine/build_corpus/corpus/ | 会话流程、会话存取、引擎选择、语料 |
| agent | core/agent_execution_mixin/agent_prompt_mixin/agent_react_mixin/_native_execution/native_runner/native_parse/plan_engine/react_parser/tool_base/tool_matcher/tools/protocols/schemas/trace/completion_gate/code_guard/question_hub/persona/prompt_templates/dual/ | Agent 框架全套 |
| evolution | registry/loader/observer/gate/slot_store/skill_registry/_injection/_io/schemas/ | 进化系统服务化（注册/观察/门控/技能槽） |
| ops | engine/cron/mode_resolver/game_detector/_settings/store/token_ledger/token_usage/ | 调度引擎、定时任务、模式解析、游戏对局检测、Token 计量 |

### 2.5 装配层 bootstrap/

palm/bootstrap/app.py（140 行）：唯一注册点，`build_app()` 幂等（重复调用返回已注册容器）。装配顺序 = 依赖顺序：
1. 适配器层：storage → settings → crypto → models → gui（各自 try/except 降级注册）。
2. 服务层：usage → usage_ledger → scheduler → conversations → game → affinity → roleplay → memory → evolution → agent。
3. 返回 ContainerProxy。

每个服务注册时附带 capabilities 字典（如 storage 注册 6 个能力、game 注册 5 个能力、models 注册 4 个能力）。注册失败仅打印降级信息，不阻断装配——底座缺失归一 None。

---

## 第三部分 基础设施 _core/ 详解

### 3.1 服务容器 container.py

- **Container**：`register(name, impl, capabilities)`、`get(name)`（缺失返回 None）、`names()`。
- **ServiceHandle.capability(键)**：取能力函数，缺失归一 None。
- 业务代码范式：`handle = container.get("storage"); if handle: handle.capability("store_file")(...)`。
- gateway.py 承接旧 registry 迁移能力（dual/tools/world_model_cache 等 17 文件收敛至此）。

### 3.2 裁决内核 guardrail/

- engine.py + rules.py：5 档裁决（从宽松到严格），AI 档无回调时 fail-closed deny。
- 裁决对象：工具调用、联网、代码执行、进化主动动作等敏感操作。
- 接入点：agent.proactive 裁决事件、ChineseDictTool 联网裁决等（历史审计增强项）。

### 3.3 网卡门面 net/

- 唯一出网出口，fail-closed（未配置/异常时拒绝出网）。
- 所有网络访问（WebSearch、HTTP 工具、模型 API 之外的出网）经此门面。

### 3.4 权限引擎 permission.py

- 敏感能力须经用户授权（Phase 0-4 完成）。
- 持久化：permissions.json。
- 与 guardrail 分工：guardrail 是运行期裁决（规则引擎），permission 是授权状态管理（用户意图）。

### 3.5 冗余与兜底 redundancy/

- vault.py：文件级保险库，删除拦截兜底（删除先入 vault，可恢复）。
- recycle.py：回收站。
- 与 safety 服务/前端保险库面板联动。

### 3.6 事件与传输 eventbus.py + transport.py

- eventbus：进程内事件发布/订阅（工具调用事件、ask_user 事件、裁决事件、proactive 事件）。
- transport：传输层协议（控制码、SSE 事件、ask_user 应答 id 机制）。

### 3.7 其他基础设施

| 模块 | 职责 |
|---|---|
| config.py | 配置加载（.env / 默认值） |
| emotion.py | 情绪模型（五因子，E_enc 仅 v≥0） |
| housekeeping.py | 后台保洁（临时文件/日志清理） |
| interop.py | 互操作（与其他系统的协议适配） |
| logging.py | 日志（统一格式/级别） |
| paths.py | 路径解析（Data/ 根、各子系统目录约定） |
| schemas/chat.py | 对话 schema |
| security.py | 安全工具（信任根/校验） |
| token_estimate.py | token 估算（估算量不入账原则） |
| tooling.py | 工具基础设施（注册/参数校验） |
| watchdog.py | 看门狗（子进程/服务健康监测） |

---

## 第四部分 14 服务注册清单（装配层实录）

| 注册名 | 实现 | 能力（capability） |
|---|---|---|
| storage | adapters/storage/pool.py | store_file/read_file_content/find_config_file/delete_file/get_store/load_app_settings |
| settings | adapters/io/app_settings.py | load_app_settings |
| crypto | adapters/crypto/keystore.py | is_enabled/encrypt_bytes/decrypt_bytes |
| models | adapters/model/provider.py | create_stream/is_model_file_capable/file_handling_mode/model_supports_files |
| gui | adapters/gui/automation_orchestrator.py | （automate 入口） |
| usage | services/ops/token_usage.py | check_quota/record_usage |
| usage_ledger | services/ops/token_ledger.py | （Token 账本） |
| scheduler | services/ops/engine.py | （调度引擎） |
| conversations | services/chat/conversation_store.py | （会话存取） |
| game | domain/roleplay/game_service.py | award_chat_xp/award_plan_xp/has_item/unlock_item/purchase_item |
| affinity | domain/roleplay/affinity_engine.py | （好感度） |
| roleplay | domain/roleplay/character.py | roleplay_api |
| memory | domain/memory/memory_writer.py | memory_api |
| evolution | services/evolution/registry.py | evolution_api |
| agent | services/agent/core.py | （Agent 执行） |

**注意**：usage 注册的 record_usage 指向 _usage_record（装配层内部包装），体现"估算量不入账、provider 真实量落库"的计量原则。



# P.A.L.M 系统架构白皮书（续一：数据流/Agent 框架/前端/部署）

> 承接《系统架构白皮书》第一篇（架构哲学/分层/基础设施/服务清单）。本篇覆盖：核心数据流（一次对话全链路、工具调用、记忆写入）、Agent 框架内部架构、前端架构、部署拓扑、可观测性。

---

## 第五部分 核心数据流

### 5.1 一次对话的全链路（stream）

```
用户输入（前端对话页 / pywebview 桥接）
  → POST /api/chat（FastAPI 网关）
  → chat 服务（services/chat/chat_service.py）
    → container.get("conversations") 载入会话上下文（历史轮次）
    → container.get("roleplay") 注入人格与好感度（persona + affinity + dynamics）
    → container.get("memory") 注入记忆（core/vector/archived，token_budget 裁剪）
    → container.get("models").create_stream(...) 发起流式对话（provider → tokenhub → DeepSeek）
  → 流式响应事件经 transport/SSE 推送前端（实时计时展示）
  → 工具调用时：guardrail 裁决 → permission 授权 → 工具执行 → 结果回注模型
  → done 钩子：经验/星砂结算（game.award_chat_xp）→ 用量记账（usage_ledger）→ 记忆写入（memory）
  → 轨迹记录（agent.trace）
```

### 5.2 工具调用链路（含安全裁决）

```
模型输出工具意图（原生 FC / ReAct 解析）
  → 工具匹配（tool_matcher：名称/参数 schema 校验）
  → 参数 schema 自愈（P2：缺参补默认、错型纠正；失败自动重试）
  → 裁决引擎（guardrail 5 档：允许/拒绝/追问/降权/阻断；AI 档无回调 fail-closed）
  → 权限引擎（permission：敏感能力查授权，未授权发 ask_user 事件）
  → 事件下发（eventbus 发布工具调用事件，前端实时计时展示）
  → 执行（工具实现；代码类经 code_guard + 沙箱；联网类经 net 门面）
  → 结果回注（工具输出进上下文，估算 token）
  → 反思闸门（P3：回答成立性自检，不成立则重试/澄清）
```

### 5.3 ask_user 交互闭环（防死锁设计）

- ask_user 事件**即时推送**（不等模型续轮）。
- 事件携带 **id**；前端应答按 id 回填。
- 守卫场景（run_code 守卫、提问工具）共享同一应答通道。
- 评测客户端自动应答（e2e 不卡死）。
- 历史缺陷：事件缺 id 致应答死锁 → 修复；即时推送根治 run_code 守卫死锁。

### 5.4 记忆写入链路

```
对话完成 → memory_writer
  → 事实抽取（只存事实、不存语气）
  → 污染检测（全局语气污染检测：角色语气不写入长期记忆）
  → core_memory（核心记忆，权重高）/ vector_memory（语义向量，chroma/bge）
  → archived_memory（归档）
  → token_budget 校验（超预算裁剪/摘要化）
  → 情绪标记（emotion 五因子，E_enc 仅 v≥0）
```

### 5.5 用量计量链路

```
模型响应（provider 返回真实 token 明细：prompt/completion/total）
  → token_ledger 落库（provider 口径）
  → 估算量（token_estimate）不显示不入账（防虚增）
  → check_quota（配额校验，超限拦截）
  → 前端用量面板展示（明细页不再空白）
```

---

## 第六部分 Agent 框架内部架构

### 6.1 执行模式

| 模式 | 解析器 | 执行器 | 适用 |
|---|---|---|---|
| 原生 FC | native_parse | native_runner/_native_execution | 模型支持 function-calling |
| ReAct | react_parser | agent_react_mixin | 文本协议推理 |
| 规划 | plan_engine | agent_execution_mixin | 复杂任务（先计划后执行，失败自动重规划） |

三模式共用：prompt 模板（agent_prompt_mixin/prompt_templates）、人格注入（persona）、完成闸门（completion_gate）、轨迹（trace）、schema（schemas）。

### 6.2 规划引擎（plan_engine）

- 流程：任务 → 计划生成（结构化输出 P5）→ 分步执行 → 步骤失败自动重规划 → 完成。
- plan_once 回连：单次计划执行完成后回连结算（game.award_plan_xp）。
- 与原生 FC 深度集成（空 thought 事件透传曾致 NoneType 崩溃，已修复——事件需归一）。

### 6.3 反思与压缩（P3/P4）

- 反思自检（completion_gate）：回答前自检"是否真的回答了用户问题"；不成立 → 补充/重试/澄清。
- 上下文真压缩（P4）：旧轮次摘要化，native/react/规划共用；压缩后上下文 token 受控。

### 6.4 工具体系（tools/ + tool_base + tool_matcher）

- 100+ 工具，运行时注册（register_tool/unregister_tool）。
- 分类：文件处理、网络、代码执行（code_guard + 沙箱）、GUI（uia_operate/executor/OCR）、语音、游戏、搜索（ChineseDictTool 等）。
- 工具调用事件前置下发（前端实时计时展示输入）。
- 工具失败重试 + schema 自愈。

### 6.5 双引擎遗留（dual/）

历史"本地自研 + 委托"双引擎目录残留，不参与装配。当前仅本地自研引擎生效。

---

## 第七部分 前端架构

### 7.1 结构

```
frontend/
├── shell.html              # 外壳（承载 screens）
└── ui/                     # 共享组件
    └── ...                 # 11 个 screen 页面（对话/总览/存储/用量/商城/保险库/设置/...）
```

### 7.2 关键设计

- 原生 ES Modules，无构建链（无 webpack/vite 产物依赖；开发期 Vite 5173）。
- 每界面一文件（12 html + ui 共享基础）。
- 去主板隐喻：控制台/主板视图已移除，改系统总览中枢。
- 事件流：SSE 接收流式响应与工具调用事件（运行中实时计时、输入展示）。
- ask_user：弹出式问答（按 id 应答）。
- 桥接层：pywebview 中经 window.pywebview.api 调用后端（PALM 桥接层封装）。
- 桌面部件（widget）：glass_clock 等时间组件经桥接层取数（曾排查数据获取 bug——通过 PALM 桥接层定位调用链路）。

### 7.3 前后端契约

- HTTP API：FastAPI 路由（历史 163 端点全量扫描无 500）。
- SSE：/events 等流式端点。
- 双通道：普通请求 + 事件流并行。

---

## 第八部分 部署拓扑

### 8.1 进程布局

```
[pywebview 桌面壳] ←加载→ [前端 12 页]
        │ window.pywebview.api 桥接
        ▼
[FastAPI 后端 :8005]（uvicorn，装配 build_app()）
   ├── 云端 LLM（tokenhub → DeepSeek）[出网经 net 门面]
   ├── 本地 Qwen3-TTS :19300（可选，自动拉起）
   ├── STT 子进程 :19500（独立 venv，可选）
   ├── GSV（GPT-SoVITS 自包含运行时，启动即拉起）
   ├── CosyVoice（venv_cosyvoice）
   └── 数据目录 Data/（storage_pool/记忆/角色/游戏/配置/审计）
```

### 8.2 环境隔离

| venv | 用途 |
|---|---|
| venv_runtime | 主运行时（后端 + palm 库） |
| venv_cosyvoice | CosyVoice（torch cu128，Blackwell 配方） |
| venv_gsv | GPT-SoVITS 自包含运行时 |
| .venv-qwen-tts | Qwen3-TTS 服务（自动拉起） |
| .venv-stt | STT 推理引擎（独立子进程） |

### 8.3 配置驱动（.env）

- 服务：HOST/PORT/CORS_ALLOW_ORIGINS。
- 语音：QWEN_TTS_API_URL/AUTO_LAUNCH/MODEL_DIR/MODEL/QUANTIZE/VOICES_DIR。
- STT：STT_ENABLED/AUTO_LAUNCH/API_URL/SAMPLE_RATE/VAD/ASR/KWS 路径。
- 模型：provider/base_url/api_key（tokenhub.tencentmaas.com，deepseek-v4-flash/pro 等）。
- 缺省值内置，可直接启动；语音/STT 未配置时优雅降级。

---

## 第九部分 可观测性与运维

### 9.1 观测点

- 日志：统一 logging（palm/_core/logging.py）。
- 轨迹：agent trace（运行轨迹追踪，P5）。
- 遥测：usage_ledger（Token 账本）、gui_metrics（GUI 执行指标）。
- 审计：安全审计报告、外部引用核实。
- 看门狗：watchdog 监测子进程/服务健康。
- 保洁：housekeeping 定期清理。

### 9.2 健康检查与自测

- 端点全量扫描（163 端点无 500）。
- `python -m mentalcore.selftest`（心智核心自检）。
- `python -m mentalcore.exo.selftest`（外骨骼自检，4 测）。
- 单元测试（14 服务相关，7/8 通过基线）。
- e2e（8012 端口）。

### 9.3 容错哲学

- 装配降级：任何服务注册失败 → 打印降级信息 → 容器缺失归一 None → 业务判空。
- 运行降级：语音/STT 缺模型 → /api/status 报缺失，不阻断启动。
- 安全降级：crypto 指纹失败 → 仅置禁用；guardrail AI 档无回调 → fail-closed deny；net 未配置 → 拒绝出网。

---

## 第十部分 架构演进约束（复刻须知）

1. **禁止越层依赖**：domain 不得 import services/adapters；services 可依赖 domain 与 ports；adapters 不得依赖 services。bootstrap 是唯一允许"知道所有模块"的地方。
2. **禁止全局状态**：业务模块零注册、零全局状态；一切经容器。
3. **缺失归一**：container.get 缺失返回 None；capability 缺失返回 None；业务必须判空降级。
4. **命名纪律**：能力键与旧 registry 服务名对齐（container.get("storage") 等保持语义一致）。
5. **契约强制**：Port ABC 子类必须实现全部抽象方法（ABC 强制验证）。
6. **装配幂等**：build_app() 重复调用不重复注册。



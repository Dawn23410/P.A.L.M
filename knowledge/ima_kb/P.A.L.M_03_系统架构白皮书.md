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



# P.A.L.M 系统架构白皮书（深度扩充：源码级解析与装配细节）

> 承接《系统架构白皮书》正文。本部分提供关键基础设施的源码级解析（container/guardrail/net/eventbus/agent 核心），以及装配层细节、Agent 依赖注入协议清单。

---

## 扩充章 A：服务容器源码级解析（container.py 实录）

### A.1 ServiceHandle（服务句柄）

```python
class ServiceHandle:
    def __init__(self, name, impl, capabilities=None):
        self._capabilities = capabilities or {}

    @property
    def capabilities(self) -> dict:
        """显式注册的能力 + 实现对象的方法属性（方法名即能力键）。"""
        merged = dict(self._capabilities)
        for attr in dir(self._impl):
            if attr.startswith("_"): continue
            value = getattr(self._impl, attr)
            if callable(value):
                merged.setdefault(attr, value)
        return merged

    def capability(self, name):
        """取能力：先查显式注册，再回退实现对象的方法属性；缺失返回 None。"""
        if name in self._capabilities:
            return self._capabilities[name]
        return getattr(self._impl, name, None)
```

**关键设计**：
1. **双源能力解析**：能力键先查显式注册的 capabilities 字典，再回退实现对象的方法属性——业务代码可以直接 `handle.capability("store_file")` 而无需关心该能力是显式注册还是方法。
2. **缺失归一**：两源都无 → None（不是抛异常）——业务侧判空降级。
3. **capabilities 属性**：合并显式 + 方法属性（供外部枚举服务能力，如系统总览中枢展示）。

### A.2 Container（容器）

```python
class Container:
    def register(self, name, impl, capabilities=None) -> ServiceHandle: ...
    def get(self, name) -> ServiceHandle | None: ...   # 缺失返回 None
    def all(self) -> list[ServiceHandle]: ...
    def names(self) -> list[str]: ...                  # 排序后的服务名

container = Container()     # 全局单例
registry = container        # 兼容别名（旧代码 from ... import registry 仍可用）
```

**关键设计**：
1. **全局单例**：库内模块经 container.get(服务名) 惰性取用，与旧 registry 同构（迁移兼容）。
2. **兼容别名 registry**：旧导入路径不破坏。
3. **CapabilitySlot**：能力槽（服务对外暴露的可调用能力，供演化服务引用）——演化引擎观察服务能力的通道。

### A.3 装配层细节（bootstrap/app.py 剩余部分实录）

- usage 服务注册时 record_usage 指向 `_usage_record`（装配层内部包装函数）——体现计量原则（真实量落账本）。
- 每个服务 try/except 包裹：storage 注册失败打印降级信息继续；crypto 失败仅置禁用；models/gui/memory 失败同样降级。
- **ContainerProxy**：build_app 返回的包装（隔离外部对容器的写操作）。

---

## 扩充章 B：裁决内核源码级解析（guardrail/engine.py 实录）

### B.1 5 档策略（Profile）

```python
class Profile(str, Enum):
    HARDLINE  = "hardline"    # 死线：默认拒绝；warn 升级为 deny（只允许显式 allow）
    STRICT    = "strict"      # 严格：默认询问；warn 保持提醒
    LOOSE     = "loose"       # 宽松：默认提醒（放行+advisory），不升级
    AI        = "ai"          # AI 兜底：默认走 AI 回调（未配置则 fail-closed 拒绝）
    WHITELIST = "whitelist"   # 白名单：默认拒绝；仅 allow 规则可放行
```

| 档位 | 无规则命中默认 | warn 动作 | 适用场景 |
|---|---|---|---|
| 死线 | 拒绝 | 升级为拒绝 | 最高危操作（删除/越权） |
| 严格 | 询问 | 保持提醒 | 敏感操作（联网/代码执行） |
| 宽松 | 提醒 | 不升级 | 低危操作（一般工具） |
| AI 兜底 | AI 回调 | — | 动态裁决（未配置回调 = fail-closed 拒绝） |
| 白名单 | 拒绝 | — | 最小化放行（仅显式 allow） |

### B.2 裁决结果（Decision）

```python
@dataclass
class Decision:
    action: str            # allow / deny / ask / warn
    reason: str = ""
    rule: Rule | None = None
    ask_message: str = ""
    ask_timeout_ms: int = 30_000   # 询问超时 30 秒
    ask_on_timeout: str = "deny"   # 超时默认拒绝（fail-closed）
```

**关键设计**：ask 询问超时默认 30 秒，超时后默认 deny（不是 allow）——询问场景也保持 fail-closed。

### B.3 规则匹配

- 规则集 RulesConfig（rules.py，pydantic 模型）。
- 按 priority 降序匹配，首条命中生效；规则内条件 AND 组合。
- 与 execute_tool_with_safety 的 adjudicator_cap 接口对齐：get_guardrail_capability() 返回 (event_type, ctx) → Decision。

---

## 扩充章 C：网卡门面源码级解析（net/__init__.py 实录）

### C.1 设计铁律

1. **本模块绝不 import httpx/requests/socket 等联网原语**——联网能力仅由"网卡砖"经 register_card(...) 注入执行器。其他砖一律经本门面请求外网。
2. **无网卡注册（或已拔出）→ 一切外网请求抛 NetworkForbidden（fail-closed）**——连 install_guard 兜住的"偷偷直连"也一并拒绝。
3. **本机回环（127.0.0.1/localhost/::1）不属外网出口，守卫放行**——保证离线时本地模型服务（Ollama 等）仍可用。

### C.2 执行器契约

```python
# 由网卡砖注入：
execute(method, url, *, headers=None, content=None, json=None,
        params=None, timeout=None, stream=False, **kw) -> httpx.Response
```
返回 httpx.Response（网卡砖是唯一持有 httpx 之处），门面原样透传。

### C.3 NetworkForbidden

无网卡注册时抛 NetworkForbidden（RuntimeError 子类）——业务侧捕获后降级（提示离线/禁用联网工具）。

---

## 扩充章 D：事件总线源码级解析（eventbus.py 实录）

- emit(event_type, payload)：同步分发，单个订阅方异常不影响其余（降级隔离）。
- subscribe(event_type, handler)：返回取消订阅函数；handler 可为同步或 async（async 用 asyncio.run 执行，保证同步 emit 语义）。
- 订阅表 + 事件审计（最近 N 条）供 BIOS 健康报告展示。
- 南桥隐喻：广播型低速通知（要结果的走北桥能力总线 get_facade 点对点调用）。

---

## 扩充章 E：Agent 核心依赖注入协议清单（core.py 实录）

Agent 类 = PromptMixin + ExecutionMixin + ReactMixin，构造函数支持核心组件依赖注入：

| Protocol | 默认实现 | 可替换 |
|---|---|---|
| MemoryProtocol | _memory_api()（记忆砖门面） | 自定义记忆实现 |
| ToolRegistryProtocol | ToolRegistry.get_registry() | 自定义工具注册表 |
| ToolMatcherProtocol | tool_matcher.get_matcher() | 自定义匹配器 |
| CompletionGateProtocol | completion_gate.get_default_gate() | 自定义完成闸门 |
| PersonaProviderProtocol | persona.create_persona_provider() | 自定义人格提供者 |
| TokenBudgetProtocol | （内置） | 自定义 token 预算 |
| PlannerProtocol | （内置规划引擎） | 自定义规划器 |

**即插即用**：实现对应 Protocol 即可替换任意一层，无需修改内核代码。关键参数：model/max_iterations(10)/deep_think(False)/model_window(128000)/user_message/max_plan_steps(8)/persona_text/character_card/conversation_id。

- 模型选择：palm.adapters.model.model_router.select_model（模型路由：flash/pro 分档）。
- 事件：schemas.AgentEvent（统一事件模型）。
- 记忆门面：get_memory_api()（未注册抛 RuntimeError——Agent 强依赖记忆）。
- 兼容导出：__all__ = ["Agent", "parse_react_output"]。


# P.A.L.M 系统架构白皮书（深度扩充一：数据流时序与部署细节）

> 承接《系统架构白皮书》正文与扩充章 A-E。本部分给出：核心流程的时序图（文字版）、部署拓扑细节、配置矩阵、运行模式详解。

---

## 扩充章 F：核心流程时序（文字版时序图）

### F.1 对话全流程时序

```
用户           前端           FastAPI          chat服务         roleplay/memory    models           guardrail/permission
 │   输入消息    │              │                │                  │               │                  │
 ├─────────────►│              │                │                  │               │                  │
 │              │  POST /chat  │                │                  │               │                  │
 │              ├─────────────►│                │                  │               │                  │
 │              │              │ 上下文组装请求  │                  │               │                  │
 │              │              ├───────────────►│                  │               │                  │
 │              │              │                │ 注入人格+记忆     │               │                  │
 │              │              │                ├─────────────────►│               │                  │
 │              │              │  stream_chat   │                  │               │                  │
 │              │              │                ├─────────────────────────────────►│                  │
 │              │              │ ◄── text/thought 事件流 ──────────────────────────┤                  │
 │              │  SSE text    │                │                  │               │                  │
 │              │◄─────────────┤                │                  │               │                  │
 │              │              │  tool_call     │                  │               │                  │
 │              │              │◄───────────────┤                  │               │                  │
 │              │              │                │  裁决+授权        │               │                  │
 │              │              │                ├───────────────────────────────────────────►│
 │              │              │                │ 执行工具          │               │                  │
 │              │              │                ├──────────────►（tools）           │                  │
 │              │              │ 结果回注 → 续轮直到完成                             │                  │
 │              │  done 事件   │                │                  │               │                  │
 │              │◄─────────────┤                │                  │               │                  │
 │              │              │                │ 结算(done钩子)    │               │                  │
 │              │              │                ├──► game.award_chat_xp / usage_ledger / memory  │
```

### F.2 ask_user 应答时序（防死锁设计）

```
系统 → 前端：ask_user 事件 {id, message}        （即时推送，不等模型续轮）
前端 → 系统：POST /api/ask-response {id, answer}
系统：按 id 回填 question_hub → 恢复被挂起的流程（run_code 守卫/提问工具）
超时：30s 无应答 → 默认 deny（fail-closed）
```

### F.3 EXO 委派时序（Boss → Worker）

```
用户 → Boss：对话消息
Boss 模型：回复正文 + ||EXO||{"goal":...,"context":...}||END||
ReplySplitter：识别 EXO 标记 → 透传 out_fields["exo"]
MentalCore.exo_broker：收到委派 → 后台线程拉起 Worker（不阻塞 Boss 回复）
Worker（WorkCore）：ReAct 循环 + 5 小魔方执行任务
  → 工具调用：tool_cube 权限闸门 → sandbox_cube 隔离执行 → comm_cube 审计
  → ||FIN|| 收尾
Worker 完成：core.receive({"exo_result": ...}, "外骨骼完成")
Boss 下一轮：按角色卡语言加工外骨骼结果 → 回复用户
```

### F.4 进化触发时序

```
观察者（observer）：监听对话/行为事件
  ├─ 闲置超时（idleMinutes=15）→ idle_orchestrator 触发自主推测
  ├─ 定时到点（schedules.json cron）→ offline_digest 生成每日简报
  └─ 习惯积累 → habit_engine 适配
决策：gate 门控（autonomyLevel）→ guardrail 裁决事件（agent.proactive）
执行：proactive 主动推送（前端展示）→ evolution_api 记录
```

### F.5 记忆写入时序

```
对话完成（done 钩子）
  → memory_writer 抽取事实（只存事实、不存语气）
  → 污染检测（语气污染拦截）
  → 写入 core_memory（高权重）/ vector_memory（向量化，bge INT8）
  → token_budget 校验（超限裁剪/摘要化）
  → archived_memory 归档冷数据
  → 情绪标记（五因子，E_enc 仅 v≥0）
```

---

## 扩充章 G：部署拓扑细节

### G.1 完整进程拓扑

```
┌─ pywebview 桌面壳 ─────────────────────┐
│  12 页前端（原生 ES Modules）           │
│  window.pywebview.api 桥接层           │
└──────────────┬─────────────────────────┘
               │ HTTP + SSE
┌──────────────▼─────────────────────────┐
│ FastAPI 后端 :8005（uvicorn）           │
│  build_app() 装配 14 服务               │
│  ├─ 对话/角色/记忆/游戏/进化/调度/计量   │
│  └─ 安全链：guardrail/permission/net    │
└──────┬──────────┬──────────┬────────────┘
       │          │          │
  出网（net门面）  │   本地子进程
       ▼          │          ▼
  tokenhub ────►  │   Qwen3-TTS :19300
  (DeepSeek等)    │   STT :19500
                  │   GSV（启动即拉起）
                  │   CosyVoice（venv）
                  ▼
            本地数据 Data/（存储池/记忆/角色/游戏/配置/审计）
```

### G.2 独立态说明

- 每个服务可独立运行（独立态兼容性修复：确保项目可启动且核心端点全绿）。
- mock 模式：禁用 Agent 执行仅保留对话（缝合引擎 mock 通道可用）。

### G.3 启动顺序建议

1. 装配检查：build_app() 幂等（14 服务注册）。
2. 可选服务：Qwen3-TTS（AUTO_LAUNCH）、STT（AUTO_LAUNCH）、GSV（启动即拉起）。
3. FastAPI 网关启动（uvicorn）。
4. 前端：Vite dev（5173）或静态托管；pywebview 桌面壳加载。

---

## 扩充章 H：配置矩阵（.env × settings.json 联动）

| 配置 | 来源 | 作用 |
|---|---|---|
| HOST/PORT | .env | 服务监听 |
| CORS_ALLOW_ORIGINS | .env | 跨域 |
| apiUrl | settings.json | 前端连后端 |
| model/flashModel/proModel | settings.json | 模型选择（select_model 路由） |
| customProviders | settings.json | 供应商/端点/模型池 |
| agentToolMode/PlanningMode | settings.json | Agent 行为 |
| runMode | settings.json | 运行模式（mode_resolver） |
| autonomyLevel | settings.json | 进化自主等级（gate） |
| daily/monthlyTokenLimit | settings.json | 配额（check_quota） |
| QWEN_TTS_* | .env | 本地 TTS |
| STT_* | .env | 语音识别 |
| MENTALCORE_API_KEY | mentalcore/.env | 心智核心模型端点 |

**联动原则**：.env 管进程级（端口/服务开关/路径），settings.json 管应用级（模型/行为/UI）；缺省值内置可直启。

---

## 扩充章 I：运行模式详解（mode_resolver）

| 模式 | 能力 |
|---|---|
| max（全功能） | 对话/工具/规划/进化/语音/GUI 全开 |
| min（最小） | 核心对话 + 基础工具 |
| mock（隔离） | 仅对话（缝合引擎/心智核心 mock），禁 Agent 执行——测试/演示 |

模式切换经 mode_resolver 动态应用（不影响装配，仅关停能力出口）。


# P.A.L.M 系统架构白皮书（深度扩充二：API 端点详表与数据模型）

> 承接扩充章 F-I。本部分给出后端 API 端点详表（按领域）、数据模型清单、以及历史端点证据（163 端点扫描、路由证据）。

---

## 扩充章 J：API 端点详表（按领域重建）

> 说明：以下端点清单基于路由证据（brick_inventory.json routes、前端 api.js、历史提交）重建，具体路径以源码为准，用于复刻时的路由规划参考。

### J.1 对话与 Agent（核心）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/chat | 对话流式（SSE） |
| GET | /api/tools | 工具列表 |
| POST | /api/tools | 注册工具 |
| DELETE | /api/tools/{name} | 注销工具 |
| POST | /api/ask-response | ask_user 应答（id 回填） |
| POST | /api/run | Agent 单次运行 |
| GET | /api/events | SSE 事件长连接 |
| POST | /api/plan | 规划引擎触发 |
| POST | /api/dual-run | 双引擎运行（遗留） |
| GET | /api/dual-status | 双引擎状态（遗留） |
| POST | /api/dual-intervene | 双引擎干预（遗留） |

### J.2 角色与好感度

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/characters | 角色列表 |
| GET | /api/characters/{id} | 角色详情 |
| POST | /api/characters | 创建/更新角色 |
| DELETE | /api/characters/{id} | 删除角色（级联） |
| POST | /api/characters/import | Markdown 技能导入 |
| GET | /api/affinity | 好感度查询 |
| POST | /api/affinity | 好感度更新 |
| GET | /api/characters/{id}/dynamics | 角色动态数据 |

### J.3 用量与配额

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/usage | 用量明细（provider 口径） |
| GET | /api/usage/quota | 配额状态 |
| POST | /api/usage/record | 记账（真实量） |

### J.4 存储与文件

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/storage | 存储状态 |
| POST | /api/storage/file | 写文件 |
| GET | /api/storage/file | 读文件 |
| DELETE | /api/storage/file | 删文件（vault 拦截） |
| GET | /api/storage/health | 健康（quota/lifecycle/audit） |
| GET | /api/settings | 读设置 |
| POST | /api/settings | 存设置（文件锁重试） |

### J.5 游戏

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/game | 游戏状态 |
| GET | /api/game/shop | 商城 |
| POST | /api/game/purchase | 购买（星砂） |
| GET | /api/game/tasks | 每日任务 |
| POST | /api/game/match | 对局（五子棋） |

### J.6 语音

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /api/tts | TTS 合成（facade） |
| GET | /api/stt/status | STT 状态（缺模型报缺失） |
| POST | /api/stt/recognize | STT 识别 |
| POST | /api/voice/session | 语音会话 |

### J.7 系统与运维

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/system | 系统状态（14 服务） |
| GET | /api/vault | 保险库列表 |
| POST | /api/vault/restore | 恢复文件 |
| DELETE | /api/vault/{id} | 彻底删除 |
| GET/POST | /api/scheduler | 定时任务 |
| GET | /api/evolution | 进化状态 |
| GET | /api/memory | 记忆查询 |
| POST | /api/memory | 记忆写入 |
| GET | /api/monitor | 监控（看门狗/裁决审计） |
| GET | /api/mcp | MCP 能力管理 |

### J.8 端点质量基线

- 历史：全量链路扫描 163 端点无 500（仅依赖缺失降级 503）。
- 复刻要求：所有端点捕获异常；错误分类（400 参数错/403 授权/404 缺失/503 降级/500 禁止裸崩）。

---

## 扩充章 K：数据模型清单（全量）

### K.1 领域对象

| 对象 | 文件 | 字段（关键） |
|---|---|---|
| 角色卡 | characters/*.json | name/description/personality/first_mes/mes_examples/... |
| 会话 | 对话记录/*.json | id（十六进制）/messages/timestamp |
| 游戏状态 | game_state.json | total_exp/currency/daily_tasks/unlocked_items/... |
| 权限 | permissions.json | capability/granted/scope/updated_at |
| 设置 | settings.json | 见扩充章 C 全表 |
| 调度 | schedules.json | job_id/cron/action/enabled/last_run |

### K.2 事件对象

| 事件 | 负载 |
|---|---|
| text | {text} |
| thought | {text} |
| tool_call | {name, args, status, duration_ms} |
| ask_user | {id, message, timeout_ms} |
| verdict | {action, reason, rule} |
| voice.reply_ready | {text, voice_text} |
| voice.speaker | {speaker, similarity, is_match, text?} |
| voice.tts_audio_chunk | {seq, text, audio(bytes)} |
| entity.deleted | {entity_type, entity_id} |
| affinity.settled | {character_id, base, dynamics, delta} |

### K.3 传输包（mentalcore）

TransportPacket {body, fields}；fields 内含 data（||DATA|| 过滤后）/exo（||EXO|| 透传）。

---

## 扩充章 L：架构评审记录（终极架构决策依据）

### L.1 为什么推翻主板体系

1. **复杂度失控**：硬件隐喻（主板/砖块/总线/芯片/BIOS/看门狗/信任根/热插拔/版本回滚）带来大量概念与胶水代码——30 砖物理解耦 + palm_sdk + 网关的复杂度已超出隐喻收益。
2. **耦合未解**：palm_sdk 与砖双向依赖；manifest/registry 分散。
3. **契约缺失**：砖间调用靠约定而非强制契约（无 ABC 校验）。

### L.2 终极架构的核心改进

1. **契约强制**：15 Port ABC + 强制验证——依赖方向可 lint 校验。
2. **容器收敛**：container 取代 registry——装配唯一、取用惰性、缺失归一。
3. **隐喻清除**：无主板/Brick/BusType/Manifest——用软件工程语言替代硬件隐喻。
4. **SDK 退役**：palm_sdk 功能收敛进 palm/_core/——减少一层间接。
5. **最小颗粒度**：24 砖全拆入 palm 库——按职责分层（ports/domain/services/adapters）。

### L.3 评审流程（可复刻）

1. 架构文档（终极架构 v0.2）编写。
2. 评审（用户审阅 + 意见修订）。
3. 评审通过 → 落 P1（契约层先行）。
4. 分层实现（ports → _core → adapters → domain → services → bootstrap）。
5. 全量入仓 + 归档旧体系。


# P.A.L.M 系统架构白皮书（深度扩充三：安全架构与规则体系）

> 承接扩充章 F-L。本部分深入安全架构：裁决规则体系（rules.py 设计）、权限引擎流程、网卡门面实现细节、保险库机制、以及安全链 H1-H4/M5/M7。

---

## 扩充章 M：裁决规则体系（guardrail/rules.py 设计）

### M.1 规则模型

```python
# 规则结构（pydantic 模型）
class Rule:
    id: str                    # 规则 id
    priority: int              # 优先级（降序，首条命中生效）
    event_type: str            # 事件类型（tool_call/web_access/code_exec/...）
    conditions: list           # 条件（AND 组合）
    action: str                # allow / deny / warn / ask
    reason: str                # 命中说明
    ask_message: str           # ask 时的问题

class RulesConfig:
    rules: list[Rule]          # 规则集
```

### M.2 规则示例（复刻参考）

```yaml
rules:
  - id: deny_format_disk
    priority: 100
    event_type: tool_call
    conditions: [{tool: "file_delete", path_match: "C:\\"}]
    action: deny
    reason: 禁止删除系统盘文件
  - id: ask_run_code
    priority: 50
    event_type: tool_call
    conditions: [{tool: "run_code"}]
    action: ask
    ask_message: 确认执行代码？
  - id: warn_web_search
    priority: 10
    event_type: web_access
    conditions: [{url_prefix: "http"}]
    action: warn
    reason: 外网访问需注意数据安全
```

### M.3 裁决流程（5 档 × 规则集）

```
事件到达 → 按 priority 降序匹配规则
  → 首条命中：按规则 action 处理（allow/deny/warn/ask）
  → 无命中：按 Profile 兜底
      HARDLINE → deny（warn 升级 deny）
      STRICT → ask
      LOOSE → warn（放行+advisory）
      AI → AI 回调（未配置 fail-closed deny）
      WHITELIST → deny（仅显式 allow）
  → Decision 返回（action/reason/rule/ask_message/ask_timeout_ms=30000/ask_on_timeout=deny）
```

### M.4 裁决接入点（get_guardrail_capability）

```python
# 返回 (event_type, ctx) -> Decision 的裁决函数
# 接入：execute_tool_with_safety（工具）、agent.proactive（主动推送）、
#      ChineseDictTool（联网）、进化动作
```

---

## 扩充章 N：权限引擎流程（permission.py 设计）

### N.1 授权模型

```python
permission = {
  "capability": "file_delete",
  "granted": false,          # 未授权
  "scope": "ask_once",       # 询问策略：ask_once/always_allow/always_deny
  "updated_at": "...",
  "history": []              # 授权历史（审计）
}
```

### N.2 授权流程

```
敏感能力请求
  → 查 permissions.json
  → 已授权（always_allow）→ 放行
  → 未授权 → 发 ask_user（携带 capability 信息）
  → 用户允许 → granted=true（按 scope 持久化）
  → 用户拒绝 → deny + 记录
  → ask 超时 → 默认 deny（fail-closed）
```

### N.3 与裁决引擎的协同

```
工具调用链：
  guardrail 裁决（规则层，事件级）→ 通过
  → permission 授权（意图层，用户级）→ 通过
  → 执行
任何一层拒绝 → 拦截（原因分层记录）
```

---

## 扩充章 O：网卡门面实现细节（net/）

### O.1 组件

| 组件 | 职责 |
|---|---|
| register_card(executor) | 网卡砖注入执行器（唯一持有 httpx 处） |
| get_network_executor() | 取执行器（无则 None） |
| NetworkForbidden | 无网卡出网异常（fail-closed） |
| install_guard | 兜住"偷偷直连"（未注册网卡时任何联网原语调用被拒） |
| 回环放行 | 127.0.0.1/localhost/::1 不属外网（本地模型服务可用） |

### O.2 铁律再述

1. 门面自身不 import httpx/requests/socket。
2. 无网卡注册 → 一切外网请求抛 NetworkForbidden。
3. 回环不拦截（离线时 Ollama 等本地服务可用）。

### O.3 复刻实现要点

```python
class NetworkForbidden(RuntimeError): ...

_executor = None  # 网卡砖注入

def register_card(executor): global _executor; _executor = executor
def get_network_executor(): return _executor

def network_get(url, **kw):
    if _executor is None: raise NetworkForbidden(...)
    return _executor("GET", url, **kw)
```

---

## 扩充章 P：保险库机制（redundancy/vault.py + recycle.py）

### P.1 vault（文件保险库）

```
delete_file 请求
  → safe-delete 守卫检查
  → 文件移入 vault（重命名保留原路径元数据）
  → 前端保险库面板可见
  → restore：从 vault 移回原路径
  → purge：彻底删除（二次确认）
```

### P.2 recycle（回收站）

- 系统级回收站适配（删除走 OS 回收站语义）。
- 与 vault 的关系：vault 是应用级保险库（业务文件），recycle 是系统级兜底。

### P.3 删除链路完整流程

```
业务删除 → safe-delete 守卫（本机 rm 守卫）→ vault 拦截 → 可恢复
  → 恢复：vault restore
  → 彻底：vault purge（二次确认）
  → 跨砖级联：entity.deleted 事件 → 相关砖级联清理
```

---

## 扩充章 Q：安全链 H1-H4 / M5 / M7（历史审计基线）

| 编号 | 安全链 | 对应实现 |
|---|---|---|
| H1 | 输入净化 | 工具参数 schema 校验自愈/注入面修复 |
| H2 | 越权防护 | 权限引擎（敏感能力须授权） |
| H3 | 代码隔离 | 沙箱 subprocess 隔离（fail-closed） |
| H4 | 数据保护 | 加密落盘（SM4）+ vault 保险库 |
| M5 | 出网管控 | 网卡门面（唯一出口） |
| M7 | 运行期防御 | 裁决 5 档 + 看门狗 + 审计 |

**审计要求**：
- 外部引用网络核实（库名/函数名/写法）。
- 每次安全增强补审计记录。
- 红队测试（prompt 注入样例库）。

---

## 扩充章 R：事件协议完整规范

### R.1 事件类型与负载（协议级）

| 事件 | 方向 | 负载 | 时序 |
|---|---|---|---|
| text | 模型→前端 | {text} | 流式 |
| thought | 模型→前端 | {text} | 流式（空归一） |
| tool_call | 模型→前端 | {name, args, status, duration_ms} | 执行前下发 |
| ask_user | 系统→前端 | {id, message, timeout_ms} | 即时推送 |
| verdict | 系统→前端 | {action, reason, rule} | 裁决后 |
| proactive | 系统→前端 | {text, source} | 主动推送 |

### R.2 事件总线事件（进程内）

entity.deleted / affinity.settled / tool.registered / tool.unregistered / voice.*（8 种）/ voice.reply_ready / voice.speaker / voice.tts_audio_chunk。

### R.3 ask_user 应答协议

```
下发：{type: "ask_user", id: "q-123", message: "...", timeout_ms: 30000}
应答：POST /api/ask-response {id: "q-123", answer: "..."}
超时：30s → 默认 deny（fail-closed）
重入：应答后恢复挂起流程（守卫/提问工具）
```


# P.A.L.M 系统架构白皮书（深度扩充四：接口设计原则与演进方向）

> 承接扩充章 M-R。本部分给出：接口设计原则（Port/capability/事件三范式）、架构演进方向、以及与主流架构的对比。

---

## 扩充章 S：接口设计三范式

### S.1 Port 契约（静态接口）

```
用途：定义能力契约（ABC 强制）
范式：
  class StoragePort(ABC):
      @abstractmethod
      def store_file(self, key: str, data: bytes) -> None: ...
  # 适配器实现 Port，装配层注册进容器
原则：
  - 可独立 import（无运行时依赖）
  - 子类必须实现全部抽象方法（ABC 校验）
  - 语义稳定（跨版本不变）
```

### S.2 capability 门面（动态接口）

```
用途：服务能力暴露（运行时取用）
范式：
  handle = container.get("storage")
  fn = handle.capability("store_file")   # 缺失归一 None
  if fn: fn(key, data)
原则：
  - 缺失归一（None 不抛异常）
  - 双源解析（显式注册 + 方法属性）
  - 键名语义对齐旧 registry（迁移兼容）
```

### S.3 事件（异步广播接口）

```
用途：广播型解耦（不要求结果）
范式：
  eventbus.subscribe("entity.deleted", handler)
  eventbus.emit("entity.deleted", payload)
原则：
  - 同步分发 + 降级隔离（单订阅方异常不影响其余）
  - 事件类型集中常量（避免魔法字符串）
  - 审计留痕（最近 N 条）
```

**三范式分工**：要契约用 Port、要能力用 capability、要通知用事件——各司其职，互不替代。

---

## 扩充章 T：架构演进方向（从终态推演）

### T.1 短期演进

| 方向 | 说明 |
|---|---|
| 好感度解耦 | affinity 从 roleplay 域独立（用户议题） |
| 契约扩展 | 新增 Port（如 voice_port 细分） |
| 事件规范化 | 更多业务事件（进化/游戏/记忆） |
| 监控增强 | 遥测指标接入 watchdog |

### T.2 中期演进

| 方向 | 说明 |
|---|---|
| agent 对标主流 | LangChain/OpenAI Agents/Claude SDK 能力对照 |
| 多模态 | 图像/文档理解（models file 能力已预留） |
| 插件市场 | MCP/技能卡生态 |
| 多端 | 数据同步（加密） |

### T.3 长期演进

| 方向 | 说明 |
|---|---|
| 全本地化 | 本地 LLM + 本地 TTS 全离线 |
| 联邦记忆 | 多设备记忆同步 |
| 自主协作 | 多 Agent 协作（Worker 网络） |

---

## 扩充章 U：与主流架构对比（诚实对比）

### U.1 依赖注入 vs 服务容器

| 维度 | P.A.L.M container | 主流 DI 容器（如 FastAPI Depends） |
|---|---|---|
| 粒度 | 服务级（14 个） | 函数级 |
| 语义 | capability 门面 | 依赖解析 |
| 缺失处理 | 归一 None（业务判空） | 报错 |
| 迁移 | 旧 registry 兼容 | — |

**定位**：container 是轻量服务定位器（Service Locator），非完整 DI——够用且迁移友好。

### U.2 Port 契约 vs 接口抽象

| 维度 | P.A.L.M Port | 主流（Protocol/Trait） |
|---|---|---|
| 强制 | ABC 强制验证 | 结构协议 |
| 数量 | 15（按能力域） | 按需 |
| 独立 | 可独立 import | 依框架 |

**定位**：Port 是项目级契约（与旧体系对齐），非框架级抽象。

### U.3 事件总线 vs 消息队列

| 维度 | P.A.L.M eventbus | MQ（如 Redis Stream） |
|---|---|---|
| 范围 | 进程内 | 跨进程 |
| 可靠性 | 尽力（降级隔离） | 持久化 |
| 复杂度 | 极低 | 高 |

**定位**：单机系统用进程内事件总线足够；跨进程需求才需 MQ（当前无）。

### U.4 裁决引擎 vs 权限框架

| 维度 | P.A.L.M guardrail | 权限框架（如 CASL） |
|---|---|---|
| 维度 | 事件级规则 + 5 档 Profile | 主体-资源-动作 |
| 兜底 | fail-closed（4 档默认拒） | 默认允许（通常） |
| 动态 | AI 档回调 | 静态规则 |

**定位**：guardrail 是"安全裁决"而非"权限管理"——与 permission（用户授权）互补。

---

## 扩充章 V：架构原则速查卡（复刻者贴墙版）

1. **依赖单向**：ports ← domain/services/adapters ← bootstrap。
2. **容器取用**：container.get(名).capability(键)，缺失归一 None。
3. **装配唯一**：bootstrap/app.py 唯一注册点，幂等。
4. **适配器隔离**：只有适配器碰外部 IO。
5. **门面收敛**：出网走 net、裁决走 guardrail、语音走 facade。
6. **事件解耦**：广播用 eventbus（要结果用 capability）。
7. **契约先行**：新能力先 Port 后实现。
8. **fail-closed**：未配置即拒绝（裁决/网卡/沙箱）。
9. **删除可恢复**：vault 拦截。
10. **计量真实**：provider 落账，估算不入账。
11. **规范硬约束**：函数≤50 行/文件≤500 行/单一职责。
12. **归档先行**：重大变更前归档。


# P.A.L.M 系统架构白皮书（深度扩充五：文件级目录与依赖矩阵）

> 承接扩充章 S-V。本部分给出：palm/_core 文件级目录展开、服务依赖矩阵、以及事件-服务-数据对照表。

---

## 扩充章 W：palm/_core 文件级目录展开

### W.1 _core 全量文件清单（20 模块）

| 模块 | 文件 | 关键内容 |
|---|---|---|
| config | config.py | 配置加载（.env/默认值） |
| container | container.py | ServiceHandle/Container/CapabilitySlot/registry 别名 |
| emotion | emotion.py | 五因子情绪模型 |
| eventbus | eventbus.py | emit/subscribe + 事件常量 + 审计 |
| gateway | gateway.py | 旧 registry 能力承接（17 文件收敛） |
| guardrail | guardrail/engine.py + rules.py | 5 档 Profile + Rule/RulesConfig/Decision |
| housekeeping | housekeeping.py | 后台保洁 |
| interop | interop.py | 互操作（get_memory_api 等） |
| logging | logging.py | 日志 |
| net | net/__init__.py | 网卡门面（register_card/NetworkForbidden） |
| paths | paths.py | 路径解析（Data/ 约定） |
| permission | permission.py | 权限引擎（授权模型/流程） |
| redundancy | redundancy/recycle.py + vault.py | 回收站 + 文件保险库 |
| schemas | schemas/chat.py | 对话 schema |
| security | security.py | 安全工具（信任根） |
| token_estimate | token_estimate.py | token 估算（不入账） |
| tooling | tooling.py | 工具基础设施 |
| transport | transport.py | 传输层（事件/控制码） |
| watchdog | watchdog.py | 看门狗 |

### W.2 adapters 文件级

| 适配器 | 文件 | 能力 |
|---|---|---|
| storage | pool.py | 文件池 6 接口 |
| io | app_settings.py | settings 读写 |
| crypto | keystore.py + operations.py | 指纹 + 加解密 |
| model | provider.py + model_router.py | 流式 + 模型路由 |
| gui | automation_orchestrator.py | automate 入口 |
| display | （壁纸/悬浮） | 显示层 |

### W.3 domain 文件级

| 子域 | 文件 | 能力 |
|---|---|---|
| roleplay | character/persona/affinity_engine/affinity_store/affection/dynamics_engine/pollution_guard/game_service/xp/state/import_skill（11） | 角色全套 |
| memory | core_memory/archived_memory/vector_memory/memory_writer/token_budget/weights/base/memory（9） | 记忆全套 |
| planning | planner/schemas（2） | 规划 |
| evolution | proactive/idle_orchestrator/offline_digest/habit_engine/fallback_engine/background_tasks（6） | 进化 |

### W.4 services 文件级

| 服务组 | 文件 | 能力 |
|---|---|---|
| agent | core + 7 协议/mixin + native 3 + plan/react + tool 3 + persona/gate/hub/trace/schemas/code_guard + tools/（9 文件）+ dual/ | Agent 全套 |
| chat | chat_service/conversation_store/hub/engine/build_corpus/corpus/core（8） | 会话 |
| evolution | registry/loader/observer/gate/slot_store/skill_registry/_injection/_io/schemas（9） | 进化服务 |
| ops | engine/cron/mode_resolver/game_detector/_settings/store/token_ledger/token_usage（9） | 调度/计量 |

---

## 扩充章 X：服务依赖矩阵

### X.1 服务依赖关系（谁依赖谁）

| 服务 | 依赖（container.get） | 说明 |
|---|---|---|
| chat | conversations/roleplay/memory/models | 会话编排 |
| agent | memory/models/usage（间接） | Agent 执行 |
| usage | usage_ledger | 计量 |
| scheduler | evolution（proactive 能力） | 定时取推送 |
| roleplay | affinity（好感度） | 角色联动 |
| game | affinity/xp | 结算 |
| evolution | guardrail（裁决） | 主动动作 |

### X.2 依赖方向铁律

```
domain 不依赖 services/adapters
services 可依赖 domain + ports
adapters 不依赖 services
bootstrap 唯一知道所有模块
业务经 container 取用（不直接 import 其他服务）
```

### X.3 循环依赖预防

- 用事件解耦（entity.deleted → 级联清理，不用直接调用）。
- 用 capability 门面（取能力不取对象）。
- lint 校验（越层即报错）。

---

## 扩充章 Y：事件-服务-数据对照表

| 事件 | 产生方 | 消费方 | 数据 |
|---|---|---|---|
| entity.deleted | 删除操作 | 相关服务级联 | — |
| affinity.settled | affinity_engine | 前端/游戏 | game_state.json |
| tool.registered | 工具注册 | 系统总览 | — |
| voice.session_start/end | 语音 | 监控 | — |
| voice.transcript/partial | STT | 对话 | — |
| voice.interruption | 语音 | 对话 | — |
| voice.vad_state | STT | 前端 | — |
| voice.reply_ready | chat | TTS/前端 | 回复文本 |
| voice.speaker | 声纹 | 对话/记忆 | 说话人 |
| voice.tts_audio_chunk | TTS | 播放端 | 音频块 |

---

## 扩充章 Z：架构自检清单（复刻后逐项勾选）

1. [ ] 依赖单向（lint 无越层）。
2. [ ] 容器装配幂等。
3. [ ] 15 Port ABC 可独立 import。
4. [ ] 缺失归一（container.get 返回 None 不崩）。
5. [ ] 适配器隔离（业务无直接 IO）。
6. [ ] 门面收敛（出网/裁决/语音）。
7. [ ] 事件解耦（级联走事件）。
8. [ ] fail-closed（裁决/网卡/沙箱）。
9. [ ] 删除可恢复（vault）。
10. [ ] 计量真实（provider 账本）。
11. [ ] 规范硬约束（≤50 行/≤500 行）。
12. [ ] 归档先行（重大变更前备份）。


# P.A.L.M 系统架构白皮书（深度扩充六：部署配置与运行验证）

> 承接扩充章 W-Z。本部分给出：完整部署配置示例、运行验证流程、以及配置项与代码的映射关系。

---

## 扩充章 AA：完整部署配置示例

### AA.1 .env 完整示例（生产形态）

```ini
# P.A.L.M 后端环境配置
HOST=127.0.0.1
PORT=8005
CORS_ALLOW_ORIGINS=http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000,http://127.0.0.1:8000

# 本地 TTS（Qwen3-TTS）
QWEN_TTS_API_URL=http://127.0.0.1:19300
QWEN_TTS_AUTO_LAUNCH=true
QWEN_TTS_MODEL_DIR=C:/Users/24459/Desktop/P.A.L.M/Data/qwen_tts_voicedesign
QWEN_TTS_MODEL=Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign
QWEN_TTS_QUANTIZE=4bit

# STT
STT_ENABLED=true
STT_AUTO_LAUNCH=true
STT_API_URL=http://127.0.0.1:19500
STT_SAMPLE_RATE=16000
STT_VAD_MODEL=C:/Users/24459/Desktop/P.A.L.M/Data/stt_models/vad/silero_vad.onnx
STT_ASR_MODEL=C:/Users/24459/Desktop/P.A.L.M/Data/stt_models/asr
STT_KWS_MODEL=C:/Users/24459/Desktop/P.A.L.M/Data/stt_models/kws
STT_KWS_KEYWORDS=C:/Users/24459/Desktop/P.A.L.M/Data/stt_models/kws/keywords.txt
```

### AA.2 settings.json 生产形态（脱敏）

```json
{
  "apiUrl": "http://localhost:8005",
  "agentWebSearch": true,
  "agentDeepThink": false,
  "agentToolMode": "native",
  "agentPlanningMode": "always",
  "agentAutoFilterTools": true,
  "runMode": "max",
  "autonomyLevel": "full",
  "idleMinutes": 15,
  "theme": "light",
  "language": "zh-CN",
  "dailyTokenLimit": 5000000,
  "monthlyTokenLimit": 50000000,
  "model": "kimi-k2.5",
  "flashModel": "kimi-k2.5",
  "proModel": "kimi-k2.5",
  "customProviders": [
    {
      "id": "tokenhub",
      "name": "tokenhub",
      "provider": "tokenhub",
      "base_url": "https://tokenhub.tencentmaas.com/v1",
      "api_key": "sk-***",
      "mode": "openai",
      "models": ["glm-5-turbo", "kimi-k2.5", "qwen3.5-plus"]
    }
  ]
}
```

### AA.3 配置映射（配置项 → 代码）

| 配置 | 代码位置 | 说明 |
|---|---|---|
| PORT | bootstrap/gateway | uvicorn 端口 |
| CORS | gateway | CORS 中间件 |
| customProviders | adapters/model/provider | 供应商列表 |
| model/flash/pro | adapters/model/model_router | select_model 路由 |
| runMode | services/ops/mode_resolver | 能力开关 |
| autonomyLevel | services/evolution/gate | 进化门控 |
| idleMinutes | services/evolution/idle_orchestrator | 闲置判定 |
| daily/monthlyTokenLimit | services/ops/token_usage | 配额 |
| QWEN_TTS_* | adapters/audio（facade） | TTS 配置 |
| STT_* | adapters/audio（stt） | STT 配置 |

---

## 扩充章 BB：运行验证流程（启动后 5 分钟验收）

### BB.1 第一分钟：装配验证

```
1. 启动日志：14 服务注册成功（无降级异常）
2. GET /api/system → 服务状态 JSON
3. 检查：storage/settings/crypto/models/gui/usage/ledger/scheduler/conversations/game/affinity/roleplay/memory/evolution/agent 全部在线
```

### BB.2 第二分钟：对话验证

```
1. POST /api/chat {"message": "你好"}
2. 期望：SSE 流式 text 事件
3. 检查：角色开启 → 开场白 first_mes
4. 检查：工具调用 → tool_call 事件（如触发）
5. 检查：done 事件（经验/用量/记忆写入）
```

### BB.3 第三分钟：安全验证

```
1. 未授权删除文件 → ask 询问
2. 拒绝 → 拦截（文件仍在）
3. 出网测试 → 网卡门面（成功或 NetworkForbidden）
4. 检查裁决日志
```

### BB.4 第四分钟：数据验证

```
1. GET /api/usage → 账本非空（provider 口径）
2. GET /api/game → 经验/星砂更新
3. 记忆检索 → 事实命中
4. GET /api/settings → 配置正确
```

### BB.5 第五分钟：心智核心验证

```
1. python -m mentalcore.selftest → 全过
2. python -m mentalcore.exo.selftest → 4 测全过
3. 控制码：/code 30000 → 好感度
4. EXO 委派 → Worker 执行 → 回传
```

---

## 扩充章 CC：故障定位路径（从症状到根因）

### CC.1 前端问题

```
前端 → 网络面板（请求状态）
  → CORS？（浏览器控制台）
  → 端点 500？（后端日志）
  → 事件流？（SSE 连接）
  → 桥接层？（pywebview window.pywebview.api）
```

### CC.2 对话问题

```
对话 → chat_service 日志
  → 上下文组装（roleplay/memory 注入）
  → models 调用（provider 日志）
  → 事件流（transport 日志）
  → 工具链（tool_call 日志）
  → 结算（game/usage/memory 日志）
```

### CC.3 安全问题

```
安全 → guardrail 日志（裁决事件）
  → permission（授权记录）
  → net（出网记录）
  → vault（删除记录）
  → threat_data.json（威胁记录）
```

### CC.4 心智核心问题

```
心智 → selftest（自检）
  → 控制码（CONTROL_USAGE）
  → 注入/拆分（middleware 日志）
  → 好感度（30000 查询）
  → EXO（worker 状态）
```

---

## 扩充章 DD：架构健康检查（定期）

| 检查项 | 周期 | 方法 |
|---|---|---|
| 端点全绿 | 每次发布 | 扫描脚本 |
| 单元测试 | 每次发布 | pytest |
| 记忆基准 | 每月 | bench（对照） |
| 语音冒烟 | 每月 | 冒烟脚本 |
| GUI 指标 | 每周 | gui_metrics |
| 安全审计 | 每季度 | 审计流程 |
| 归档备份 | 每月 | 备份脚本 |
| 依赖更新 | 每季度 | 版本评估 |


# P.A.L.M 系统架构白皮书（深度扩充七：网关/传输/协议细节）

> 承接扩充章 AA-DD。本部分深入：gateway（网关）设计、transport（传输层）协议、SSE 事件规范、以及前后端数据契约。

---

## 扩充章 EE：gateway 设计（旧 registry 能力承接）

### EE.1 gateway 职责

- 承接旧 palm_sdk registry 迁移（dual/tools/world_model_cache 等 17 文件收敛）。
- 提供跨服务能力聚合（get_facade 点对点——北桥语义）。
- 与 container 的关系：gateway 是 container 的补充（聚合视图），container 是存储。

### EE.2 北桥/南桥隐喻（历史延续）

```
北桥（能力总线）：get_facade 点对点调用（要结果）
南桥（事件总线）：emit/subscribe 广播（不要结果）
分工：要结果的走能力总线，不要结果的走事件总线
```

### EE.3 能力聚合

```
gateway.get_facade("agent") → agent 服务能力门面
gateway.get_memory_api() → 记忆 API（Agent 强依赖）
gateway 聚合：tools/world_model_cache/dual 等迁移能力
```

---

## 扩充章 FF：transport 协议细节

### FF.1 传输层职责

- 事件序列化（SSE/内部）。
- 控制码解析（五位 D1-D5）。
- ask_user 事件 id 管理。
- 事件审计（最近 N 条）。

### FF.2 SSE 事件格式

```json
// SSE 帧
event: message
data: {"type": "text", "payload": {"text": "..."}, "seq": 1, "conversation_id": "...", "ts": 1785000000.0}

event: message
data: {"type": "tool_call", "payload": {"name": "web_search", "args": {"query": "x"}, "status": "running"}, "seq": 2}

event: message
data: {"type": "ask_user", "payload": {"id": "q-1", "message": "确认执行？", "timeout_ms": 30000}, "seq": 3}

event: message
data: {"type": "done", "payload": {"exp": 10, "starsand": 2}, "seq": 4}
```

### FF.3 ask_user 协议

```
下发：{"type": "ask_user", "payload": {"id": "q-1", "message": "...", "timeout_ms": 30000}}
应答：POST /api/ask-response {"id": "q-1", "answer": "yes"}
超时：30s → 默认 deny（fail-closed）
```

---

## 扩充章 GG：前后端数据契约（完整）

### GG.1 请求格式

```json
// 对话请求
POST /api/chat
{
  "message": "你好",
  "conversation_id": "abc123",      // 可选（续接会话）
  "character_id": "mengyao",         // 可选（角色）
  "stream": true
}

// ask 应答
POST /api/ask-response
{"id": "q-1", "answer": "yes"}

// 工具调用（直接）
POST /api/tools/execute
{"tool": "web_search", "args": {"query": "x"}}

// 控制（mentalcore）
POST /api/mentalcore/control
{"code": 30300, "payload": {"base": 5.0}}
```

### GG.2 响应格式

```json
// 系统状态
GET /api/system
{
  "services": {"storage": {"status": "ok", "capabilities": 6}, ...},
  "run_mode": "max",
  "model": {"current": "kimi-k2.5", "provider": "tokenhub"}
}

// 游戏状态
GET /api/game
{
  "total_exp": 2393, "currency": 40, "streak_days": 1,
  "daily_tasks_done": ["chat_once", "plan_once", "chat_ten"],
  "unlocked_items": ["affinity_display"]
}
```

---

## 扩充章 HH：完整数据流图（文字版全景）

```
┌─────────────────────────────────────────────────────────────┐
│                        用户（前端 12 页）                      │
│  chat / game / usage / vault / settings / overview / ...     │
└──────────────┬──────────────────────────────────────────────┘
               │ HTTP + SSE
┌──────────────▼──────────────────────────────────────────────┐
│                    FastAPI 网关（:8005）                      │
│  路由 → 服务（container 取用）→ 事件流（transport/SSE）        │
└──┬───────────┬───────────┬───────────┬──────────────────────┘
   │           │           │           │
   ▼           ▼           ▼           ▼
chat 服务    agent 服务   ops 服务    evolution 服务
   │           │           │           │
   ├─roleplay  ├─tools     ├─scheduler ├─proactive
   ├─memory    ├─guardrail ├─usage     ├─offline_digest
   └─models    ├─permission├─ledger    └─habit_engine
               └─sandbox   └─mode
   │           │           │           │
   ▼           ▼           ▼           ▼
adapters（storage/crypto/models/gui/audio/io）
   │           │           │           │
   ▼           ▼           ▼           ▼
Data/（存储池/记忆/角色/游戏/配置/审计）
```

---

## 扩充章 II：架构验收工具（lint 校验）

### II.1 依赖方向校验

```python
# 检查 domain 是否 import services/adapters
def check_dependency_direction():
    violations = []
    for mod in scan("palm/domain"):
        for imp in mod.imports:
            if imp.startswith("palm.services") or imp.startswith("palm.adapters"):
                violations.append(f"{mod} → {imp}")
    assert not violations, f"越层依赖: {violations}"
```

### II.2 契约校验

```python
# 检查 Port 子类实现全部抽象方法
def check_ports():
    for port in scan("palm/ports/ports"):
        impls = find_implementations(port)
        for impl in impls:
            abc.verify_abstract(impl)   # ABC 强制验证
```

### II.3 规范校验

```python
# 函数 ≤ 50 行 / 文件 ≤ 500 行
def check_style():
    for py in scan("palm"):
        assert line_count(py) <= 500, f"{py} 超 500 行"
        for func in parse_functions(py):
            assert func.lines <= 50, f"{py}.{func.name} 超 50 行"
```

---

## 扩充章 JJ：架构演进边界（什么不能改）

1. **container 语义**：get/register/capability 接口稳定（业务依赖）。
2. **Port 契约**：15 ABC 语义稳定（跨版本不变）。
3. **事件常量**：eventbus 事件类型稳定（消费方依赖）。
4. **控制码**：五位编码语义稳定（外部调用方依赖）。
5. **数据格式**：settings/game_state/角色卡 JSON 向后兼容。
6. **安全原则**：fail-closed/须授权/删除可恢复——永不倒退。


# P.A.L.M 系统架构白皮书（深度扩充八：完整性核对与扩展设计）

> 承接扩充章 EE-JJ。本部分给出：架构完整性核对表、扩展设计指南、以及架构决策记录。

---

## 扩充章 KK：架构完整性核对表

### KK.1 分层完整性

| 层 | 应有 | 实有（证据） | 核对 |
|---|---|---|---|
| ports | 15 Port ABC | 15（agent/audio/crypto/device/display/guard/gui/memory/model/ops/persist/storage/sys/tool/ui） | ✓ |
| _core | 20 模块 | 20（config/container/emotion/eventbus/gateway/guardrail/housekeeping/interop/logging/net/paths/permission/redundancy/schemas/security/token_estimate/tooling/transport/watchdog） | ✓ |
| adapters | 6 组 | 6（crypto/display/gui/io/model/storage） | ✓ |
| domain | 4 子域 | 4（evolution/memory/planning/roleplay） | ✓ |
| services | 4 组 | 4（agent/chat/evolution/ops） | ✓ |
| bootstrap | 1 | app.py（140 行） | ✓ |

### KK.2 服务完整性

| 服务 | 装配证据 |
|---|---|
| storage | ✓（6 能力） |
| settings | ✓（load_app_settings） |
| crypto | ✓（3 能力） |
| models | ✓（4 能力） |
| gui | ✓（automate） |
| usage | ✓（check_quota/record_usage） |
| usage_ledger | ✓ |
| scheduler | ✓ |
| conversations | ✓ |
| game | ✓（5 能力） |
| affinity | ✓ |
| roleplay | ✓（roleplay_api） |
| memory | ✓（memory_api） |
| evolution | ✓（evolution_api） |
| agent | ✓ |

### KK.3 安全完整性

| 防线 | 证据 |
|---|---|
| 裁决 5 档 | guardrail/engine.py Profile |
| 权限引擎 | permission.py + permissions.json |
| 网卡门面 | net/ NetworkForbidden |
| 保险库 | redundancy/vault.py |
| 回收站 | redundancy/recycle.py |
| 看门狗 | watchdog.py |
| 审计 | eventbus 审计 + 日志 |

---

## 扩充章 LL：扩展设计指南

### LL.1 新增服务流程（标准）

```
1. 定义 Port（ports/xxx_port.py）
2. 实现适配器/服务（adapters/ 或 services/）
3. bootstrap 注册（capabilities）
4. 安全接入（裁决/权限/网卡/审计）
5. 前端接入（页面/API）
6. 验收（端点/测试/基准）
```

### LL.2 新增工具流程

```
1. tools/ 新增工具文件
2. 定义 schema + 安全标记（sensitive/networked/code）
3. 注册（register_tool）
4. 裁决规则（如需）
5. 测试
```

### LL.3 新增事件

```
1. eventbus.py 声明事件常量
2. 生产方 emit
3. 消费方 subscribe
4. 前端（如需 SSE）
5. 审计（如需）
```

### LL.4 新增引擎（模型/语音）

```
1. 适配器实现（model provider / audio facade）
2. 配置（.env/settings）
3. 降级路径（未配置不阻断）
4. 验收（流式/合成）
```

---

## 扩充章 MM：架构决策记录（ADR 风格）

### MM.1 ADR-001：服务容器 vs 完整 DI 框架

- **背景**：旧 registry 迁移；需要轻量注入。
- **决策**：自研 container（ServiceHandle + capability）。
- **理由**：轻量、迁移兼容（registry 别名）、缺失归一语义。
- **备选**：FastAPI Depends（函数级，不适合服务级）、第三方 DI（过重）。
- **结果**：14 服务注册/取用，业务零耦合。

### MM.2 ADR-002：Port ABC vs Protocol

- **背景**：需要强制契约。
- **决策**：ABC（15 Port）。
- **理由**：强制实现（子类必须实现全部抽象方法）、可独立 import。
- **结果**：契约层先行（评审通过 + 落 P1）。

### MM.3 ADR-003：事件总线 vs 直接调用

- **背景**：级联删除/广播通知需要解耦。
- **决策**：eventbus（同步分发 + 降级隔离）。
- **理由**：单机系统足够；降级隔离保证可用性。
- **结果**：entity.deleted/affinity.settled/voice.* 等事件化。

### MM.4 ADR-004：fail-closed 安全策略

- **背景**：安全优先（宁拒勿放）。
- **决策**：裁决 AI 档无回调 deny；网卡无注册拒绝；沙箱隔离失败拒绝。
- **理由**：不可用 > 不安全。
- **结果**：纵深防线每层独立兜底。

### MM.5 ADR-005：本地优先

- **背景**：隐私要求。
- **决策**：数据本机；零联网模式（缝合/心智 mock）。
- **理由**：用户数据主权。
- **结果**：mock/live 双模式；网卡门面唯一出口。

### MM.6 ADR-006：计量真实性

- **背景**：用量明细需可信。
- **决策**：provider 真实量落账本；估算量不入账。
- **理由**：防虚增、可审计。
- **结果**：token_ledger 真实账本 + check_quota。

---

## 扩充章 NN：架构演进边界（补充）

### NN.1 不变量

1. container 接口语义。
2. Port 契约语义。
3. 事件常量。
4. 控制码语义。
5. 数据格式（JSON 向后兼容）。
6. 安全原则（fail-closed/须授权/删除可恢复）。

### NN.2 可变项

1. 内部实现（引擎/算法可替换）。
2. 工具集（可增删）。
3. 服务实现（可升级）。
4. 前端页面（可重设计）。
5. 模型供应商（可切换）。

### NN.3 演进治理

- 变更先文档（评审驱动）。
- 归档先行（可回滚）。
- 基准回归（性能不变差）。
- 验收全过（质量不倒退）。


# P.A.L.M 系统架构白皮书（深度扩充九：完整契约与架构问答）

> 承接扩充章 KK-NN。本部分给出：完整端口契约示例、架构设计问答、以及架构与其他系统的集成。

---

## 扩充章 OO：端口契约完整示例（3 个典型 Port）

### OO.1 StoragePort（存储契约）

```python
"""存储契约：文件池存取。"""
from abc import ABC, abstractmethod


class StoragePort(ABC):
    """存储能力契约（适配器实现，装配注册）。"""

    @abstractmethod
    def store_file(self, key: str, data: bytes) -> None:
        """按业务 key 写入文件。"""

    @abstractmethod
    def read_file_content(self, key: str) -> bytes:
        """读取文件内容。"""

    @abstractmethod
    def find_config_file(self, name: str) -> str:
        """定位配置文件。"""

    @abstractmethod
    def delete_file(self, key: str) -> None:
        """删除文件（经安全链）。"""

    @abstractmethod
    def get_store(self, name: str):
        """获取存储区句柄。"""

    @abstractmethod
    def load_app_settings(self) -> dict:
        """加载应用设置。"""
```

### OO.2 GuardPort（裁决契约）

```python
"""裁决契约：5 档安全裁决。"""
from abc import ABC, abstractmethod


class GuardPort(ABC):
    """安全裁决能力契约。"""

    @abstractmethod
    def adjudicate(self, event_type: str, ctx: dict):
        """裁决事件：返回 Decision（action/reason/ask_message/...）。"""

    @abstractmethod
    def get_profiles(self) -> dict:
        """返回当前 5 档策略配置。"""
```

### OO.3 ModelPort（模型契约）

```python
"""模型契约：云端 LLM 唯一出口。"""
from abc import ABC, abstractmethod


class ModelPort(ABC):
    """模型供应商能力契约。"""

    @abstractmethod
    def stream_chat(self, messages: list, tools=None, **kw):
        """流式对话：返回 (token 明细, 事件流)。"""

    @abstractmethod
    def is_model_file_capable(self, model: str) -> bool:
        """模型是否支持文件输入。"""

    @abstractmethod
    def file_handling_mode(self, model: str) -> str:
        """文件处理模式（inline/reference/reject）。"""
```

**契约设计原则**：
1. 语义稳定（跨版本不变）。
2. 可独立 import（无运行时依赖）。
3. ABC 强制（子类必须实现）。
4. 面向能力（非面向实现）。

---

## 扩充章 PP：架构设计问答（ADR 补充）

**Q1：为什么 14 服务而不是更多/更少？**
14 是"业务功能的最小全集"：底座（storage/settings/crypto/models/gui）+ 服务（usage/ledger/scheduler/conversations）+ 领域（game/affinity/roleplay/memory/evolution）+ agent。更多会过度拆分，更少则功能缺失。

**Q2：为什么 adapter 单独一层？**
外部 IO 集中隔离：存储/加密/模型/IO/GUI/显示。业务层不直接碰 IO——安全（门面强制）+ 可测（mock 替换）。

**Q3：为什么 domain 不依赖 services？**
领域层是"业务概念与规则"（角色/记忆/规划/进化），服务层是"流程编排"。领域独立保证规则稳定、可单测。

**Q4：为什么用事件总线而不是直接调用？**
广播型交互（级联删除/语音事件/好感度结算）用事件解耦——生产方不关心消费方，消费方可独立增减。

**Q5：为什么缺失归一 None 而不是抛异常？**
"缺失归一降级"是铁律：服务未注册/能力缺失 → None → 业务判空 → 降级路径。防止装配失败拖垮整个系统。

**Q6：为什么 capability 双源解析？**
显式注册（语义明确）+ 方法属性（零配置）——业务代码 `capability("store_file")` 无需关心来源。

**Q7：为什么控制码用五位十进制？**
D1-D5 按位次由粗到细（域→子类→动作→对象→参数方向）——结构化、可扩展、单值颗粒度。

**Q8：为什么事件类型集中常量？**
避免魔法字符串——集中声明便于消费方引用、审计、lint。

---

## 扩充章 QQ：与其他系统集成

### QQ.1 作为独立库（palm）

```python
from palm.bootstrap.app import build_app

proxy = build_app()          # 装配 14 服务
handle = proxy.get("storage")
handle.capability("store_file")("key", b"data")
```

### QQ.2 作为 FastAPI 应用

```python
from fastapi import FastAPI
from palm.bootstrap.app import build_app

app = FastAPI()
build_app()                  # 装配

@app.get("/api/system")
def system():
    services = [h.name for h in container.all()]
    return {"services": services}
```

### QQ.3 与 mentalcore 集成

```python
from mentalcore import build_core, build_exo, default_persona
from palm.bootstrap.app import build_app

build_app()                  # palm 装配
mc = build_core(mc_config, default_persona())
exo = build_exo(mc_config)
mc.exo_broker = exo.make_broker(mc)
container.register("mentalcore", mc, {"send": mc.send_message})
```

### QQ.4 与外部系统（MCP/插件）

- MCP：热插拔能力（旧主板体系遗留）。
- 插件发现：技能卡/角色卡导入。
- Webhook：事件总线外部桥接（扩展）。

---

## 扩充章 RR：架构健康指标

| 指标 | 定义 | 健康标准 |
|---|---|---|
| 装配成功率 | 14 服务注册成功比例 | 100% |
| 端点错误率 | 5xx 比例 | 0% |
| 裁决拦截率 | deny 比例 | 按策略 |
| 工具成功率 | 工具执行成功 | ≥95% |
| 对话完成率 | done 事件到达 | ≥99% |
| 记忆命中率 | 检索命中 | 按基准 |
| 用量真实性 | 账本与 provider 一致 | 100% |
| 审计覆盖率 | 敏感操作留痕 | 100% |

---

## 扩充章 SS：架构文档体系（配套）

| 文档 | 内容 | 更新 |
|---|---|---|
| 本系列 03 | 架构白皮书 | 复刻依据 |
| 架构日志 v2-v12 | 演进记录 | 历史 |
| ADR 记录 | 决策记录 | 随决策 |
| API 契约 | 端点/事件 | 随实现 |
| 配置手册 | .env/settings | 随配置 |
| 部署手册 | 部署/运维 | 随环境 |

**文档原则**：先文档后代码（评审驱动）；文档与代码同步；文档可复现（验收依据）。


# P.A.L.M 系统架构白皮书（深度扩充十：端点验收与架构陷阱）

> 承接扩充章 OO-SS。本部分给出：端点验收方法论、架构实现陷阱、以及架构演进路线图。

---

## 扩充章 TT：端点验收方法论

### TT.1 端点分类

| 类别 | 端点 | 验收重点 |
|---|---|---|
| 核心 | /api/chat、/api/events | 流式/事件完整 |
| 领域 | /api/characters、/api/game、/api/memory | 数据正确 |
| 运维 | /api/system、/api/usage、/api/vault | 状态真实 |
| 语音 | /api/tts、/api/stt | 降级路径 |
| 配置 | /api/settings | 读写一致 |

### TT.2 验收方法

```
1. 冒烟：核心端点基本调用（GET/POST）
2. 全量：163 端点扫描（无 500）
3. 异常：错误参数（4xx 而非 500）
4. 降级：依赖缺失（503 而非崩溃）
5. 并发：多会话并行
6. 安全：未授权（403/ask）
```

### TT.3 验收记录

```python
# 端点验收报告结构
{
  "date": "...",
  "total": 163,
  "ok": 163,
  "fails": [],
  "degraded": [],
  "conclusion": "pass"
}
```

---

## 扩充章 UU：架构实现陷阱（复刻避坑）

### UU.1 容器陷阱

| 陷阱 | 后果 | 规避 |
|---|---|---|
| 循环注册 | 装配死循环 | bootstrap 顺序依赖 |
| 缺失未判空 | NoneType 崩溃 | 判空铁律 |
| 全局状态泄漏 | 测试污染 | 业务零全局 |
| registry 混乱 | 迁移断链 | 兼容别名 |

### UU.2 契约陷阱

| 陷阱 | 后果 | 规避 |
|---|---|---|
| Port 未强制 | 实现缺方法 | ABC 验证 |
| 契约漂移 | 消费方破坏 | 语义稳定 |
| 越层依赖 | 循环 import | lint 校验 |

### UU.3 事件陷阱

| 陷阱 | 后果 | 规避 |
|---|---|---|
| 魔法字符串 | 拼写错误 | 集中常量 |
| 订阅泄漏 | 内存增长 | 返回取消函数 |
| 异常传播 | 订阅方拖垮 | 降级隔离 |
| 异步阻塞 | emit 卡死 | async 处理 |

### UU.4 安全陷阱

| 陷阱 | 后果 | 规避 |
|---|---|---|
| 裁决旁路 | 敏感操作未拦截 | 门面强制 |
| 授权遗漏 | 越权访问 | 全量接入 |
| 出网裸连 | 数据外泄 | net 门面 |
| 删除不可逆 | 数据丢失 | vault 拦截 |

### UU.5 数据陷阱

| 陷阱 | 后果 | 规避 |
|---|---|---|
| 路径硬编码 | 环境差异 | paths.py |
| 文件锁竞争 | 保存失败 | 重试 |
| 编码错误 | 中文乱码 | UTF-8 |
| 测试污染 | 数据损坏 | patch 隔离 |

---

## 扩充章 VV：架构演进路线图

### VV.1 近期（1-2 月）

| 项 | 说明 |
|---|---|
| 好感度解耦 | affinity 独立领域/服务 |
| 契约扩展 | 更多 Port（voice/evolution 细分） |
| 事件规范 | 更多业务事件 |
| 监控增强 | 遥测指标接入 |

### VV.2 中期（3-6 月）

| 项 | 说明 |
|---|---|
| agent 对标 | LangChain/OpenAI/Claude |
| 多模态 | 图像/文档 |
| 插件市场 | MCP/技能卡 |
| 多端同步 | 加密数据同步 |

### VV.3 长期（6-12 月）

| 项 | 说明 |
|---|---|
| 全本地化 | 本地 LLM + TTS |
| 联邦记忆 | 多设备 |
| 自主协作 | 多 Agent 网络 |
| 社区生态 | 角色卡/技能市场 |

---

## 扩充章 WW：架构最终自评

### WW.1 优势

1. 分层清晰（ports/domain/services/adapters/bootstrap）。
2. 契约强制（15 ABC）。
3. 安全纵深（fail-closed 每层独立）。
4. 解耦充分（容器/事件/门面）。
5. 可观测（轨迹/审计/基准）。

### WW.2 代价

1. 概念数量多（Port/能力/事件/控制码）。
2. 装配层职责重（唯一注册点）。
3. 文档依赖强（知识库维护）。

### WW.3 权衡结论

对于"个人 + AI"协作开发的桌面 AI 管家，这套架构的收益（可控/可测/可复刻）远大于代价（概念多/文档重）——这正是终极架构确立的原因。


# P.A.L.M 系统架构白皮书（深度扩充十一：数据流与状态机全解）

> 承接扩充章 TT-WW。本部分给出：核心数据流的状态机描述、会话/任务/好感度状态机、以及架构级时序图。

---

## 扩充章 XX：核心数据流状态机

### XX.1 会话状态机

```
created（创建）
  → active（对话中：上下文组装 → 模型流式 → 事件流）
  → tool_waiting（工具调用：裁决/授权/执行/回注）
  → ask_waiting（ask_user：等待应答，30s 超时 deny）
  → completing（完成：done 钩子结算）
  → closed（结束：持久化）
  → deleted（删除：级联清理）

异常路径：
  model_error（模型异常：重试/降级）
  tool_error（工具异常：自愈/重试）
  timeout（超时：deny/重试）
```

### XX.2 任务状态机（进化/规划）

```
pending（提交）
  → planning（规划：计划生成）
  → executing（执行：分步）
  → tool_calling（工具调用）
  → replanning（失败重规划）
  → done（完成：plan_once 回连）
  → cancelled（取消）
  → failed（失败：兜底）
```

### XX.3 好感度状态机

```
initial（初始：base=0, dynamics=0, tier=1）
  → settling（结算：对话后 base/dynamics 更新）
  → tier_up（档位提升：base 达阈值）
  → dynamic_shift（动态线变化：会话内波动）
  → cleansing（清档：防污染重置）
  → persistent（持久化：live 加密）
```

### XX.4 Worker 任务状态机

```
pending（委派）
  → running（ReAct 循环）
  → tool_calling（工具：权限/隔离/审计）
  → paused（暂停：干预）
  → resumed（恢复）
  → done（完成：||FIN|| + 回传）
  → cancelled（取消：干预）
  → failed（失败：兜底）
```

---

## 扩充章 YY：架构级时序图（文字版）

### YY.1 对话 + 工具 + 结算（全景时序）

```
用户 → 前端 → FastAPI → chat_service
  → roleplay.build_persona（人格）
  → memory.retrieve（记忆）
  → models.stream_chat（流式）
  → 事件流 → 前端
  → tool_call → guardrail → permission → 执行 → 回注
  → completion_gate（反思）
  → done → game.award_chat_xp → usage.record → memory.write → trace
  → affinity.settled 事件
  → 前端刷新（经验/用量）
```

### YY.2 语音会话时序

```
用户说话 → STT（:19500：VAD → ASR → KWS）
  → voice.transcript 事件
  → 对话链路（文本）
  → 回复 → voice.reply_ready
  → TTS facade（GSV/CosyVoice2/Qwen3-TTS）
  → voice.tts_audio_chunk（边生成边合成）
  → 播放
  → voice.speaker（声纹：多用户个性化）
```

### YY.3 进化时序

```
观察者（observer）→ 触发源（闲置/定时/习惯/事件）
  → gate（autonomyLevel）
  → guardrail（proactive 裁决）
  → 执行（proactive 推送 / offline_digest）
  → 记录（evolution_api）
  → 前端展示
```

### YY.4 EXO 时序

```
Boss 回复 + ||EXO||
  → ReplySplitter → out_fields["exo"]
  → exo_broker → 后台拉起 Worker
  → WorkCore ReAct（5 魔方）
  → 完成 → core.receive() 回传
  → Boss 下一轮加工 → 用户
```

---

## 扩充章 ZZ：架构级异常处理汇总

| 异常 | 检测 | 处理 |
|---|---|---|
| 装配失败 | try/except | 降级注册（打印 + 继续） |
| 模型错误 | stream 异常 | 重试 → 降级 mock → 错误提示 |
| 工具错误 | 执行异常 | schema 自愈 → 重试 → 错误回注 |
| 裁决 deny | Decision | blocked 返回 → 模型调整 |
| ask 超时 | 30s | deny（fail-closed） |
| 文件锁 | 保存异常 | 重试 → 错误分类 |
| 依赖缺失 | import 失败 | 降级（503） |
| 子进程异常 | watchdog | 重启/告警 |
| 数据损坏 | 校验失败 | 归档恢复 |
| 并发冲突 | 锁/版本 | 重试/隔离 |

---

## 扩充章 AAA：架构最终数据流全景

```
┌──────────────────────────────────────────────────────┐
│ 前端 12 页（原生 ES Modules）                          │
│  chat/game/usage/vault/settings/overview/monitor/... │
└────────────────────┬─────────────────────────────────┘
                     │ HTTP + SSE
┌────────────────────▼─────────────────────────────────┐
│ FastAPI 网关（:8005）                                 │
│  路由 → container.get(服务) → capability(键) → 执行    │
└──┬──────────┬──────────┬──────────┬──────────────────┘
   ▼          ▼          ▼          ▼
chat 服务   agent 服务  ops 服务   evolution 服务
   │          │          │          │
   ├─roleplay ├─tools    ├─scheduler ├─proactive
   ├─memory   ├─guardrail├─usage     ├─offline_digest
   └─models   ├─permission├─ledger   └─habit
              └─sandbox  └─mode
   ▼          ▼          ▼          ▼
适配器（storage/crypto/models/gui/audio/io）
   ▼
Data/（存储池/记忆/角色/游戏/配置/审计/轨迹）
   ▼
归档（archive/ 可恢复）
```

**架构完成度**：本系列 03 篇（架构白皮书）至此完整——分层、容器、契约、安全、事件、数据流、状态机、异常、演进全部覆盖。


# P.A.L.M 系统架构白皮书（深度扩充十二：部署拓扑与扩展点全解）

> 承接扩充章 XX-AAA。本部分给出：部署拓扑变体、扩展点全解、以及架构与产品的对应关系。

---

## 扩充章 BBB：部署拓扑变体

### BBB.1 完整部署（全功能）

```
pywebview 壳 + 12 页前端
FastAPI（14 服务）
  + 云端 LLM（tokenhub）
  + Qwen3-TTS（:19300）
  + STT（:19500）
  + GSV（自包含）
  + CosyVoice（venv）
  + ChromaDB + Ollama（bge-m3）
Data/ 全量
```

### BBB.2 最小部署（文本对话）

```
FastAPI（核心服务：storage/settings/crypto/models/chat/agent/roleplay/memory/...）
  + 云端 LLM
无语音/无 GUI/无向量（可选）
Data/ 核心目录
```

### BBB.3 离线部署（零联网）

```
FastAPI（mock 模式：缝合引擎/心智核心 mock）
无云端 LLM（缝合检索式对话）
Data/ 语料本地
```

### BBB.4 独立部署（mentalcore 单独）

```
mentalcore（pip install -e .）
  + 非推理模型端点
mentalcore_data/（live 加密）
无 palm/无前端（接口调用）
```

---

## 扩充章 CCC：扩展点全解

### CCC.1 服务扩展点

```
新增服务流程：
  1. ports/xxx_port.py（契约）
  2. adapters/ 或 services/ 实现
  3. bootstrap 注册（capabilities）
  4. 安全接入（裁决/权限/审计）
  5. 前端接入
  6. 验收
```

### CCC.2 工具扩展点

```
新增工具：
  1. services/agent/tools/ 新增文件
  2. ToolSpec（name/desc/schema/安全标记）
  3. 注册（register_tool）
  4. 裁决规则（如需）
  5. 测试
```

### CCC.3 模型扩展点

```
新增供应商：
  1. settings.json customProviders 数组
  2. 适配器实现（provider）
  3. 降级路径
  4. 验收（流式）
```

### CCC.4 语音扩展点

```
新增引擎：
  1. audio facade 注册
  2. 配置（.env）
  3. 降级路径
  4. 冒烟验收
```

### CCC.5 心智扩展点

```
六面：register_face
魔方：exo/cubes/ 新增
控制码：CONTROL_HANDLERS
模型：独立配置
技能：professional_memory
```

### CCC.6 前端扩展点

```
新增页面：
  1. frontend/ 新增 html
  2. ui/ 复用组件
  3. api.js 封装接口
  4. 导航接入
```

---

## 扩充章 DDD：架构与产品对应关系

| 架构要素 | 产品体现 |
|---|---|
| Port 契约 | 能力边界（可扩展） |
| 服务容器 | 系统总览（14 服务） |
| 适配器 | 存储/模型/语音管理 |
| 领域层 | 角色/记忆/游戏/进化 |
| 服务层 | 对话/Agent/调度 |
| 裁决 | 安全询问/拦截提示 |
| 权限 | 授权设置 |
| 保险库 | 删除恢复 |
| 事件总线 | 实时事件（语音/结算） |
| 控制码 | 心智管理 |
| 双链 | 陪伴 + 干活 |
| 账本 | 用量面板 |

---

## 扩充章 EEE：架构最终结论

P.A.L.M 的架构是一个"面向复刻、面向演进"的设计：

1. **契约化**：15 Port 定义能力边界（扩展不破坏）。
2. **容器化**：14 服务按名取用（缺失归一降级）。
3. **安全化**：fail-closed 纵深（每层独立兜底）。
4. **事件化**：广播解耦（级联/语音/结算）。
5. **可观测**：轨迹/审计/基准（验收有据）。

这套架构支撑了 P.A.L.M 从克隆到终极架构的演进，也支撑了本文档系列"1:1 复刻"的可行性——**架构的清晰度 = 复刻的可行性**。本系列 03 篇完整记录，复刻者按图施工即可。


# P.A.L.M 系统架构白皮书（深度扩充十三：架构篇收官）

> 承接扩充章 BBB-EEE。本部分给出：架构篇收官总结、架构知识价值、以及全系列架构结论。

---

## 扩充章 FFF：架构篇收官总结

### FFF.1 架构核心（回顾）

```
终极架构 = ports（15 契约）+ container（14 服务）
         + 分层（domain/services/adapters/bootstrap）
         + _core 基础设施（20 模块）
         + 安全纵深（裁决/权限/网卡/保险库）
         + 事件解耦（eventbus）
         + 计量真实（usage_ledger）
```

### FFF.2 架构原则（回顾）

1. 依赖单向（越层 lint 报错）。
2. 容器取用（缺失归一 None）。
3. 装配唯一（bootstrap 幂等）。
4. 适配器隔离（业务零 IO）。
5. 门面收敛（net/guardrail/facade）。
6. 事件解耦（广播不要求结果）。
7. fail-closed（未配置即拒绝）。
8. 删除可恢复（vault）。
9. 计量真实（provider 账本）。

### FFF.3 架构知识价值

1. **可复刻**：分层/契约/容器——按图施工。
2. **可演进**：扩展点清晰（服务/工具/模型/语音/心智/前端）。
3. **可验证**：契约测试/lint/端点扫描。
4. **可解释**：ADR 记录决策（为什么）。

---

## 扩充章 GGG：全系列架构结论

P.A.L.M 的架构回答了三个问题：

**为什么分层？** —— 依赖可控、测试可替、扩展不破坏。
**为什么契约？** —— 能力边界清晰、实现可换。
**为什么 fail-closed？** —— 不可用 > 不安全。

这套架构支撑了：
- 21 天从克隆到终极架构（演进能力）。
- 320+ 文件的组织（规模能力）。
- 14 服务的协作（组合能力）。
- 本系列 1:1 复刻（传承能力）。

**架构已白盒，复刻已可行。**




---


# P.A.L.M 系统架构白皮书（99% 补全章：15 Port 契约全量实录）

> 本章为架构篇补全，将 15 个 Port 的**完整抽象方法**从真实源码全量抄录（这是 03 篇此前最大的缺口）。同时补入裁决规则模型（rules.py 实录）与工具层基座（tooling.py 实录）。复刻者凭本章可 1:1 重建契约层。

---

## 补全章 A：15 Port 完整抽象方法（源码全量抄录）

> 所有 Port 均为 `abc.ABC`，仅依赖标准库，经 `ports/__init__.py` 总出口引用；子类缺失任一抽象方法即无法装配（ABC 强制）。隐喻沿用旧体系插槽语言（ai/pcie/chip/usb/ram/sata/m2/board/ui 插槽）。

### A.1 AgentPort（agent_port.py，ai 插槽，7 方法）

```python
class AgentPort(ABC):
    """Agent 核心插槽：规划/执行/反应/提示/完成判定/意图路由。"""

    @abstractmethod
    def run(self, prompt: str, context: dict[str, Any]) -> dict[str, Any]:
        """单次运行入口：ReAct 文本循环或原生 function calling 二选一，返回最终结果。"""

    @abstractmethod
    def stream(self, prompt: str, context: dict[str, Any]) -> Iterator[dict[str, Any]]:
        """流式事件出口：逐事件产出（工具调用/思维链/文本增量），消费方按类型分发。"""

    @abstractmethod
    def plan(self, task: str) -> dict[str, Any]:
        """计划生成：把任务拆成可执行步骤清单（含依赖与验收条件）。"""

    @abstractmethod
    def replan(self, plan: dict[str, Any], feedback: dict[str, Any]) -> dict[str, Any]:
        """重规划：执行受阻或需求变更时，依据反馈修订既有计划。"""

    @abstractmethod
    def build_prompt(self, user_input: str, persona: str, tools: list[str], memories: list[str]) -> str:
        """提示构建：把角色/工具清单/记忆注入用户输入，产出模型可消费的系统+用户消息。"""

    @abstractmethod
    def is_done(self, output: dict[str, Any]) -> bool:
        """完成判定：门控判断一轮输出是否已满足目标（true 即终止循环）。"""

    @abstractmethod
    def route_intent(self, message: str) -> str:
        """意图路由：把用户消息归类为四意图之一（如 闲聊/任务/记忆/情感），决定走哪条链路。"""
```

### A.2 AudioPort（audio_port.py，pcie 声卡，3 方法）

```python
class AudioPort(ABC):
    """声卡插槽：语音识别/语音合成/声纹识别。"""

    @abstractmethod
    def stt(self, audio: bytes) -> str:
        """语音识别：音频字节 → 文本；无授权/引擎缺失时抛依赖异常由调用方降级。"""

    @abstractmethod
    def tts(self, text: str) -> bytes:
        """语音合成：文本 → 音频字节（WAV）；CosyVoice/SoVITS 由实现方调度。"""

    @abstractmethod
    def voiceprint(self, audio: bytes) -> dict[str, Any]:
        """声纹识别：音频 → 声纹特征与分组归属，用于说话人确认。"""
```

### A.3 CryptoPort（crypto_port.py，chip 焊死，4 方法）

```python
class CryptoPort(ABC):
    """加密芯片插槽：SM4 加解密/硬件指纹密钥绑定/离线恢复。"""

    @abstractmethod
    def encrypt_bytes(self, data: bytes, key_id: str = "default") -> bytes:
        """加密：按密钥标识对原始字节做对称加密（SM4），返回密文。"""

    @abstractmethod
    def decrypt_bytes(self, blob: bytes, key_id: str = "default") -> bytes:
        """解密：按密钥标识还原明文；密钥不符抛异常由调用方归一。"""

    @abstractmethod
    def bind_fingerprint(self) -> str:
        """硬件指纹：读取/生成绑定本机的指纹标识，作为密钥派生种子。"""

    @abstractmethod
    def recover(self, seed: str) -> dict[str, Any]:
        """离线恢复：凭恢复种子重建密钥材料，返回恢复结果与可用状态。"""
```

### A.4 DevicePort（device_port.py，usb 五通道，5 方法）

```python
class DevicePort(ABC):
    """设备插槽（USB）：五通道协议，任何外设芯片必须实现。"""

    @abstractmethod
    def ingest(self, payload: dict[str, Any]) -> None:
        """入站总线：承载控制/数据/外部事件，内部按类型路由。"""

    @abstractmethod
    def drain(self) -> list[dict[str, Any]]:
        """出站总线：抽取待发消息（心跳/数据包/出站数据），消费方轮询清空。"""

    @abstractmethod
    def heartbeat(self) -> str:
        """统一存活信号：返回就绪/异常两态标识；消费者收不到即视为离线。"""

    @abstractmethod
    def control(self, code: str, decoder: dict[str, Any]) -> dict[str, Any]:
        """控制面：控制码 + 解码器单入口，返回执行结果与状态。"""

    @abstractmethod
    def data(self, payload: dict[str, Any]) -> bytes:
        """数据面：与控制面分离的载荷通道（音频/文本/二进制），返回编码后字节。"""
```

### A.5 DisplayPort（display_port.py，pcie 显示，3 方法）

```python
class DisplayPort(ABC):
    """显示层插槽：桌面/壁纸/部件渲染。"""

    @abstractmethod
    def render(self, spec: dict[str, Any]) -> bytes:
        """渲染：按规格（布局/组件/主题）产出图像字节，供展示。"""

    @abstractmethod
    def set_wallpaper(self, image: bytes) -> None:
        """壁纸：把图像字节设为桌面壁纸；失败返回异常由调用方降级。"""

    @abstractmethod
    def widgets(self) -> list[dict[str, Any]]:
        """部件清单：返回当前已注册桌面部件的描述，供管理界面展示。"""
```

### A.6 GuardPort（guard_port.py，chip 焊死，3 方法）

```python
class GuardPort(ABC):
    """守卫芯片插槽：动作裁决/策略管理。"""

    @abstractmethod
    def evaluate(self, action: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        """动作裁决：评估一次敏感动作（类型/目标/参数），返回放行/拒绝/升级及档位。"""

    @abstractmethod
    def policies(self) -> list[dict[str, Any]]:
        """策略清单：返回全部现行规则（供前端 JSON 管理与审计导出）。"""

    @abstractmethod
    def set_policy(self, policy: dict[str, Any]) -> None:
        """策略更新：新增/替换一条规则；非法策略抛 ValueError 由调用方归一。"""
```

### A.7 GuiPort（gui_port.py，pcie 显卡，3 方法）

```python
class GuiPort(ABC):
    """GUI 自动化插槽：语义入口/世界模型/静态认知。"""

    @abstractmethod
    def automate(self, software_id: str, intent: str) -> dict[str, Any]:
        """语义自动化入口：软件标识 + 意图 → 执行结果；经执行器阶梯（UIA/OCR/LLM/VLC）兜底。"""

    @abstractmethod
    def world_model(self, screen: dict[str, Any]) -> dict[str, Any]:
        """世界模型：把屏幕快照/控件树解析为结构化场景，供执行器决策。"""

    @abstractmethod
    def atlas(self) -> dict[str, Any]:
        """静态认知：返回已知软件的控件规律/转移规律/坐标记忆（EMA，样本不足不可信）。"""
```

### A.8 MemoryPort（memory_port.py，ram 内存条，5 方法）

```python
class MemoryPort(ABC):
    """记忆插槽：写入/语义检索/上下文压缩/Token 预算/情绪五因子。"""

    @abstractmethod
    def write(self, payload: dict[str, Any]) -> None:
        """事件触发式写入：把对话/行为事件沉淀为可检索的记忆条目。"""

    @abstractmethod
    def retrieve(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """语义检索：按相关性返回 top_k 条记忆（向量/BM25 混合由实现方决定）。"""

    @abstractmethod
    def compress(self, session: dict[str, Any]) -> dict[str, Any]:
        """上下文压缩：长会话折叠为摘要+要点，保留关键事实用于注入。"""

    @abstractmethod
    def budget(self, usage: dict[str, Any]) -> dict[str, Any]:
        """Token 预算：按用量与上限给出可注入配额，防上下文超限。"""

    @abstractmethod
    def emotion(self, text: str) -> dict[str, Any]:
        """情绪五因子：对文本打分（仅输出非负值），供情感门控与角色反应使用。"""
```

### A.9 ModelPort（model_port.py，cpu 焊死，4 方法）

```python
class ModelPort(ABC):
    """模型插槽：LLM 流式调用/单次补全/路由/健康。"""

    @abstractmethod
    def stream_chat(self, messages: list[dict[str, Any]], model: str, **options: Any) -> Iterator[str]:
        """流式补全：逐 token 产出文本；消费方用于 SSE/打字机效果。"""

    @abstractmethod
    def complete(self, messages: list[dict[str, Any]], model: str, **options: Any) -> str:
        """单次补全：一次性返回完整文本（工具判定/短回答等非流式场景）。"""

    @abstractmethod
    def route(self, intent: str) -> str:
        """模型路由：按意图/成本把请求分派到 Pro/Flash 等具体模型标识。"""

    @abstractmethod
    def health(self) -> dict[str, Any]:
        """健康探测：返回可用模型清单与各模型可用性（供 BIOS 自检与前端展示）。"""
```

### A.10 OpsPort（ops_port.py，ram 内存服务，3 方法）

```python
class OpsPort(ABC):
    """运维服务插槽：Token 用量/运行监控/定时任务。"""

    @abstractmethod
    def usage(self) -> dict[str, Any]:
        """Token 用量台账：返回累计消耗与分模型明细，供前端用量界面。"""

    @abstractmethod
    def monitor(self) -> dict[str, Any]:
        """运行监控：返回进程/资源/异常计数，供监控界面与告警。"""

    @abstractmethod
    def schedule(self, job: dict[str, Any]) -> None:
        """定时任务：登记/更新一个计划任务；触发时回调由实现方保证。"""
```

### A.11 PersistPort（persist_port.py，sata 硬盘，3 方法）

```python
class PersistPort(ABC):
    """持久化插槽：会话落盘/恢复、记忆落盘。"""

    @abstractmethod
    def save_session(self, session: dict[str, Any]) -> None:
        """会话落盘：把会话（消息序列/元数据）写入持久介质。"""

    @abstractmethod
    def load_session(self, session_id: str) -> dict[str, Any]:
        """会话恢复：按标识取回会话；不存在返回空会话由调用方归一。"""

    @abstractmethod
    def save_memory(self, memory: dict[str, Any]) -> None:
        """记忆落盘：把运行期记忆快照持久化，供重启后重建。"""
```

### A.12 StoragePort（storage_port.py，m2 固态，4 方法）

```python
class StoragePort(ABC):
    """存储插槽：介质层块读写/健康。"""

    @abstractmethod
    def read_block(self, key: str) -> bytes:
        """块读取：按 key 返回原始字节；key 缺失时抛 KeyError 由调用方归一。"""

    @abstractmethod
    def write_block(self, key: str, data: bytes) -> None:
        """块写入：按 key 落盘原始字节；介质层负责原子性与目录布局。"""

    @abstractmethod
    def delete_block(self, key: str) -> None:
        """块删除：按 key 移除；删除动作须经回收站语义（保险库兜底），禁止硬删。"""

    @abstractmethod
    def health(self) -> dict[str, Any]:
        """健康自检：返回容量/余量/读写状态，供 BIOS 自检与前端监控展示。"""
```

### A.13 SysPort（sys_port.py，board 板载，4 方法）

```python
class SysPort(ABC):
    """板载系统服务插槽：应用设置/文件鉴权/解析分发。"""

    @abstractmethod
    def settings(self) -> dict[str, Any]:
        """应用设置：返回全部设置项（供前端设置界面与管理接口）。"""

    @abstractmethod
    def set_setting(self, key: str, value: Any) -> None:
        """应用设置写入：按键更新并持久化；非法键抛 ValueError 由调用方归一。"""

    @abstractmethod
    def file_gate(self, path: str) -> bool:
        """文件鉴权：判定路径是否在允许域（用户主目录）内，越界返回 false。"""

    @abstractmethod
    def parse(self, file_path: str) -> dict[str, Any]:
        """解析分发：按文件类型路由到文档解析/图片 OCR，返回结构化内容。"""
```

### A.14 ToolPort（tool_port.py，工具总线，4 方法）

```python
class ToolPort(ABC):
    """工具插槽：注册/语义匹配/执行/代码防护。"""

    @abstractmethod
    def register(self, tool: dict[str, Any]) -> None:
        """工具注册：登记工具描述（名称/参数 schema/回调），供发现与调用。"""

    @abstractmethod
    def match(self, prompt: str) -> list[dict[str, Any]]:
        """语义匹配：按意图返回候选工具清单（含置信度），供主循环选择。"""

    @abstractmethod
    def execute(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """工具执行：按名调用已注册工具，返回结构化结果；未知名抛 KeyError。"""

    @abstractmethod
    def guard(self, code: str, lang: str) -> dict[str, Any]:
        """代码防护：静态预检生成代码（Python/JS/PowerShell），返回风险档位与命中规则。"""
```

### A.15 UiPort（ui_port.py，ui 显示器，2 方法）

```python
class UiPort(ABC):
    """前端界面契约：界面端点清单/界面渲染数据。"""

    @abstractmethod
    def endpoints(self) -> list[dict[str, Any]]:
        """界面端点清单：返回本界面依赖的后端端点（方法/路径/参数），供 shell 装载校验。"""

    @abstractmethod
    def render(self, screen: str, params: dict[str, Any]) -> dict[str, Any]:
        """渲染数据：按界面名与参数返回装配数据；未知界面返回空 dict 由调用方归一。"""
```

**契约层补全结论**：15 Port 共 55 个抽象方法（7+3+4+5+3+3+3+5+4+3+3+4+4+4+2），全部为"零实现、零依赖（仅标准库）"，复刻者按本章即可 1:1 重建契约层。

---

## 补全章 B：裁决规则模型（rules.py 实录）

### B.1 条件算子（ConditionOp，15 个）

| 类 | 算子 | 含义 |
|---|---|---|
| 数值 | gte/gt/eq/lt/lte | >= > == < <= |
| 字符串 | matches（正则）/startswith/endswith/contains/not_startswith/not_endswith/not_contains | 匹配/前缀/后缀/包含/反向 |
| 集合 | in_op（in）/not_in | 值在/不在集合 |
| 布尔 | is_true/is_false | 真/假 |

### B.2 规则数据结构（pydantic）

```python
class Condition(BaseModel):
    """单条匹配条件：字段 + 算子 + 目标值。"""
    field: str
    op: ConditionOp
    value: Any | None = None    # 数值/字符串/列表；布尔算子忽略
    label: str | None = None    # 条件不满足时的替代提示模板

class AskConfig(BaseModel):
    """ask 动作配置。"""
    message: str = ""           # 确认提示模板（支持 {field} 插值）
    timeout_ms: int = 30_000    # 超时毫秒
    on_timeout: Literal["deny", "allow", "warn"] = "deny"

ResponseAction = dict[Literal["ask", "deny", "allow", "warn"], str | AskConfig]
# deny 拒绝 / ask 询问 / warn 提醒（放行+告警） / allow 允许（白名单）
# quarantine（隔离）设计时纳入但第一期不实现

class Rule(BaseModel):
    """单条安全裁决规则：所有条件 AND 组合，优先级高（数字大）先匹配。"""
    id: str
    description: str = ""
    # ...（事件类型、条件列表、动作、优先级等，以源码为准）
```

### B.3 规则格式约定

```
规则格式：<AI行为><条件组合><执行行为>
  AI行为   : file.delete / file.write / process.execute / network.request / batch.operation
  条件组合 : 多个条件 AND 逻辑组合；字段+算子+值自由搭配
  执行行为 : 询问 / 提醒 / 拒绝 / 允许
```

**补全结论**：规则库为 pydantic 模型 + 规则文件（YAML 优先，pyyaml 不可用时回退 _minimal_yaml）；规则条目本身不内置于代码（引擎只认 RuleSet 数据结构）——复刻者需自行按 AI 行为五类设计规则条目。

---

## 补全章 C：工具层基座（palm/_core/tooling.py 实录）

### C.1 ToolSpec 完整字段（工具与外部世界唯一数据契约）

```python
@dataclass
class ToolSpec:
    name: str                                     # 蛇形命名，唯一标识（如 read_file）
    description: str                              # LLM 理解用途的自然语言描述
    parameters: dict = field(default_factory=lambda: {
        "type": "object", "properties": {}, "required": []})   # JSON Schema 参数定义
    event_type: str = ""                          # 触发裁决引擎的事件类型（空=不触发安全审查）
    permission: str = ""                          # 所需用户授权键；空串=豁免（fail-open）
    requires_grounding: bool = False              # 硬约束前置校验：删除/外发等高风险操作须先经
                                                  # 搜索/溯源核验并附带 verification_id，否则拦截
    requires_confirmation: bool = False           # 需要用户确认
```

### C.2 工具运行上下文（contextvars）

```python
agent_conversation_id: ContextVar[str]      # 当前会话 id（工具免改签名读取）
agent_model: ContextVar[str]                # 当前模型
agent_character_id: ContextVar[str]         # 当前角色 id（提醒/定时工具按角色人设撰写）
agent_provider: ContextVar[object]          # 当前供应商配置（automation 砖复用同款模型）
agent_is_wakeup: ContextVar[bool]           # 后台任务完成自动唤醒轮标记（唤醒轮禁再登记任务，防套娃）
```

### C.3 工具重试参数（真实值）

```python
_TOOL_MAX_RETRIES = 2        # 仅重试 tool.execute 瞬时异常（不含首次共 2 次）
_TOOL_RETRY_BACKOFF = 0.3    # 线性退避秒数
# 权限/裁决拦截在重试前已 return，不会被重试
```

### C.4 工具执行安全链

```
execute_tool_with_safety（tooling.py）：
  schema 校验 → 裁决（event_type）→ 授权（permission 键）→ 硬约束前置校验
  （requires_grounding 需 verification_id）→ 确认（requires_confirmation）→ 执行 → 重试（瞬时异常 2 次）
```

**补全结论**：工具层的"基类下沉"事实（tool_base.py 仅为薄壳，真正基类在 palm/_core/tooling.py）已被本补全章修正——03/04 篇此前按 tool_base 描述，现在以 tooling 为准。

---

## 补全章 D：宿主层事实澄清（重大修正）

**源码证据**：当前工作区 palm/ 库内**无任何 FastAPI 路由/APIRouter 定义**（grep 全库无 `@app.`/`APIRouter(`）；tool_base.py 注释明确"真正的基类定义已下沉到**主板 backend/app/bricks/_shared/tooling.py**"。

**结论**：
1. **HTTP 网关是宿主层职责**（backend/app/bricks/ 等应用层代码不在当前 palm 库内，也不在可访问的归档中——08-18 归档时对象损坏，或由 pywebview 宿主工程持有）。
2. 历史"163 端点全绿"是旧体系（主板时代 backend/app）的实录，**不是当前库内代码可验证的事实**。
3. 本文档系列中的 API 端点清单均为"宿主层规划参考"（基于旧体系 routes 证据重建），**非当前库内实测**。
4. 复刻者如需 HTTP 层，需自行按 UiPort.endpoints() 契约在宿主层实现 FastAPI 路由——契约已由 UiPort 定义，实现归宿主。

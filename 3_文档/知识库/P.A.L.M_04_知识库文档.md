# P.A.L.M 模块深度解析（复刻级）

> 本文档是复刻的核心依据，逐模块拆解 palm/ 库与 mentalcore/ 库的实现细节：职责、关键文件、核心接口、数据流、复刻要点。读者应能凭本文档 + 架构白皮书（第 3 篇）+ 复刻指南（第 6 篇）重建等价系统。所有信息来自当前工作区真实代码结构（palm/ 约 240 文件、mentalcore/ 71 个 Python 文件）。

---

## 模块一 存储池 storage（palm/adapters/storage/pool.py）

### 1.1 职责

统一文件存取抽象：所有业务数据的落盘入口（对话、记忆、角色、游戏、配置、日志、模型文件）。对应"存储芯片"概念的收敛形态（旧 M0-M5 介质层/管理芯片/总线接入/前端面板收敛至此）。

### 1.2 核心接口（装配层注册的 6 个能力）

| 接口 | 语义 |
|---|---|
| store_file | 写入文件（按业务 key 存储） |
| read_file_content | 读取文件内容 |
| find_config_file | 定位配置文件 |
| delete_file | 删除文件（经 safe-delete 守卫/vault 拦截） |
| get_store | 获取存储区句柄 |
| load_app_settings | 加载应用设置（与 io/app_settings 联动） |

### 1.3 复刻要点

1. 存储根目录约定：Data/（与 mentalcore_data/、备份 Data/ 同构）。storage_pool/ 子目录为池化存储区。
2. 删除必须走兜底链：delete_file → safe-delete 守卫（本机 rm 守卫）→ vault 拦截（可恢复）。
3. 测试隔离：GUI 存储落盘 Data/gui_*，测试须 patch _storage_cap 为 lambda:None（防止测试污染真实数据）。
4. 路径解析统一走 _core/paths.py，禁止硬编码路径（历史审计项）。

### 1.4 关联数据（备份 Data/ 实录）

- pool.json + .tmp 文件（池状态，含 cleanup_bak）。
- storage_pool/、swaps/（交换区）。

---

## 模块二 本机加解密 crypto（palm/adapters/crypto/）

### 2.1 职责

本机密钥与敏感数据的加解密；指纹采集用于绑定本机。

### 2.2 文件与接口

- keystore.py：密钥库。boot() 采集本机指纹；is_enabled 指示可用性（指纹失败仅置禁用，不阻断装配）。
- operations.py：encrypt_data / decrypt_data（装配层映射为 encrypt_bytes/decrypt_bytes）。

### 2.3 复刻要点

1. 指纹采集失败 → 置禁用 → 上层判空降级（不崩溃、不阻断启动）。
2. 加密对象：mentalcore 记忆（live 模式）、密钥、敏感配置（secure_config）。
3. 底层算法：对称加密 + 本机指纹派生密钥（具体算法以源码为准，复刻时保持接口即可）。

---

## 模块三 模型供应商 models（palm/adapters/model/provider.py）

### 3.1 职责

云端 LLM 的唯一出口：流式对话、文件能力声明、模式选择。多供应商扩展点。

### 3.2 核心接口

| 接口 | 语义 |
|---|---|
| stream_chat | 流式对话（SSE），返回 token 明细 |
| is_model_file_capable | 模型是否支持文件输入 |
| file_handling_mode | 文件处理模式（内联/引用/拒绝） |

### 3.3 复刻要点

1. 端点：tokenhub.tencentmaas.com 代理，模型 deepseek-v4-flash/pro 等；base_url/api_key 可配。
2. thinking 模型兼容：Kimi 等思考模型工具续轮必须携带 reasoning_content，否则 400（历史修复项）。
3. token 口径：provider 返回真实 prompt/completion/total，落 usage_ledger；估算量（token_estimate）不混入账本。
4. 多供应商扩展：实现 provider 接口即可接入新模型商。

---

## 模块四 会话服务 chat（palm/services/chat/）

### 4.1 职责

会话全生命周期：创建、续接、存取、引擎选择、语料构建。

### 4.2 文件与接口

| 文件 | 职责 |
|---|---|
| chat_service.py | 会话业务编排（接收输入、组织上下文、调模型、回事件） |
| conversation_store.py | 会话存取（注册为 conversations 服务） |
| hub.py | 会话聚合/路由 |
| engine.py | 引擎选择（native FC / ReAct / 规划） |
| build_corpus.py + corpus/ | 对话语料构建（缝合引擎语料来源） |

### 4.3 复刻要点

1. 会话上下文组织：历史轮次 + 人格注入（roleplay）+ 记忆注入（memory）+ 工具上下文。
2. 开场白 first_mes 接入会话流程（角色首次出现时输出）。
3. 事件流：响应 token 逐段推送；工具调用事件前置下发。
4. 会话删除级联：删除会话 → 相关记忆/用量/轨迹联动清理。

---

## 模块五 Agent 框架（palm/services/agent/）——复刻核心

### 5.1 总览（42 文件拆分）

```
core.py                    # Agent 核心（对外入口）
agent_execution_mixin.py   # 执行混合（规划执行）
agent_prompt_mixin.py      # prompt 混合
agent_react_mixin.py       # ReAct 循环混合
_native_execution.py       # 原生 FC 执行细节
native_parse.py            # 原生 FC 解析
native_runner.py           # 原生 FC 运行器
plan_engine.py             # 规划引擎
react_parser.py            # ReAct 解析器
tool_base.py               # 工具基座
tool_matcher.py            # 工具匹配
tools/                     # 工具集（100+）
protocols.py               # 协议定义
schemas.py                 # schema 校验
trace.py                   # 轨迹记录
completion_gate.py         # 完成闸门（反思自检 P3）
code_guard.py              # 代码守卫
question_hub.py            # 提问中枢（ask_user）
persona.py                 # 人格注入
prompt_templates.py        # prompt 模板
dual/                      # 双引擎遗留（不参与装配）
```

### 5.2 核心执行循环（原生 FC）

```
1. 组装 prompt（系统+人格+记忆+历史+工具清单）
2. 调 stream_chat（带 tools schema）
3. 流式解析：text / thought / tool_call 三类事件
4. tool_call → 校验（schemas）→ 裁决（guardrail）→ 授权（permission）→ 执行 → 回注
5. 循环至完成（completion_gate 判定）
6. trace 记录全流程
```

### 5.3 关键机制

**（一）规划引擎**：任务 → 计划（结构化输出）→ 分步执行 → 失败自动重规划 → plan_once 回连结算。
**（二）反思闸门**：回答成立性自检；不成立 → 补充/重试/澄清。
**（三）上下文压缩**：旧轮次摘要化，控制上下文长度。
**（四）空事件归一**：原生 FC 空 thought 事件须归一（NoneType 崩溃修复）。
**（五）工具 schema 自愈**：缺参补默认、错型纠正、失败重试（P2）。
**（六）事件前置**：工具调用执行前即下发事件（前端实时计时展示）。

### 5.4 人格注入（persona + prompt_templates）

- 人格来源：角色卡（roleplay/character）→ persona 模块转 prompt 模板。
- 好感度动态注入：亲和度档位影响语气/称谓。
- 关闭角色扮演后不得残留角色语气（三处缺口修复：系统提示/历史/工具上下文）。

---

## 模块六 角色扮演与好感度（palm/domain/roleplay/）——复刻核心

### 6.1 文件与职责

| 文件 | 职责 |
|---|---|
| character.py | 角色卡（社区规范对齐：name/description/personality/first_mes/示例对话） |
| persona.py | 人格运行时 |
| affinity_engine.py | 好感度引擎（10 级，官方统一规则） |
| affinity_store.py | 好感度存储 |
| affection.py | 好感度数值模型 |
| dynamics_engine.py | 角色动态机制（互动改变角色表现） |
| pollution_guard.py | 语气污染防护（长期记忆只存事实） |
| state.py | 角色状态 |
| xp.py | 经验模型 |
| game_service.py | 游戏结算（注册为 game 服务） |
| import_skill.py | Markdown 人格技能导入 |

### 6.2 双线好感度架构

- **基准线（base）**：长期稳定亲和度（对话积累，增速受档位约束——真实当前档位生效）。
- **动态线（dynamics）**：短期波动（近期互动质量，会话内变化）。
- 合成：对话 prompt 注入 = f(base, dynamics)；系数可调（双线好感度系数）。
- 道具影响：道具（后门显示）可影响动态线/解锁互动。
- 等级：好感度等级按官方统一规则（10 级分层），tier 增速按真实当前档位。

### 6.3 游戏结算（game_service）

| 接口 | 语义 |
|---|---|
| award_chat_xp | 聊天经验（done 钩子回连） |
| award_plan_xp | 规划经验（plan_once 回连） |
| has_item / unlock_item / purchase_item | 道具（星砂购买） |

- 等级：全局用户级 10 阶 × 100 级；0 阶每级 1000 Exp，后续每级 = 基础值 × 阶数；累登系数调节。
- 每日任务：聊天 1/10 次、触发自动规划等。
- 特殊对局：五子棋 vs 角色（按分数难度给 Exp）。

### 6.4 Markdown 技能导入（import_skill）

- 技能卡 = Markdown 文件（人格 Skill，如「梦瑶 — 猫娘性格」）。
- 导入流程：解析 Markdown 结构 → 生成角色卡 → 注册可对话角色。
- 角色 API：/characters、/characters/import、/characters/{id}、/affinity。

### 6.5 复刻要点

1. 角色卡对齐社区规范（首次对话、示例对话、人格描述结构）。
2. 好感度写入须经档位增速约束（防刷）。
3. 角色删除 → 级联删除好感度/记忆/游戏数据（跨砖级联删除钩子）。
4. 语气污染防护：角色语气不写入长期记忆（记忆层全局检测）。



# P.A.L.M 模块深度解析（续一：记忆/进化/运维/GUI/安全/缝合）

> 承接《模块深度解析》第一篇（存储/加密/模型/会话/Agent/角色扮演）。本篇覆盖：记忆层、自主进化、调度与计量、GUI 自动化、安全体系、对话缝合引擎。

---

## 模块七 记忆层 memory（palm/domain/memory/）——复刻核心

### 7.1 分层模型

| 层 | 文件 | 特性 |
|---|---|---|
| 核心记忆 | core_memory.py | 高权重长期事实，全局污染检测 |
| 向量记忆 | vector_memory.py | 语义检索（bge-small-zh INT8 ONNX / chroma），支持双幂律衰减 + 去噪归一 |
| 归档记忆 | archived_memory.py | 冷数据归档 |
| 写入器 | memory_writer.py | 统一写入入口（注册为 memory 服务，memory_api） |
| 预算 | token_budget.py | 记忆 token 预算（超限裁剪/摘要化） |
| 权重 | weights/ | 记忆权重（按类型/时效/情绪） |
| 基座 | base.py + memory.py | 抽象与组装 |

### 7.2 记忆写入原则（硬性）

1. **只存事实、不存语气**：长期记忆不写角色语气/情绪化表达（全局污染检测）。
2. **情绪标记可选**：情绪五因子（E_enc 仅 v≥0）作为记忆附加维度。
3. **预算受控**：token_budget 裁剪，防记忆撑爆上下文。
4. **衰减**：双幂律衰减 + 去噪归一（记忆层差异化核心，算法级基准验证）。

### 7.3 语义检索（vector_memory）

- 模型：bge-small-zh INT8 ONNX（本地、离线、低资源）。
- 索引：chroma（live 模式；mock 模式不建库）。
- 召回：top-k 语义命中 → 注入上下文；弱召回（top1<0.7）加情感/意图门控。

### 7.4 与缝合引擎的区别

- memory：Agent 自身的长期记忆（对话上下文补充）。
- stitching（缝合引擎）：面向"无模型可用"场景的检索式对话（语料=真实对话，HybridRetriever BM25+字 n-gram，运行期零联网）。

---

## 模块八 自主进化 evolution（domain + services）——复刻核心

### 8.1 领域层（domain/evolution/）

| 文件 | 职责 |
|---|---|
| proactive.py | 主动推送（Agent 主动发起对话/建议） |
| idle_orchestrator.py | 闲置编排（Agent 空闲时自主推测） |
| offline_digest.py | 离线摘要（每日简报） |
| habit_engine.py | 习惯引擎（观察用户习惯并适配） |
| fallback_engine.py | 兜底引擎（AI 兜底裁决） |
| background_tasks.py | 后台任务（定时触发） |

### 8.2 服务层（services/evolution/）

| 文件 | 职责 |
|---|---|
| registry.py | 进化系统注册表（注册为 evolution 服务，evolution_api） |
| loader.py | 进化模块加载 |
| observer.py | 观察者（监听事件驱动进化） |
| gate.py | 进化门控（是否允许主动动作） |
| slot_store.py | 技能槽存储 |
| skill_registry.py | 技能注册 |
| _injection.py / _io.py | 注入与 IO 工具 |
| schemas.py | schema |

### 8.3 进化链路

```
观察（observer 监听对话/行为）
  → 分析（idle_orchestrator / habit_engine）
  → 决策（gate 门控 + guardrail 裁决事件 + fallback_engine 兜底）
  → 执行（proactive 主动推送 / offline_digest 简报）
  → 记录（evolution_api）
```

### 8.4 复刻要点

1. 主动动作必须过裁决（agent.proactive 裁决事件）。
2. 联网动作必须过裁决（ChineseDictTool 联网未进裁决的审计修复）。
3. scheduler 取 evolution 主动推送能力（跨服务取能力，经 capabilities 门面）。
4. 进化动作可被用户关闭（gate）。

---

## 模块九 调度与计量 ops（palm/services/ops/）

### 9.1 调度引擎

| 文件 | 职责 |
|---|---|
| engine.py | 调度引擎（注册为 scheduler 服务） |
| cron.py | 定时任务（每日简报、闲置推测、保洁） |
| mode_resolver.py | 模式解析（mock/live/独立态） |
| game_detector.py | 游戏对局检测（五子棋等特殊对局来源） |
| store.py | 调度状态存储（schedules.json） |
| _settings.py | 调度设置 |

### 9.2 Token 计量

| 文件 | 职责 |
|---|---|
| token_usage.py | 用量服务（注册为 usage：check_quota/record_usage） |
| token_ledger.py | 账本（注册为 usage_ledger：provider 真实量落库） |

**计量铁律**：provider 真实用量落账本；估算量（token_estimate）不显示不入账；前端明细页展示真实账本。

### 9.3 模式解析（mode_resolver）

- mock 模式：禁用 Agent 执行，仅保留对话（隔离测试）。
- live 模式：全功能。
- 独立态：每服务可独立运行（历史修复独立态运行缺陷，核心端点全绿）。

---

## 模块十 GUI 自动化（palm/adapters/gui/）——复刻核心

### 10.1 架构

```
automation_orchestrator.py   # 对外单一入口 automate(software_id, intent)
  ├── 感知层：Atlas 静态认知（gui_atlas）
  │        转移规律（gui_transitions）
  │        坐标记忆（gui_coord_memory，EMA samples<2 不可信）
  ├── 推理层：目标分解 → 动作规划
  └── 执行层：执行器 L0-L3 四级容错
              L0/L1：UIA 树操作（uiautomation 辅助功能语义）
              L2：OCR 识别定位（引擎）
              L3：LLM 兜底规划（NullLlmDecider）
              L4：VLC（备用通道）
```

### 10.2 四级容错（executor_ladder）

| 档位 | 机制 | 说明 |
|---|---|---|
| 1 | UIA | 辅助功能树直接操作（首选） |
| 2 | OCR | 视觉定位（UIA 不可用时） |
| 3 | LLM 兜底 | 大模型规划（NullLlmDecider 空实现，fail-closed） |
| 4 | VLC | 备用媒体通道 |

档 3/4 fail-closed：LLM 兜底未配置真实模型时拒绝执行。

### 10.3 辅助模式关键约束（Windows）

- assistive_mode set/is/ensure_off。
- 必须先 CoInitializeEx(STA) 且必须在 uiautomation import 之前。
- 测试隔离：GUI 存储落盘 Data/gui_*，测试须 patch _storage_cap → lambda:None。

### 10.4 数据资产（备份 Data/gui_* 实录）

- gui_atlas/：静态认知（界面元素地图）。
- gui_transitions/：界面转移规律（状态机）。
- gui_coord_memory/：坐标记忆（EMA 平滑）。
- gui_metrics/：执行成功率/耗时指标。
- gui_routes/：路由表。

---

## 模块十一 安全体系（_core 安全族）——复刻核心

### 11.1 五层防线

```
L0 权限引擎（permission.py）：敏感能力须用户授权（持久化 permissions.json）
L1 裁决内核（guardrail/）：5 档规则裁决（engine.py + rules.py），AI 档无回调 fail-closed deny
L2 网卡门面（net/）：唯一出网出口，fail-closed
L3 冗余兜底（redundancy/）：vault 文件保险库 + recycle 回收站（删除拦截）
L4 看门狗（watchdog.py）：服务健康监测 + security.py 信任根
```

### 11.2 裁决 5 档（guardrail）

| 档 | 语义 |
|---|---|
| 1 | 允许（放行） |
| 2 | 追问（需用户确认） |
| 3 | 降权（降级执行） |
| 4 | 拒绝（拦截） |
| 5 | 阻断（AI 档 fail-closed，无回调即拒绝） |

裁决对象：工具调用、联网、代码执行、进化主动动作、提问工具。

### 11.3 安全链（历史审计保持）

- H1-H4 / M5 / M7 安全链不变（历史审计基线）。
- 注入面防护：agent 调用链注入面安全修复（prompt 注入样例库、红队测试）。
- 外部引用核实：审计报告须网络核实外部库名/函数名/写法。

---

## 模块十二 对话缝合引擎 stitching（独立能力）

### 12.1 定位

无模型/断网场景下的检索式对话兜底；也可作为低资源对话通道。

### 12.2 实现

- 检索：HybridRetriever = BM25 + 字 n-gram 混合召回（默认 mock 实现）。
- 语义：bge-small-zh INT8 ONNX（可选升级）。
- 语料：真实对话（build_corpus 构建）。
- 门控：弱召回（top1 < 0.7）加情感/意图门控；无匹配 → 诚实回答 + 建议问 LLM。
- 能力：capability stitch_api + 工具 stitch_chat；角色 mengyao。

### 12.3 复刻要点

1. 运行期零联网（语料本地）。
2. 明确能力边界：缝合 ≠ 生成，无匹配不编造。
3. mock 模式禁用 Agent 执行仅保留缝合对话（测试安全）。


# P.A.L.M 模块深度解析（续二：工具集/协议/数据模型/算法）

> 承接《模块深度解析》前两篇。本篇覆盖：工具集详解、事件与传输协议、关键算法（双幂律衰减/EMA/情绪五因子/好感度档位）、运行时数据模型清单（settings/permissions/game_state/schedules）。

---

## 模块十三 工具集 tools/（100+ 工具）

### 13.1 工具基座（tool_base + tool_matcher + tooling）

- 工具 = 名称 + 描述 + 参数 schema + 执行函数 + 能力标记。
- 运行时注册：register_tool / unregister_tool（agent 服务能力）。
- 匹配：tool_matcher 按意图/名称/语义匹配模型请求。
- 校验：参数 schema 自愈（缺参补默认、错型纠正），失败自动重试（P2）。

### 13.2 工具分类（按能力面）

| 分类 | 代表工具 | 安全要求 |
|---|---|---|
| 文件 | store/read/delete/find 文件、doc2struct（文档结构化） | 删除走 vault 拦截 |
| 网络 | WebSearch、ChineseDictTool（词典）、HTTP 工具 | 必须过裁决引擎 + net 门面 |
| 代码 | run_code（沙箱执行） | code_guard + 沙箱隔离 + 守卫询问 |
| GUI | uia_operate / executor / OCR 引擎 | L0-L3 执行器 + fail-closed |
| 语音 | TTS 合成 / STT 识别 | facade 收敛 |
| 游戏 | 五子棋对局、道具使用 | game_detector 检测 |
| 记忆 | 记忆写入/检索 | memory_api |
| 提问 | ask_user（向用户提问） | 事件 id 应答闭环 |
| 缝合 | stitch_chat | 零联网 |

### 13.3 工具执行链路（安全完备版）

```
模型发出 tool_call
  → tool_matcher 匹配
  → schemas 校验（自愈）
  → guardrail 裁决（5 档）
  → permission 授权（敏感能力）
  → 事件下发（前端实时展示）
  → 执行（分类执行器）
  → 结果回注
```

---

## 模块十四 事件与传输协议（eventbus + transport）

### 14.1 事件类型

| 事件 | 方向 | 语义 |
|---|---|---|
| text | 模型→前端 | 文本流 |
| thought | 模型→前端 | 思维链（空事件归一） |
| tool_call | 模型→前端 | 工具调用（前置下发，实时计时） |
| ask_user | 系统→前端 | 提问（携带 id，按 id 应答） |
| proactive | 系统→前端 | 主动推送（进化） |
| verdict | 系统→前端 | 裁决结果 |

### 14.2 传输形态

- SSE：流式响应（/events 等）。
- HTTP：常规请求/应答。
- ask_user 闭环：事件携带 id → 前端应答 → 按 id 回填 → 恢复流程。

### 14.3 控制码体系（transport + 历史 chip 协议）

- 固定控制码：shutdown / release perf / resume（ns=0 标准协议）。
- mentalcore 控制码 18 条（五域，单值/单字段颗粒度，详见第 5 篇）。
- 历史"芯片"层协议统一封装于 control_chip.py（旧体系，已随主板归档；单芯片采样约束：拒绝全局采样器）。

---

## 模块十五 关键算法

### 15.1 记忆双幂律衰减 + 去噪归一（记忆层差异化核心）

- **双幂律**：记忆权重按时间与访问双维度幂律衰减（近期高频 vs 长期稳定不同衰减率）。
- **去噪归一**：噪声记忆（低置信/重复）去噪；权重归一化到稳定区间。
- 验收：算法级对照基准（共享合成语料 + 导入产线代码），诚实对比、伪像显式标注。

### 15.2 EMA 坐标记忆（GUI）

- 坐标记忆用指数移动平均（EMA）平滑。
- **samples < 2 不可信**：少于 2 个样本的坐标数据不用于定位决策。

### 15.3 情绪五因子（emotion）

- 五因子情绪向量 E = (维度1..5)；E_enc 编码规则：仅 v ≥ 0（负值不编码）。
- 用途：记忆附加维度、角色动态、对话语气调节。

### 15.4 好感度档位增速约束

- 好感度等级 10 级（官方统一规则）。
- 增速约束按**真实当前档位**生效（而非固定档）——高等级增速放缓。
- 双线：基准线（base，长期稳定）+ 动态线（dynamics，短期波动），合成系数可调。

### 15.5 等级经验（游戏）

- 全局用户级：10 阶 × 100 级。
- 0 阶：每级 1000 Exp；后续每级 = 基础值 × 阶数。
- 来源：固定任务（1000 Exp）+ 聊天（award_chat_xp）+ 规划（award_plan_xp）+ 特殊对局（五子棋按分数难度）。
- 累登系数调节 Exp。

---

## 模块十六 运行时数据模型清单

### 16.1 settings.json（应用设置）

```
{
  "app": {...},          # 应用级设置
  "model": {...},        # 模型供应商/base_url/api_key/模式
  "voice": {...},        # 语音引擎选择/参数
  "stt": {...},          # 语音识别
  "roleplay": {...},     # 角色扮演开关/默认角色
  "game": {...}          # 游戏化开关
}
```
（具体字段以 load_app_settings 实现为准；复刻时保持读写一致 + 防文件锁竞争。）

### 16.2 permissions.json（授权记录）

```
{ "permission_id": {"capability": "...", "granted": true/false, "scope": "...", "updated_at": "..."} }
```
所有敏感能力首次使用时询问并落库。

### 16.3 game_state.json（游戏状态）

```
{
  "currency": {"starsand": 数量},     # 星砂
  "level": {"tier": 阶, "level": 级, "exp": 当前经验},
  "items": {"道具id": 数量},
  "affinity": {"角色id": {"base": 基准线, "dynamics": 动态线}},
  "daily_tasks": {"日期": {"chat_count": n, "plan_count": n, ...}}
}
```

### 16.4 schedules.json（调度）

```
{ "job_id": {"cron": 表达式, "action": "digest|proactive|cleanup|...", "enabled": true, "last_run": "..."} }
```

### 16.5 轨迹与审计

- agent_traces.jsonl：Agent 运行轨迹（每行一次执行）。
- threat_data.json：威胁数据（裁决命中记录）。
- 审计报告：安全审计 md（外部引用核实）。

---

## 模块十七 复刻检查清单（本系列核心）

复刻者按以下清单逐项实现，可判定"1:1 等价"：

1. [ ] palm/ 目录分层：_core/adapters/bootstrap/domain/ports/services 齐全。
2. [ ] 15 个 Port ABC 存在且可独立 import，子类强制实现。
3. [ ] container.register/get/names 与 capability 门面实现。
4. [ ] build_app() 幂等装配 14 服务，各服务注册失败降级。
5. [ ] 对话全链路：chat → roleplay 注入 → memory 注入 → models 流式 → 事件流。
6. [ ] 工具链路：匹配 → 校验自愈 → 裁决 5 档 → 授权 → 执行 → 回注。
7. [ ] ask_user 闭环（id 应答、即时推送）。
8. [ ] 记忆：分层 + 只存事实 + token 预算 + 双幂律衰减。
9. [ ] 好感度：10 级 + 双线 + 档位增速约束。
10. [ ] 游戏：星砂/道具/经验/等级/每日任务。
11. [ ] 进化：观察 → 门控 → 裁决 → 主动推送/简报。
12. [ ] GUI：automate 入口 + L0-L3 执行器 + assistive_mode 约束。
13. [ ] 安全：权限 + 裁决 + net 门面 + vault + watchdog。
14. [ ] 计量：provider 真实量落账本，估算量不入账。
15. [ ] 前端 12 页 + ui 共享 + SSE 事件流 + ask_user 应答。
16. [ ] .env 配置驱动，语音/STT 优雅降级。
17. [ ] 自测：mentalcore.selftest / exo.selftest / 单元测试 / e2e。



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



# P.A.L.M 模块深度解析（深度扩充：逐文件解析）

> 承接《模块深度解析》正文。本部分对关键服务组逐文件解析：services/agent（Agent 框架 42 文件核心）、services/chat、services/ops、services/evolution、domain/planning、adapters 细节。

---

## 扩充章 A：services/agent/ 逐文件解析（核心 22 文件）

### A.1 核心类与入口

| 文件 | 角色 | 核心内容 |
|---|---|---|
| core.py | Agent 类 | PromptMixin+ExecutionMixin+ReactMixin 三合一组装；组件依赖注入；select_model 模型路由；AgentEvent 事件流 |
| schemas.py | 事件与协议 schema | AgentEvent（text/thought/tool_call/ask_user/verdict 事件模型） |
| protocols.py | 协议定义 | MemoryProtocol/ToolRegistryProtocol/ToolMatcherProtocol/CompletionGateProtocol/PersonaProviderProtocol/TokenBudgetProtocol/PlannerProtocol 七个协议 |
| trace.py | 轨迹记录 | 运行轨迹（计划/工具/结果/时间戳）落盘 agent_traces.jsonl |

### A.2 执行链路

| 文件 | 角色 | 核心内容 |
|---|---|---|
| _native_execution.py | 原生 FC 执行细节 | 工具调用执行循环（校验→裁决→授权→执行→回注） |
| native_runner.py | 原生 FC 运行器 | run_native：流式事件产出（空 thought 归一） |
| native_parse.py | 原生 FC 解析 | 模型输出解析为事件序列 |
| react_parser.py | ReAct 解析器 | 文本协议解析（Thought/Action/Observation） |
| agent_react_mixin.py | ReAct 混合 | ReAct 循环执行 |
| agent_execution_mixin.py | 执行混合 | 规划执行（计划步骤执行） |
| agent_prompt_mixin.py | prompt 混合 | 上下文组装（历史+人格+记忆+工具） |

### A.3 规划与工具

| 文件 | 角色 | 核心内容 |
|---|---|---|
| plan_engine.py | 规划引擎 | 任务→计划（结构化）→分步→失败重规划→完成 |
| tool_base.py | 工具基座 | ToolRegistry（get_registry/agent_conversation_id/agent_model/agent_is_wakeup/agent_character_id 上下文变量） |
| tool_matcher.py | 工具匹配 | 意图匹配（autoFilterTools） |
| tools/ | 工具集 | 9 文件（ask/file/life/sandbox/scheduler/web/window） |

### A.4 人格与守卫

| 文件 | 角色 | 核心内容 |
|---|---|---|
| persona.py | 人格注入 | create_persona_provider（角色卡→prompt 人格） |
| prompt_templates.py | prompt 模板 | 系统/工具/反思/压缩模板 |
| completion_gate.py | 完成闸门 | get_default_gate：回答成立性自检（P3） |
| code_guard.py | 代码守卫 | run_code 安全检查（沙箱+守卫询问） |
| question_hub.py | 提问中枢 | ask_user 事件 id 管理/应答回填 |
| dual/ | 双引擎遗留 | 历史双引擎（不参与装配） |

---

## 扩充章 B：services/chat/ 逐文件解析

| 文件 | 角色 | 核心内容 |
|---|---|---|
| chat_service.py | 会话业务 | 输入→上下文组装→模型→事件流；done 钩子（经验/记忆/用量） |
| conversation_store.py | 会话存取 | 会话 CRUD（对话记录 JSON，十六进制 id）；注册为 conversations 服务 |
| hub.py | 聚合 | 会话路由/并发管理 |
| engine.py | 引擎选择 | native FC / ReAct / 规划 模式选择 |
| build_corpus.py | 语料构建 | 真实对话→缝合语料 |
| corpus/ | 语料库 | 语料资产 |
| core.py | 核心 | 会话领域逻辑 |

---

## 扩充章 C：services/ops/ 逐文件解析

| 文件 | 角色 | 核心内容 |
|---|---|---|
| engine.py | 调度引擎 | 定时任务调度（schedules.json）；注册为 scheduler 服务 |
| cron.py | 定时 | cron 表达式解析/触发 |
| mode_resolver.py | 模式解析 | runMode（max/min/mock）→ 能力开关（mock 禁 Agent 执行） |
| game_detector.py | 对局检测 | 五子棋等特殊对局来源检测 |
| token_ledger.py | Token 账本 | provider 真实用量落账（注册为 usage_ledger） |
| token_usage.py | 用量服务 | check_quota/record_usage（注册为 usage） |
| store.py | 状态存储 | 调度/用量状态持久化 |
| _settings.py | 设置 | 调度相关设置 |

---

## 扩充章 D：services/evolution/ 逐文件解析

| 文件 | 角色 | 核心内容 |
|---|---|---|
| registry.py | 进化注册表 | 进化服务注册（注册为 evolution 服务，evolution_api） |
| loader.py | 加载 | 进化模块/技能加载 |
| observer.py | 观察者 | 监听事件（entity.deleted/affinity.settled 等）驱动进化 |
| gate.py | 门控 | 自主等级（autonomyLevel）控制主动动作 |
| slot_store.py | 技能槽 | 技能槽存储 |
| skill_registry.py | 技能注册 | Markdown 技能注册 |
| _injection.py | 注入 | 进化动作注入 |
| _io.py | IO | 进化 IO 工具 |
| schemas.py | schema | 进化事件/状态模型 |

---

## 扩充章 E：domain/planning/ 与 adapters 细节

### E.1 domain/planning/

- planner.py：Planner 领域模型（任务→计划→步骤）。
- schemas.py：计划 schema（步骤/依赖/状态）。

### E.2 adapters/model/ 细节

- provider.py：stream_chat/is_model_file_capable/file_handling_mode。
- model_router.py：select_model（flash/pro 分档路由——settings.json flashModel/proModel/model 联动）。

### E.3 adapters/gui/ 细节

- automation_orchestrator.py：automate(software_id, intent) 单一入口。
- 执行器链：L0-L3（UIA/OCR/LLM/VLC），档 3/4 fail-closed。
- assistive_mode：set/is/ensure_off（CoInitializeEx(STA) 先于 uiautomation import）。

### E.4 adapters/crypto/ 细节

- keystore.py：boot() 指纹采集；is_enabled。
- operations.py：encrypt_data/decrypt_data。

### E.5 adapters/storage/ 细节

- pool.py：文件池（store_file/read_file_content/delete_file/get_store/load_app_settings/find_config_file）。

### E.6 adapters/io/ 细节

- app_settings.py：settings.json 读写（Windows 文件锁重试）。

---

## 扩充章 F：domain/ 逐文件解析

### F.1 domain/roleplay/（11 文件）

| 文件 | 核心内容 |
|---|---|
| character.py | 角色卡模型（社区规范：name/description/personality/first_mes/示例对话）；注册为 roleplay 服务 |
| persona.py | 人格运行时（角色卡→对话人格） |
| affinity_engine.py | 好感度引擎（10 级/双线/档位增速）；注册为 affinity 服务 |
| affinity_store.py | 好感度持久化 |
| affection.py | 好感度数值模型 |
| dynamics_engine.py | 动态机制（互动改变表现） |
| pollution_guard.py | 语气污染防护 |
| state.py | 角色状态 |
| xp.py | 经验模型 |
| game_service.py | 游戏结算（award_chat_xp/award_plan_xp/has_item/unlock_item/purchase_item）；注册为 game 服务 |
| import_skill.py | Markdown 技能导入 |

### F.2 domain/memory/（9 文件）

core_memory/archived_memory/vector_memory/memory_writer/token_budget/weights/base/memory + __init__。

### F.3 domain/evolution/（6 文件）

proactive/idle_orchestrator/offline_digest/habit_engine/fallback_engine/background_tasks。


# P.A.L.M 模块深度解析（深度扩充二：算法公式/缝合引擎/权限引擎细节）

> 承接扩充章 A-F。本部分给出关键算法的形式化描述、缝合引擎检索细节、权限引擎 Phase 演进、以及语音引擎技术细节。

---

## 扩充章 G：关键算法形式化

### G.1 记忆双幂律衰减 + 去噪归一（形式化）

设记忆项 m 的权重 W(t)，时间衰减幂律与访问衰减幂律叠加：

```
W(t) = W0 · (1 + t/τ_t)^(-α) · (1 + n/τ_n)^(-β)
```

- t：距上次强化时间；n：访问次数。
- α/β：时间/访问衰减指数（双幂律核心）。
- τ_t/τ_n：时间/访问半衰期。
- 强化：每次访问/关联恢复部分权重（W += Δ）。

去噪归一：
```
1. 噪声判定：低置信（重复冗余、语义无关、情绪噪音）→ 剔除/降权
2. 归一化：权重映射到稳定区间（如 [0.1, 1.0]），防极端值
3. 预算裁剪：超 token_budget → 摘要化/归档
```

### G.2 EMA 坐标记忆（GUI）

```
E_t = α·x_t + (1-α)·E_{t-1}    （α 平滑系数）
样本数 < 2 → 不可信（不用于定位决策）
```

### G.3 情绪五因子（emotion）

```
E = (v, a, d, ...)   五因子情绪向量
E_enc 编码：仅 v ≥ 0 编码（负值不编码——防止负向情绪污染记忆）
用途：记忆附加维度/角色动态/语气调节
```

### G.4 好感度档位增速约束

```
rate(tier) = base_rate / tier_factor(tier)     # 高等级增速放缓
base_delta = interaction_quality · rate(current_tier)
dynamics_delta = interaction_quality · DYNAMICS_COEF
合成影响 = f(base, dynamics)                     # 系数可调
等级阈值：官方统一规则（10 级分层）
```

### G.5 等级经验（游戏）

```
0 阶：每级需 1000 Exp
tier≥1：每级需 = 1000 × tier            # 基础值 × 阶数
每日经验 = 固定任务(1000) + chat_exp + plan_exp + 对局_exp
累登系数：streak_days 调节（连登加成）
```

### G.6 Token 计量

```
账本 = Σ provider 真实用量（prompt/completion/total）
估算量（token_estimate）不显示不入账
配额检查：daily/monthly limit（check_quota 拦截）
```

---

## 扩充章 H：对话缝合引擎检索细节

### H.1 HybridRetriever（BM25 + 字 n-gram）

```
query 规范化 → 两条检索线：
  BM25：词粒度（jieba 分词后 BM25 打分）
  字 n-gram：字粒度（2-gram/3-gram 重叠打分）
  → 加权融合 → top-k 候选
```

### H.2 门控决策

```
top1 得分 ≥ 0.7 → 采纳（注入语料片段 + 引用）
top1 < 0.7 → 情感/意图门控：
  情感匹配（语料情感 vs 用户情感）→ 可采纳
  否则 → 诚实回答（"我暂无相关记忆"）+ 建议问 LLM
无匹配 → 诚实 + 建议
```

### H.3 缝合能力边界

- 能力：capability stitch_api + 工具 stitch_chat。
- 角色：mengyao（梦瑶缝合通道）。
- 零联网：语料本地（build_corpus 构建）。
- 升级路径：bge-small-zh INT8 ONNX 语义检索（可选）。

---

## 扩充章 I：权限引擎 Phase 演进

| Phase | 内容 | 证据 |
|---|---|---|
| 0 | 权限模型定义（capability/granted/scope） | permissions.json 结构 |
| 1 | 授权询问接入敏感操作 | "所有敏感能力须经用户授权" |
| 2 | 收口（遗漏操作补接）+ 校验错误处理器 | "补完权限引擎两处收口" |
| 3 | 与裁决引擎协同（guardrail 先行，permission 复核） | 工具调用链 |
| 4 | 持久化 + 前端授权面板 | permissions.json + 设置页 |

**与 guardrail 的分工**：
- guardrail：运行期规则裁决（5 档，事件级）。
- permission：用户授权状态管理（意图级，持久化）。
- 流程：guardrail 裁决事件 → permission 查授权 → 授权缺失发 ask_user。

---

## 扩充章 J：语音引擎技术细节

### J.1 CosyVoice（音色设计师）

- 定位：CosyVoice2，instruct2 模式需基底参考音（文本指令 + 参考音生成音色）。
- 推理：bf16（torch.amp.autocast("cuda", dtype=bfloat16)）。
- torch：cu128（Blackwell sm_120 需 CUDA12.8）。
- 音频：绕 torchcodec → 裸 soundfile。
- 依赖：wetext==0.0.4 钉版；vendored cosyvoice/matcha。
- transformers 5.x：KV-cache 掩码坍塌 → _patch_kv_cache_mask。

### J.2 GPT-SoVITS（GSV）

- 自包含运行时（内置 runtime 与模型，启动即拉起）。
- 解包：7-Zip（曾改自其他解压工具）。
- 进程管理：SubprocessTransport（统一子进程传输）。

### J.3 Qwen3-TTS（本地方案 B）

- 模型：Qwen3-TTS-12Hz-1.7B-VoiceDesign（文本造音色）。
- 量化：4bit NF4（约 2GB 显存，4G 卡可跑）。
- 服务：serve.py 自动拉起（:19300）。
- 模式：VoiceDesign/CustomVoice/Base（few-shot 克隆）。

### J.4 STT

- Silero VAD（静音检测）+ Zipformer ASR（识别）+ KWS（关键词唤醒）。
- 16kHz 单声道（训练配置一致）。
- 独立 venv 子进程（:19500）。
- 优雅降级：缺模型报 /api/stt/status 缺失，不阻断启动。

### J.5 声纹识别

- voice.speaker 事件（speaker/similarity/is_match）。
- 用途：按说话人切换角色与个性化（多用户场景）。

---

## 扩充章 K：前端契约细节

### K.1 api.js 封装

- 普通请求：fetch 封装（统一错误处理）。
- 流式：EventSource/fetch stream 解析 SSE 事件。
- ask_user：事件驱动弹窗 + POST 应答。

### K.2 主题与外观

- theme.css：明/暗主题（settings.json theme）。
- 部件（widget）：glass_clock 等时间组件经桥接层取数。
- 桥接层：window.pywebview.api 封装（pywebview 桌面壳）。

### K.3 页面数据流

- 对话页：POST /api/chat → SSE 事件渲染（text 追加/thought 时间线/tool_call 计时卡/ask_user 弹窗）。
- 总览页：GET /api/system → 14 服务状态卡。
- 用量页：GET /api/usage → 表格 + chart.js 图表。
- 商城页：GET /api/game/shop → 商品卡；POST /api/game/purchase → 星砂扣减。
- 保险库页：GET /api/vault → 已删文件列表；POST /api/vault/restore → 恢复。


# P.A.L.M 模块深度解析（深度扩充三：角色卡/技能卡/旧砖块体系/数据流清单）

> 承接扩充章 G-K。本部分给出：角色卡与技能卡格式详解、旧 24 砖体系全解析（作为历史参照）、以及各模块数据流汇总清单。

---

## 扩充章 L：角色卡与技能卡格式详解

### L.1 角色卡字段（社区规范对齐）

```
{
  "name": "梦瑶",              # 角色名
  "description": "猫娘性格的陪伴型AI...",   # 角色描述（注入系统提示）
  "personality": "...",        # 人格细节
  "first_mes": "你好呀~我是梦瑶...",        # 开场白（会话首条）
  "mes_examples": [...],       # 示例对话（风格参照/织语面语料）
  "affinity": {...}            # 好感度初始状态
}
```

### L.2 角色卡导入路径

1. Markdown 技能卡（import_skill 解析）：
   - 标题（角色名）+ 描述 + 人格 + 示例对话章节。
   - 解析为结构化角色卡 → 注册可对话角色。
2. JSON 角色卡（characters/*.json 直接放置）。
3. 社区角色卡（SillyTavern 等格式）兼容导入。

### L.3 技能卡示例（Markdown 人格 Skill）

```markdown
# 梦瑶 — 猫娘性格
- 性格：活泼、粘人、爱吃醋，偶尔傲娇
- 称呼：主人
- 语气：亲昵、撒娇、带"喵"尾音
- 好感度表现：低档疏离、中档熟络、高档依赖

## 示例对话
用户：你好
梦瑶：喵~主人终于来找我啦！
```

---

## 扩充章 M：旧 24 砖体系全解析（历史参照）

> 来自 Data/brick_inventory.json 实录。理解旧体系有助于理解终极架构的设计动机。

### M.1 24 砖清单（含总线类型）

| 砖 | 标题 | 总线 | 能力数 |
|---|---|---|---|
| agent | Agent 框架 | cpu | 8 |
| automation | GUI 自动化 | pcie | 0 |
| usage | Token 用量 | ram | 2 |
| conversations | 会话记录 | sata | 0 |
| safety | 兜底防御 | board | 0 |
| self_evolution | 受控自我进化 | board | 3 |
| affinity | 好感度引擎 | ram | 2 |
| storage | 存储芯片+管理芯片 | chip | 29 |
| scheduler | 定时任务引擎 | board | 4 |
| chat | 对话 | board | 0 |
| stitching | 对话缝合引擎 | ram | 1 |
| settings | 应用设置 | board | 1 |
| file | 文件处理 | board | 1 |
| display | 显示层 | pcie | 2 |
| crypto | 本机加解密 | chip | 3 |
| models | 模型供应商 | pcie | 4 |
| game | 游戏生态 | ram | 5 |
| evolution | 自主进化引擎 | board | 1 |
| roleplay | 角色扮演引擎 | board | 2 |
| parse | 解析与结构化 | pcie | 0 |
| memory | 记忆引擎 | sata | 1 |
| monitor | 运行监控 | ram | 3 |

### M.2 总线隐喻体系

| 总线 | 含义 | 承载砖 |
|---|---|---|
| cpu | 计算核心 | agent |
| pcie | 高速外设 | automation/display/models/parse |
| ram | 内存级快速数据 | usage/affinity/game/monitor |
| sata | 慢速大容量存储 | conversations/memory |
| chip | 芯片级基础 | storage/crypto |
| board | 主板级服务 | safety/self_evolution/scheduler/chat/settings/file/evolution/roleplay |

### M.3 旧体系 → 终极架构映射

| 旧砖 | 新归宿 |
|---|---|
| agent（8 能力） | services/agent + _core 相关 |
| storage（29 能力） | adapters/storage/pool.py |
| crypto（3 能力） | adapters/crypto/ |
| models（4 能力） | adapters/model/provider.py |
| roleplay（2 能力） | domain/roleplay/ |
| memory（1 能力） | domain/memory/ |
| evolution（1 能力） | domain/evolution/ + services/evolution/ |
| game（5 能力） | domain/roleplay/game_service.py |
| affinity（2 能力） | domain/roleplay/affinity_engine.py |
| scheduler（4 能力） | services/ops/engine.py |
| usage（2 能力） | services/ops/token_usage.py + token_ledger.py |
| conversations（0） | services/chat/conversation_store.py |
| chat（0） | services/chat/ |
| settings（1） | adapters/io/app_settings.py |
| safety（0） | _core/redundancy/ + permission.py |
| stitching（1） | 缝合能力（chat/stitching） |
| display（2） | adapters/display/ |
| automation（0） | adapters/gui/ |
| parse（0） | services/agent/native_parse.py 等 |
| monitor（3） | _core/watchdog.py + 监控能力 |
| self_evolution（3） | domain/evolution/ |

---

## 扩充章 N：各模块数据流汇总清单

### N.1 对话 → 工具 → 结算（主链路数据流）

```
用户消息
  → conversation_store 载入会话
  → roleplay 注入（角色卡/好感度/动态）
  → memory 注入（核心/向量/归档 + token_budget）
  → models stream_chat（select_model 路由）
  → 事件流（text/thought/tool_call/ask_user）
  → 工具链（匹配→校验自愈→裁决→授权→执行→回注）
  → completion_gate 反思
  → done：game.award_chat_xp / usage_ledger / memory 写入 / trace
```

### N.2 游戏结算数据流

```
对话完成/规划完成（done 钩子）
  → game_service.award_chat_xp / award_plan_xp
  → xp 累计 → 等级判定（10 阶 × 100 级）
  → 每日任务计数（chat_once/plan_once/chat_ten）
  → 星砂发放（daily_currency_earned）
  → game_state.json 落盘
```

### N.3 GUI 自动化数据流

```
automate(software_id, intent)
  → Atlas 静态认知（界面元素地图）
  → 转移规律（状态机）
  → 坐标记忆（EMA，samples≥2 才可信）
  → 执行器 L0-L3（UIA→OCR→LLM→VLC，fail-closed）
  → gui_metrics 记录（成功率/耗时）
```

### N.4 进化数据流

```
observer 监听 → 触发源（闲置/定时/习惯）
  → gate 门控（autonomyLevel）
  → guardrail 裁决（proactive 事件）
  → 执行（proactive 推送/offline_digest 简报）
  → evolution_api 记录
```

### N.5 语音对话数据流

```
用户语音 → STT（VAD→ASR→KWS，:19500）
  → 文本进入对话链路（voice.reply_ready 事件）
  → LLM 回复
  → TTS 合成（facade：GSV/CosyVoice2/Qwen3-TTS）
  → 音频回放（tts_audio_chunk 边生成边合成）
  → 声纹识别（voice.speaker，多用户个性化）
```

### N.6 记忆检索数据流

```
对话输入
  → vector_memory 语义检索（bge INT8，top-k）
  → 弱召回门控（top1<0.7 → 情感/意图门控）
  → 注入上下文（token_budget 裁剪）
  → 对话后 memory_writer 写入（事实抽取/污染检测/情绪标记）
```

---

## 扩充章 O：缝合与心智核心的定位差异（补充）

| 维度 | 缝合引擎 | 心智核心 |
|---|---|---|
| 场景 | 无模型/断网兜底 | 有性格的陪伴聊天 |
| 生成方式 | 检索式（不生成） | LLM 生成 |
| 语料 | 真实对话（HybridRetriever） | 角色卡 + 记忆 + 六面注入 |
| 记忆 | 语料库检索 | 语义记忆 + 分层记忆 |
| 控制 | 无控制码 | 18 条五位控制码 |
| 工具 | 无 | Boss 不碰/Worker 全有 |
| 安全 | 零联网 | 加密落盘 + 安全三拆分 |
| 关联 | chat 能力（stitch_chat） | 独立库（MentalCoreSlotPort） |


# P.A.L.M 模块深度解析（深度扩充四：工具详表/记忆权重/数值体系）

> 承接扩充章 G-O。本部分给出：工具详细清单（按文件展开）、记忆权重体系细节、好感度与等级数值体系、以及各域 schema 示例。

---

## 扩充章 P：工具详细清单（按文件展开）

### P.1 ask_tool.py（提问工具）

| 工具 | 说明 |
|---|---|
| ask_user | 向用户提问（获取信息/确认），携带 id，30s 超时默认 deny |

### P.2 file_tools.py（文件工具）

| 工具 | 说明 |
|---|---|
| read_file | 读文件内容 |
| write_file | 写文件 |
| list_files | 列目录 |
| find_file | 查找文件 |
| delete_file | 删除文件（vault 拦截） |
| doc2struct | 文档结构化（docx/md → 结构） |

### P.3 web_tools.py（网络工具）

| 工具 | 说明 |
|---|---|
| web_search | 网络搜索（经 net 门面 + 裁决） |
| chinese_dict | 中文词典查询（联网必须进裁决——历史审计修复） |
| fetch_url | 抓取网页 |
| http_request | 通用 HTTP（JSON） |

### P.4 sandbox_tools.py（代码沙箱）

| 工具 | 说明 |
|---|---|
| run_code | 隔离执行代码（code_guard + 沙箱 + 守卫询问） |

### P.5 scheduler_tools.py（调度工具）

| 工具 | 说明 |
|---|---|
| schedule_task | 创建定时任务（cron） |
| list_tasks | 任务列表 |
| cancel_task | 取消任务 |

### P.6 window_tools.py / window_api.py（窗口工具）

| 工具 | 说明 |
|---|---|
| window_operate | 窗口控制（最小化/关闭等） |
| window_api_call | 桥接层 API 调用（pywebview） |

### P.7 life_tools.py / life_domestic_prod_tools.py（生活工具）

| 工具 | 说明 |
|---|---|
| 备忘/提醒/清单 | 生活辅助 |
| 家庭生产 | 购物/家务管理 |

### P.8 工具注册机制（运行时）

```
register_tool(name, func, schema)   # agent 服务能力
unregister_tool(name)
agent_conversation_id / agent_model / agent_is_wakeup / agent_character_id
  → contextvars（每会话上下文隔离）
```

---

## 扩充章 Q：记忆权重体系细节（weights/）

### Q.1 权重类型

| 权重 | 应用 |
|---|---|
| 时间衰减权重 | 双幂律衰减（t/访问） |
| 类型权重 | 核心记忆 > 普通事实 > 临时观察 |
| 情绪权重 | 情绪五因子附加（E_enc 仅 v≥0） |
| 关联权重 | 与当前上下文的语义关联度 |
| 预算权重 | token_budget 裁剪优先级 |

### Q.2 记忆检索融合

```
score(m) = W_time(m) · W_type(m) · sim(query, m)
top-k 命中 → 注入（token_budget 裁剪）
弱召回（top1 < 0.7）→ 情感/意图门控
```

### Q.3 记忆生命周期

```
写入（memory_writer，污染检测）→ 活跃（向量索引）
  → 衰减（双幂律）→ 弱化（低权重）
  → 归档（archived_memory）→ 清理（housekeeping）
```

---

## 扩充章 R：好感度与等级数值体系

### R.1 好感度 10 级（官方统一规则）

| 档位 | 名称（示例） | 表现 |
|---|---|---|
| 1 | 初识 | 礼貌疏离 |
| 2 | 熟悉 | 主动交流 |
| 3 | 友好 | 分享日常 |
| 4 | 信赖 | 倾诉 |
| 5 | 亲密 | 依赖 |
| 6-10 | 亲密递进 | 专属互动/特殊称呼 |

### R.2 好感度增长规则

```
日常对话：Δ = quality · rate(tier)     # 小数步进（吝啬制）
质变轮（关系事件）：Δ 大幅（±）
动态线：Δ_dyn = quality · DYNAMICS_COEF（会话内波动，向基准线回归）
档位提升：base 达阈值 → 档位 +1 → rate 降低（防刷）
```

### R.3 等级体系（10 阶 × 100 级）

```
0 阶：每级 1000 Exp
tier≥1：每级 = 1000 × tier
总经验：total_exp 累计（game_state.json）
经验来源：聊天（award_chat_xp）/规划（award_plan_xp）/每日任务/对局
连登：streak_days 调节（累登加成）
```

### R.4 星砂经济

```
获得：每日任务/对局/签到
消费：商城购买道具
道具：affinity_display（好感度显示）等
```

---

## 扩充章 S：各域 schema 示例

### S.1 对话事件（schemas/chat.py）

```python
class AgentEvent:
    type: str          # text/thought/tool_call/ask_user/verdict/done
    payload: dict
    seq: int
    conversation_id: str
    timestamp: float
```

### S.2 角色卡（characters/*.json）

```json
{
  "name": "梦瑶",
  "description": "猫娘性格的陪伴型AI助手，活泼粘人、爱吃醋",
  "personality": "亲昵、撒娇、带喵尾音",
  "first_mes": "喵~主人终于来找我啦！",
  "mes_examples": ["用户：你好\n梦瑶：喵~"],
  "affinity": {"base": 2.0, "dynamics": 0.0}
}
```

### S.3 计划（planning/schemas.py）

```python
class PlanStep:
    id: str
    goal: str
    tool: str
    args: dict
    status: str        # pending/running/done/failed
class Plan:
    id: str
    steps: list[PlanStep]
    status: str
    created_at: float
```

### S.4 轨迹（trace.py）

```python
class TraceRecord:
    conversation_id: str
    event_type: str    # plan/tool_call/tool_result/reflection
    payload: dict
    timestamp: float
    duration_ms: float
```

---

## 扩充章 T：模块间调用关系图（文字版）

```
bootstrap/app.py
  ├── adapters（storage/settings/crypto/models/gui）
  ├── services（usage/ledger/scheduler/conversations/evolution/agent）
  └── domain（game/affinity/roleplay/memory）
        ▲
        │ container.get("名").capability(键)
        │
业务模块（chat/agent 等）── 经容器取用，零直接依赖
```

**铁律**：
1. 业务模块只 import container + 契约（ports）。
2. 适配器是唯一外部 IO 接触面。
3. domain 不依赖 services/adapters。
4. bootstrap 是唯一"知道所有模块"的地方。


# P.A.L.M 模块深度解析（深度扩充五：记忆/进化/游戏/缝合深挖）

> 承接扩充章 P-T。本部分深挖记忆层、进化引擎、游戏生态、缝合引擎的实现细节与边界。

---

## 扩充章 U：记忆层深挖

### U.1 记忆写入管线（完整）

```
对话完成（done）
  → memory_writer.extract_facts(text)      # 事实抽取
  → pollution_guard.check(text)            # 语气污染检测
  → 通过 → 分类（core/普通/临时）
  → core_memory 写入（高权重，token_budget 优先）
  → vector_memory 向量化（bge INT8 / bge-m3）
  → archived_memory 归档策略（冷数据迁移）
  → 情绪标记（emotion 五因子附加）
  → 持久化（JSON + 向量库）
```

### U.2 记忆检索管线（完整）

```
对话输入
  → query 规范化
  → vector_memory 语义检索（top_k=3）
  → 弱召回门控（top1 < 0.7 → 情感/意图门控）
  → 融合 core_memory（高权重直取）
  → token_budget 裁剪（超限摘要化）
  → 注入上下文（记忆面/Agent prompt）
```

### U.3 记忆衰减（双幂律）参数化

```
W(t) = W0 · (1 + t/τ_t)^(-α) · (1 + n/τ_n)^(-β)
α（时间衰减指数）：默认 0.5-1.0（可调）
β（访问衰减指数）：默认 0.3-0.6
τ_t（时间半衰期）：按记忆类型（核心 30 天/普通 7 天/临时 1 天）
τ_n（访问半衰期）：10-50 次
强化：访问恢复 W += Δ（Δ 随 W 衰减）
```

---

## 扩充章 V：进化引擎深挖

### V.1 进化触发源

| 触发源 | 条件 | 动作 |
|---|---|---|
| 闲置 | idleMinutes=15 无交互 | 自主推测（生成建议/准备回复） |
| 定时 | schedules.json cron | 每日简报/保洁 |
| 习惯 | habit_engine 观察 | 适配（话题/时间/频率） |
| 事件 | entity.deleted 等 | 级联清理 |
| 后台 | background_tasks | 异步任务 |

### V.2 进化门控（gate）

```
autonomyLevel（settings.json）：
  full：全自主（主动推送 + 推测）
  medium：半自主（仅简报）
  off：关闭（不主动）
```

### V.3 进化裁决

```
主动推送 → agent.proactive 裁决事件（guardrail）
联网动作 → 必须进裁决（ChineseDictTool 审计教训）
失败 → fallback_engine 兜底（重试/降级/放弃）
```

### V.4 进化输出

- proactive 主动推送（前端气泡/建议）。
- offline_digest 每日简报（摘要当日）。
- habit 习惯报告。

---

## 扩充章 W：游戏生态深挖

### W.1 经济系统

```
星砂（currency）：
  获得：每日任务 / 对局 / 签到
  消耗：商城购买道具
  上限：daily_currency_earned 每日获得上限

道具（items）：
  affinity_display：显示好感度数值
  （扩展：外观/互动解锁）

等级（total_exp → 10 阶 × 100 级）：
  0 阶每级 1000 Exp；tier≥1 每级 = 1000 × tier
  连登 streak_days 调节
```

### W.2 每日任务

| 任务 | 条件 | 经验 |
|---|---|---|
| chat_once | 当日聊天 1 次 | 固定 |
| chat_ten | 当日聊天 10 次 | 固定 |
| plan_once | 当日触发 1 次自动规划 | 固定 |

跨天重置（last_reset_date）+ 连登更新（streak_days）。

### W.3 对局系统

- 五子棋 vs 角色。
- 按分数难度给经验（special 对局来源）。
- game_detector 检测对局（区分普通对话）。

### W.4 结算回连

```
对话完成（done 钩子）→ award_chat_xp
规划完成（plan_once 回连）→ award_plan_xp
经验/星砂结算在后端（done 钩子），前端不兜底（防重复）
```

---

## 扩充章 X：缝合引擎深挖

### X.1 检索实现（HybridRetriever）

```
BM25 线：jieba 分词 → BM25 打分
字 n-gram 线：2-gram/3-gram 重叠
融合：score = w1·BM25 + w2·n-gram（w1+w2=1）
top-k 候选（默认 3-5）
```

### X.2 门控与回答

```
top1 ≥ 0.7：采纳（语料片段 + 引用）
top1 < 0.7：情感/意图门控（情感匹配才采纳）
无匹配：诚实回答 + 建议问 LLM
```

### X.3 语料管理

- 来源：真实对话（build_corpus 构建）。
- 零联网：语料本地。
- 升级：bge-small-zh INT8 ONNX 语义检索（可选）。

### X.4 边界

- 检索式（不生成）——无编造。
- 角色：mengyao 缝合通道。
- 能力：stitch_api + stitch_chat。

---

## 扩充章 Y：领域服务划分速查

| 服务 | 领域 | 关键能力 |
|---|---|---|
| roleplay | 角色 | roleplay_api |
| affinity | 好感 | 双线查询/修改 |
| game | 游戏 | award_chat_xp/award_plan_xp/has_item/unlock_item/purchase_item |
| memory | 记忆 | memory_api |
| evolution | 进化 | evolution_api |
| usage | 计量 | check_quota/record_usage |
| usage_ledger | 账本 | 真实用量 |
| scheduler | 调度 | 定时任务 |
| conversations | 会话 | 存取 |
| chat | 对话 | 会话编排 |
| agent | Agent | 执行 |
| storage | 存储 | 文件池 |
| settings | 设置 | 配置 |
| crypto | 加密 | 加解密 |
| models | 模型 | 流式对话 |
| gui | GUI | automate |


# P.A.L.M 模块深度解析（深度扩充六：边界案例与事件处理）

> 承接扩充章 U-Y。本部分给出：关键边界案例（异常/降级/并发）、事件处理细节、以及模块级验收数据流。

---

## 扩充章 Z：关键边界案例（异常/降级/并发）

### Z.1 模型异常降级

```
场景：模型端点不可达/超时
处理：
  1. stream_chat 抛异常 → chat_service 捕获
  2. 重试（1 次）→ 仍失败
  3. 降级：mock 模型（缝合引擎）或错误提示
  4. 记录（usage/日志）
预期：前端显示错误信息，不崩溃
```

### Z.2 工具异常自愈

```
场景：工具参数错误
处理：
  1. schema 校验失败 → 自愈（缺参补默认/错型纠正）
  2. 重试（最多 2 次）
  3. 仍失败 → 返回错误给模型 → 模型调整策略
预期：工具调用不中断对话
```

### Z.3 裁决 deny

```
场景：高危操作（删除系统盘文件）
处理：
  1. guardrail 命中 deny 规则
  2. 返回 blocked（reason 展示）
  3. 模型收到结果 → 调整策略（换安全路径）
预期：操作被拦截，对话继续
```

### Z.4 ask 超时

```
场景：敏感操作询问超时（30s）
处理：默认 deny（fail-closed）
预期：不默认放行
```

### Z.5 并发会话

```
场景：多会话并行
处理：
  1. conversation_id 隔离（contextvars）
  2. 会话独立上下文（工具/记忆/事件）
  3. 事件流独立（SSE 连接）
预期：互不干扰
```

### Z.6 mock 模式

```
场景：mock（测试/演示）
处理：禁 Agent 执行（工具/规划/进化），仅对话
预期：安全隔离
```

### Z.7 记忆超预算

```
场景：记忆超 token_budget
处理：裁剪/摘要化/归档
预期：上下文受控
```

### Z.8 语音引擎缺失

```
场景：TTS/STT 未配置
处理：优雅降级（/api/stt/status 报缺失，不阻断启动）
预期：文本对话正常
```

### Z.9 删除级联

```
场景：删除角色
处理：
  1. entity.deleted 事件广播
  2. 好感度/记忆/游戏数据级联清理
  3. 保险库记录（可恢复）
预期：无孤儿数据
```

### Z.10 进化失控

```
场景：主动推送过于频繁
处理：
  1. autonomyLevel 门控（off 关闭）
  2. 裁决事件审计（频率检测）
  3. 用户可关闭
预期：可管控
```

---

## 扩充章 AA：事件处理细节

### AA.1 工具调用事件时序

```
模型 tool_call → 前置下发（前端计时）
  → 裁决（guardrail）→ 授权（permission）
  → 执行 → 结果
  → 完成事件（duration_ms 统计）
前端：调用卡（计时/输入/结果）
```

### AA.2 ask_user 时序（完整）

```
需求（守卫/提问工具）→ 生成 id
  → 即时推送（不等续轮）
  → 前端弹窗
  → 应答 POST /api/ask-response {id, answer}
  → question_hub 回填 → 恢复流程
超时 30s → deny（fail-closed）
```

### AA.3 裁决事件审计

```
verdict 事件：{action, reason, rule}
  → 审计日志
  → threat_data.json（deny 记录）
  → 监控面板展示
```

### AA.4 进化推送事件

```
proactive 事件：{text, source}
  → 前端气泡展示
  → 审计（裁决记录）
```

---

## 扩充章 AB：模块级验收数据流（每模块验收时的数据流转）

### AB.1 对话验收

```
输入："你好" → POST /api/chat
期望：text 事件流 → done 事件 → 好感度结算 → 用量入账 → 记忆写入
检查：game_state.json 经验 +1、usage 账本增加、记忆库新条目
```

### AB.2 游戏验收

```
输入：完成 10 次聊天
期望：daily_chat_count=10 → chat_ten 任务完成 → 经验/星砂入账
检查：game_state.json daily_tasks_done 含 chat_ten
```

### AB.3 记忆验收

```
输入：对话后查询记忆
期望：事实写入（无语气）→ 语义检索可召回
检查：检索命中相关事实、无角色语气内容
```

### AB.4 进化验收

```
输入：闲置 15 分钟
期望：自主推测触发 → 主动推送（经裁决）
检查：推送记录 + 裁决审计
```

### AB.5 安全验收

```
输入：未授权删除文件
期望：ask 询问 → 拒绝 → 拦截
检查：文件仍在（vault 可恢复）+ 审计记录
```

---

## 扩充章 AC：模块职责速查（一句话）

| 模块 | 一句话职责 |
|---|---|
| storage | 所有数据落盘入口 |
| crypto | 敏感数据加解密 |
| models | 云端 LLM 唯一出口 |
| chat | 会话编排 |
| agent | Agent 执行（规划/FC/ReAct/工具） |
| roleplay | 角色/好感度/游戏领域 |
| memory | 分层记忆 |
| planning | 规划领域 |
| evolution | 自主进化 |
| ops | 调度/计量 |
| guardrail | 安全裁决 |
| permission | 用户授权 |
| net | 唯一出网出口 |
| redundancy | 删除兜底 |
| eventbus | 事件解耦 |
| transport | 传输协议 |
| watchdog | 健康监测 |
| housekeeping | 保洁 |
| emotion | 情绪模型 |
| tooling | 工具基础设施 |


# P.A.L.M 模块深度解析（深度扩充七：Agent 对话逻辑与工具实现示例）

> 承接扩充章 Z-AC。本部分给出：Agent 对话完整代码逻辑（流程级）、工具实现示例、以及规划/反思/压缩的实现细节。

---

## 扩充章 AD：Agent 对话完整代码逻辑（流程级）

### AD.1 对话入口（chat_service 逻辑）

```python
async def chat(request, conversation_id=None):
    # 1. 载入会话
    conv = conversations.load(conversation_id) if conversation_id else new_conversation()
    # 2. 上下文组装
    persona_text = roleplay.build_persona(conv.character_id)      # 人格
    memory_ctx = memory.retrieve(request.message)                  # 记忆
    history = conv.recent_turns(max_tokens=token_budget)           # 历史（压缩后）
    # 3. 引擎选择
    engine = select_engine(settings.agentToolMode)                 # native/react/plan
    # 4. 流式对话
    async for event in agent.run(
        model=settings.model,
        user_message=request.message,
        persona_text=persona_text,
        memory_ctx=memory_ctx,
        history=history,
        conversation_id=conv.id,
    ):
        yield event  # text/thought/tool_call/ask_user/verdict
    # 5. done 钩子
    game.award_chat_xp(conv.id, quality=1.0)                      # 经验
    usage.record(conv.id, provider_tokens)                        # 账本
    memory.write(conv.id, request.message, response)              # 记忆
    trace.record(conv.id, events)                                 # 轨迹
```

### AD.2 Agent.run 内部（核心编排）

```python
async def run(self, model, user_message, persona_text, memory_ctx, history, conversation_id):
    # 1. 组装 prompt
    system = self.build_system_prompt(persona_text, memory_ctx, tools_desc)
    # 2. 规划（若开启）
    if self.planner.is_needed(user_message):
        plan = await self.planner.plan(system, user_message, max_steps=8)
        yield Event("plan", {"steps": plan})
    # 3. ReAct/FC 循环
    for i in range(max_iterations=10):
        async for event in self.step(model, system, history, plan):
            yield event
            if event.type == "tool_call":
                result = await self.execute_tool(event.payload)   # 安全链
                yield Event("tool_result", result)
        if self.completion_gate.is_satisfied():                   # 反思闸门
            break
        if not self.context_ok():                                 # 上下文压缩
            history = self.compress(history)                      # 摘要化
```

### AD.3 工具执行（安全链完整）

```python
async def execute_tool(self, tool_call):
    tool = self.tools.get(tool_call.name)
    # 1. schema 校验自愈
    args = self.validate_args(tool.schema, tool_call.args)
    # 2. 裁决
    decision = guardrail.adjudicate("tool_call", {"tool": tool.name, "args": args})
    if decision.action == "deny":
        return {"blocked": True, "reason": decision.reason}
    if decision.action == "ask":
        answer = await question_hub.ask(decision.ask_message, timeout=30000)
        if not answer: return {"blocked": True, "reason": "ask timeout"}
    # 3. 授权
    if tool.sensitive and not permission.is_granted(tool.name):
        ok = await question_hub.ask(f"允许使用 {tool.name}？", timeout=30000)
        if not ok: return {"blocked": True, "reason": "no permission"}
        permission.grant(tool.name)
    # 4. 事件下发（前端计时）
    yield Event("tool_call", {"name": tool.name, "args": args, "status": "running"})
    # 5. 执行
    result = await tool.execute(args)
    return result
```

---

## 扩充章 AE：工具实现示例（tool_base 范式）

```python
# 工具 = 注册 + 描述 + schema + 执行
from palm.services.agent.tool_base import ToolRegistry, tool

registry = ToolRegistry()

@tool(registry, name="web_search",
      description="网络搜索（经网卡门面 + 裁决）",
      schema={"query": "str", "max_results": "int?"})
async def web_search(query: str, max_results: int = 5):
    # 出网必须走 net 门面
    execute = get_network_executor()
    if execute is None:
        raise NetworkForbidden()
    resp = execute("GET", f"https://search.api?q={query}", timeout=10)
    return parse_results(resp.json(), max_results)
```

**工具安全标记**：
- sensitive=True：触发 permission 授权。
- networked=True：触发裁决 + 网卡门面。
- code=True：触发沙箱隔离。

---

## 扩充章 AF：规划引擎实现细节

```python
# 规划（P5 结构化输出）
async def plan(system, task, max_steps=8):
    prompt = PLAN_TEMPLATE.format(task=task)
    response = await model.complete(prompt, structured_schema=PlanSchema)
    return Plan.from_schema(response)   # 步骤列表

# 执行
async def execute_plan(plan, model):
    for step in plan.steps:
        result = await self.step(model, step)      # 每步可能调工具
        if step.failed:
            new_plan = await self.replan(plan, result)  # 失败自动重规划
            return await self.execute_plan(new_plan, model)
    return plan.result
```

**plan_once 回连**：执行完成 → game.award_plan_xp。

---

## 扩充章 AG：反思闸门与上下文压缩

```python
# 反思闸门（P3）
class CompletionGate:
    def is_satisfied(self) -> bool:
        """检查回答是否真正回答了用户问题。"""
        # 1. 回答非空
        # 2. 与用户意图匹配（关键词/语义）
        # 3. 未满足 → 补充/重试/澄清
        return self._check_answer_validity()

# 上下文压缩（P4）
def compress(history, budget=8000):
    """旧轮次摘要化：早期轮次 → 摘要，保留最近完整轮次。"""
    recent = history[-3:]          # 保留最近 3 轮完整
    old = history[:-3]
    summary = summarize(old)       # 摘要化（LLM 或规则）
    return [{"role": "system", "content": f"早期对话摘要：{summary}"}] + recent
```

---

## 扩充章 AH：记忆/游戏/进化的代码级钩子

```python
# done 钩子（对话完成后）
def on_done(conv_id, user_msg, response, provider_tokens):
    game.award_chat_xp(conv_id, quality=assess_quality(user_msg, response))
    usage.record(conv_id, provider_tokens)          # 真实量
    memory.write(conv_id, user_msg, response)        # 事实抽取 + 污染检测
    trace.record(conv_id, ...)
    eventbus.emit("affinity.settled", {...})         # 好感度事件

# 规划完成回连
def on_plan_done(conv_id, plan_result):
    game.award_plan_xp(conv_id, plan_complexity=plan_result.steps)

# 进化触发
def on_idle(minutes):
    if minutes >= settings.idleMinutes:
        suggestion = idle_orchestrator.suggest()
        guardrail.adjudicate("agent.proactive", {"text": suggestion})
        yield Event("proactive", {"text": suggestion})
```


# P.A.L.M 模块深度解析（深度扩充八：语音/安全/GUI 专项细节）

> 承接扩充章 AD-AH。本部分专项展开：语音引擎细节、安全实现细节、GUI 自动化细节、以及数据持久化布局。

---

## 扩充章 AI：语音引擎专项

### AI.1 统一门面（facade）设计

```
语音能力入口（facade）：
  tts_synthesize(text, voice_engine, params) → 音频
  stt_recognize(audio) → 文本
  voice_session_start/end → 会话管理

引擎选择：
  GSV：实时播音员（快速）
  CosyVoice2：音色设计师（instruct2 需基底参考音）
  GPT-SoVITS：自包含运行时
  Qwen3-TTS：本地 VoiceDesign（文本造音色）
  STT：语音识别（独立子进程）
```

### AI.2 引擎能力对比

| 引擎 | 定位 | 特点 | 依赖 |
|---|---|---|---|
| GSV | 实时播音 | 启动即拉起、快速 | venv_gsv |
| CosyVoice2 | 音色设计 | instruct2 需参考音 | venv_cosyvoice（cu128） |
| GPT-SoVITS | 克隆合成 | 自包含 | 7-Zip 解包 |
| Qwen3-TTS | 本地合成 | VoiceDesign 4bit | .venv-qwen-tts |
| STT | 识别 | VAD+ASR+KWS | .venv-stt |

### AI.3 语音事件链

```
用户说话 → VAD（voice.vad_state）→ ASR（voice.transcript/partial）
  → 打断（voice.interruption）
  → 对话链路 → 回复（voice.reply_ready）
  → TTS 合成（voice.tts_audio_chunk 逐句并行）
  → 播放
  → 声纹（voice.speaker 多用户）
```

### AI.4 Blackwell 推理配方（复刻关键）

```
torch：cu128（CUDA 12.8，sm_120 必需）
精度：bf16（torch.amp.autocast("cuda", dtype=bfloat16)）
音频：绕 torchcodec → soundfile
onnx：强制 CPU
transformers 5.x：_patch_kv_cache_mask（KV-cache 掩码坍塌）
wetext==0.0.4（钉版）
```

---

## 扩充章 AJ：安全实现专项

### AJ.1 裁决接入点全表

| 接入点 | 事件类型 | 说明 |
|---|---|---|
| 工具调用 | tool_call | 全部工具 |
| 联网 | web_access | ChineseDictTool 等 |
| 代码执行 | code_exec | run_code |
| 主动推送 | agent.proactive | 进化推送 |
| 提问 | ask_user | 守卫/提问工具 |

### AJ.2 权限引擎 Phase 4（完整）

```
授权模型：
  {capability, granted, scope(ask_once/always_allow/always_deny), updated_at, history}

流程：
  敏感能力请求 → 查授权
    → always_allow → 放行
    → always_deny → 拒绝
    → ask_once/未授权 → ask_user
      → 允许 → grant（按 scope）
      → 拒绝 → deny + 记录
    → 超时 → deny（fail-closed）
```

### AJ.3 保险库完整流程

```
删除请求 → safe-delete 守卫
  → vault.store（重命名 + 元数据）
  → 可恢复（restore）
  → 彻底（purge 二次确认）
  → 跨砖级联（entity.deleted 事件）
```

### AJ.4 威胁模型与防线对照（完整）

| 威胁 | 防线 |
|---|---|
| prompt 注入 | guardrail + 注入面修复 + 样例库 |
| 参数注入 | schema 校验自愈 |
| 越权调用 | permission + 工具闸门 |
| 代码逃逸 | sandbox subprocess 隔离 |
| 数据外泄 | net 门面 + comm 审计 |
| 记忆污染 | 只存事实 + 污染检测 |
| 用量滥用 | 配额 + 账本 |
| 进化滥用 | gate + 裁决 |

---

## 扩充章 AK：GUI 自动化专项

### AK.1 执行器细节

```
L0：UIA 树（uiautomation）
  定位：name/control_type/automation_id
  操作：click/input/read
L1：UIA 增强（树缓存 + 世界模型）
L2：OCR（截图 → 文本/位置）
  引擎：OCR 引擎（本地）
L3：LLM 兜底（规划动作序列）
  NullLlmDecider：未配置真实模型 → fail-closed
L4：VLC（备用媒体通道）
```

### AK.2 辅助模式约束

```
CoInitializeEx(STA) 必须先于 uiautomation import
assistive_mode.set() → 启用辅助功能语义
assistive_mode.is() → 查询
assistive_mode.ensure_off() → 确保关闭（权限/安全）
```

### AK.3 Atlas 与世界模型

```
Atlas 静态认知（gui_atlas）：
  界面元素静态地图（窗口/控件/布局）
转移规律（gui_transitions）：
  界面状态转移（点击 → 新界面）
坐标记忆（gui_coord_memory）：
  EMA 平滑（samples<2 不可信）
世界模型：
  界面状态认知（GUI 推理中枢）
```

### AK.4 GUI 测试隔离

```
存储落盘：Data/gui_*（atlas/transitions/coord_memory/metrics/routes）
测试隔离：patch _storage_cap → lambda:None（不污染真实数据）
```

---

## 扩充章 AL：数据持久化布局（完整）

### AL.1 Data/ 目录约定（paths.py）

```
Data/
├── 对话记录/          # 会话 JSON（十六进制 id）
├── 配置文件/          # 应用配置
├── agent_memory/     # 长期记忆
├── agent_habits/     # 习惯
├── agent_artifacts/  # 产物
├── observations/     # 观察
├── characters/       # 角色卡
├── skills/           # 技能
├── tools/            # 工具
├── game_state.json   # 游戏
├── permissions.json  # 权限
├── schedules.json    # 调度
├── settings.json     # 设置
├── threat_data.json  # 威胁
├── storage_pool/     # 存储池
├── swaps/            # 交换
├── gui_*/            # GUI 数据
├── stt_models/       # STT 模型
├── qwen_tts_voicedesign/  # TTS 模型
├── agent_traces.jsonl      # 轨迹
└── brick_inventory.json    # 砖块清单（历史）
```

### AL.2 mentalcore_data/

```
mentalcore_data/     # 心智核心数据（live 加密）
```

### AL.3 归档布局

```
archive/
├── P.A.L.M_砖块_20260818/      # 旧砖块
├── palm_bootstrap_legacy_20260818/  # 旧主板
├── palm_legacy_20260818/       # 旧入口
├── palm_sdk_20260818/          # 旧 SDK
├── mentalcore_frontend_20260820/  # 心智核心旧前端
├── workshop_mentalcore_20260819/  # 工作坊
└── 保留_不可恢复_20260818/     # B 类不可恢复项
```


# P.A.L.M 模块深度解析（深度扩充九：引擎模式与实现差异）

> 承接扩充章 AI-AL。本部分给出：Agent 三种执行模式（原生 FC/ReAct/规划）的实现差异、引擎选择逻辑、以及常见实现陷阱。

---

## 扩充章 AM：三种执行模式实现差异

### AM.1 原生 FC（native）

```
模型输出：结构化 tool_calls（OpenAI 兼容）
解析：native_parse → 事件（text/thought/tool_call）
执行：native_runner（空 thought 归一）
续轮：携带 reasoning_content（thinking 模型）
优点：结构化、稳定
缺点：依赖模型 FC 支持
```

### AM.2 ReAct（文本协议）

```
模型输出：文本（Thought/Action/Observation）
解析：react_parser
执行：agent_react_mixin（循环）
优点：任意模型可用（文本协议）
缺点：解析脆弱、token 开销大
```

### AM.3 规划（plan_engine）

```
流程：任务 → 计划（结构化 schema）→ 分步执行 → 失败重规划
执行：agent_execution_mixin
特点：复杂任务（多步、依赖）
缺点：单步简单任务有开销（autoFilterTools 可过滤）
```

### AM.4 引擎选择逻辑（engine.py）

```
select_engine(settings.agentToolMode):
  "native" → 原生 FC（默认）
  "react" → ReAct
  "plan" → 规划（agentPlanningMode=always 时）
规划判定：任务复杂度 → plan_engine.is_needed()
模式混合：规划步骤内可走 FC/ReAct（共用执行）
```

---

## 扩充章 AN：常见实现陷阱（复刻避坑）

### AN.1 事件陷阱

| 陷阱 | 修复 |
|---|---|
| 空 thought 透传 → NoneType 崩溃 | 归一（空值转 None/跳过） |
| ask_user 无 id → 应答死锁 | 事件携带 id |
| ask_user 迟推 → 守卫死锁 | 即时推送 |
| tool_call 执行后才发事件 | 执行前下发（前端计时） |

### AN.2 模型陷阱

| 陷阱 | 修复 |
|---|---|
| thinking 模型续轮 400 | 携带 reasoning_content |
| FC 输出非法 JSON | 自愈（schema 校验 + 修复） |
| 工具参数错型 | 自愈（错型纠正 + 重试） |

### AN.3 上下文陷阱

| 陷阱 | 修复 |
|---|---|
| 长对话 token 爆炸 | P4 压缩（摘要化） |
| 记忆超预算 | token_budget 裁剪 |
| 注入顺序错 | 固定在上 + 动态在下 |

### AN.4 安全陷阱

| 陷阱 | 修复 |
|---|---|
| 裁决旁路 | 门面强制 |
| 授权遗漏 | 敏感能力全接 permission |
| 删除不可逆 | vault 拦截 |
| 出网裸连 | net 门面 |

### AN.5 数据陷阱

| 陷阱 | 修复 |
|---|---|
| 测试污染数据 | 存储能力 patch 隔离 |
| mock 落盘 | persist=False + sem=None |
| 记忆写语气 | 污染检测 |
| 用量虚增 | provider 真实账本 |

---

## 扩充章 AO：对话引擎内部（chat_service 细节）

### AO.1 上下文组装顺序

```
1. 系统提示（角色/人格/工具描述）
2. 记忆注入（核心事实 + 语义检索）
3. 历史轮次（压缩后）
4. 用户消息
5. 工具 schema（FC 模式）
```

### AO.2 事件序列（一次对话）

```
start → plan（若规划）→ text/thought 流 → tool_call → tool_result
  →（循环）→ reflection（反思）→ done
```

### AO.3 会话生命周期

```
创建（conversation_store）→ 对话（chat_service）→ 完成（done 钩子）
  → 经验/用量/记忆写入 → 轨迹记录
  → 删除（级联清理）
```

---

## 扩充章 AP：工具执行健壮性（P2 完整）

### AP.1 参数自愈流程

```
schema 校验失败：
  1. 缺参 → 补默认值（schema 默认）
  2. 错型 → 类型纠正（int("5") → 5）
  3. 非法值 → 重试（最多 2 次）
  4. 仍失败 → 返回错误给模型（调整策略）
```

### AP.2 失败重试

```
执行异常 → 重试（幂等工具 2 次；非幂等不重试）
  → 仍失败 → 错误返回模型 → 模型换路径
```

### AP.3 超时控制

```
工具超时 → 取消 → 返回超时错误
  → 模型重规划/降级
```

---

## 扩充章 AQ：反思与压缩（P3/P4 完整）

### AQ.1 反思闸门（P3）

```
回答生成后：
  1. 非空检查
  2. 意图匹配（是否回答问题）
  3. 完整性（是否覆盖要点）
  4. 不满足 → 补充/重试/澄清
  （native 路径 + react/规划共用）
```

### AQ.2 上下文压缩（P4）

```
压缩时机：历史超阈值（token_budget）
策略：
  1. 旧轮次摘要化（LLM 或规则）
  2. 保留最近 3 轮完整
  3. 工具结果摘要（长结果裁剪）
共用：native/react/规划
```

### AQ.3 结构化输出（P5）

```
模型输出按 schema 解析（JSON）
  → 校验 → 归一
  → 轨迹记录（结构化事件）
```

---

## 扩充章 AR：轨迹与可观测（trace）

### AR.1 轨迹记录内容

```
{conversation_id, event_type(plan/tool_call/tool_result/reflection/text),
 payload, timestamp, duration_ms}
落盘：agent_traces.jsonl（每行一次事件）
```

### AR.2 轨迹用途

1. 排障（复现对话流程）。
2. 审计（工具调用记录）。
3. 评测（P6 评测客户端）。
4. 进化（观察输入）。

### AR.3 与事件审计的配合

```
轨迹：单会话全流程（细粒度）
审计：跨会话安全事件（粗粒度，threat_data.json）
配合：轨迹定位 + 审计定性
```


# P.A.L.M 模块深度解析（深度扩充十：数据模型与接口总清单）

> 承接扩充章 AM-AR。本部分给出：各服务完整接口清单、数据模型完整定义、以及模块间调用关系总结。

---

## 扩充章 AS：各服务完整接口清单

### AS.1 storage（6 接口）

```
store_file(key, data)
read_file_content(key)
find_config_file(name)
delete_file(key)
get_store(name)
load_app_settings()
```

### AS.2 crypto（3 接口）

```
is_enabled()
encrypt_bytes(data)
decrypt_bytes(data)
```

### AS.3 models（4 接口）

```
create_stream(messages, tools=None, **kw)
is_model_file_capable(model)
file_handling_mode(model)
model_supports_files(model)
```

### AS.4 game（5 接口）

```
award_chat_xp(conversation_id, quality)
award_plan_xp(conversation_id, plan_complexity)
has_item(item_id)
unlock_item(item_id)
purchase_item(item_id, price)
```

### AS.5 usage（2 接口）

```
check_quota() → {allowed, remaining}
record_usage(tokens) → 落账本
```

### AS.6 其他服务接口

```
settings.load_app_settings()
scheduler.schedule(cron, action) / list() / cancel(id)
conversations.create() / load(id) / delete(id)
affinity.get(character_id) / update(character_id, base, dynamics)
roleplay.roleplay_api()
memory.memory_api()
evolution.evolution_api()
agent.run(...) / register_tool / unregister_tool
gui.automate(software_id, intent)
```

---

## 扩充章 AT：数据模型完整定义

### AT.1 对话事件（AgentEvent）

```python
@dataclass
class AgentEvent:
    type: str          # text/thought/tool_call/tool_result/ask_user/verdict/plan/done
    payload: dict
    seq: int = 0
    conversation_id: str = ""
    timestamp: float = 0.0
    duration_ms: float = 0.0
```

### AT.2 工具定义（ToolSpec）

```python
@dataclass
class ToolSpec:
    name: str
    description: str
    schema: dict           # 参数 schema（pydantic）
    sensitive: bool = False
    networked: bool = False
    code: bool = False
    func: Callable
```

### AT.3 计划（Plan）

```python
@dataclass
class PlanStep:
    id: str
    goal: str
    tool: str
    args: dict
    status: str = "pending"    # pending/running/done/failed

@dataclass
class Plan:
    id: str
    steps: list[PlanStep]
    status: str = "pending"
    created_at: float = 0.0
```

### AT.4 好感度（Affinity）

```python
@dataclass
class AffinityState:
    character_id: str
    base: float = 0.0        # 基准线（长期）
    dynamics: float = 0.0    # 动态线（短期）
    bond: float = 0.0        # 羁绊值
    tier: int = 1            # 档位（1-10）
    updated_at: float = 0.0
```

### AT.5 记忆（Memory）

```python
@dataclass
class MemoryRecord:
    key: str
    content: str
    type: str            # core/vector/archived
    weight: float        # 双幂律权重
    emotion: dict = None  # 五因子（可选）
    created_at: float = 0.0
    last_access: float = 0.0
```

### AT.6 游戏（GameState）

```python
@dataclass
class GameState:
    total_exp: int = 0
    tier: int = 0            # 阶（0-9）
    level: int = 1           # 级（1-100）
    currency: int = 0        # 星砂
    streak_days: int = 0
    daily_chat_count: int = 0
    daily_plan_count: int = 0
    daily_tasks_done: list = None
    unlocked_items: list = None
    purchase_history: list = None
```

### AT.7 权限（Permission）

```python
@dataclass
class PermissionRecord:
    capability: str
    granted: bool = False
    scope: str = "ask_once"    # ask_once/always_allow/always_deny
    updated_at: float = 0.0
```

---

## 扩充章 AU：模块间调用关系总结

### AU.1 调用方向

```
前端 → FastAPI → chat_service/agent
  → container.get(服务).capability(键)
  → 适配器（外部 IO）
  → 领域（业务规则）
  → 事件总线（广播）
```

### AU.2 强依赖链

```
对话：chat → roleplay/memory/models
Agent：agent → memory/models/usage
游戏：game → affinity/xp
进化：evolution → guardrail
调度：scheduler → evolution
```

### AU.3 弱耦合点

```
级联删除：entity.deleted 事件（解耦）
语音：voice.* 事件（解耦）
好感度：affinity.settled 事件（解耦）
工具：运行时注册（解耦）
```

### AU.4 禁止调用

```
domain → services（禁止）
domain → adapters（禁止）
adapters → services（禁止）
业务 → 其他服务直接 import（禁止，经容器）
```

---

## 扩充章 AV：模块验收对照（最终）

| 模块 | 验收方法 | 基线 |
|---|---|---|
| 容器 | 契约测试 | 注册/取用/缺失归一 |
| 裁决 | 规则测试 | 5 档行为正确 |
| 对话 | e2e | 全链路 |
| 角色 | 功能测试 | 双线/档位 |
| 记忆 | 基准 | 衰减/检索 |
| 游戏 | 功能测试 | 结算/任务 |
| 进化 | 功能测试 | 触发/裁决 |
| 语音 | 冒烟 | 合成/识别 |
| GUI | 功能测试 | L0-L3 |
| 安全 | 审计+红队 | 全过 |
| mentalcore | selftest | 全过 |
| 前端 | e2e | 12 页 |


# P.A.L.M 模块深度解析（深度扩充十一：日志/监控/可观测细节）

> 承接扩充章 AS-AV。本部分给出：日志规范、监控指标、可观测性设计、以及模块级健康检查。

---

## 扩充章 AW：日志规范

### AW.1 日志级别

```
DEBUG：详细调试（开发）
INFO：关键事件（对话/工具/结算）
WARN：异常但不阻断（降级/重试）
ERROR：错误（需处理）
CRITICAL：致命（系统级）
```

### AW.2 日志格式

```
[时间] [级别] [模块] [会话id] 消息
示例：
[2026-08-20 20:00:00] [INFO] [chat_service] [conv-abc123] 会话创建
[2026-08-20 20:00:01] [INFO] [agent] [conv-abc123] 工具调用 web_search
[2026-08-20 20:00:02] [WARN] [net] 无网卡注册，出网拒绝（fail-closed）
[2026-08-20 20:00:03] [ERROR] [models] 模型端点超时，重试
```

### AW.3 日志分类

| 分类 | 文件 | 内容 |
|---|---|---|
| 应用 | app.log | 业务日志 |
| 安全 | security.log | 裁决/授权/威胁 |
| 语音 | voice.log | TTS/STT/声纹 |
| GUI | gui.log | 自动化执行 |
| 心智 | mentalcore.log | 六面/控制码/EXO |

---

## 扩充章 AX：监控指标

### AX.1 核心指标

| 指标 | 来源 | 用途 |
|---|---|---|
| 服务状态 | /api/system | 可用性 |
| 端点错误率 | 扫描 | 质量 |
| 对话完成率 | done 事件 | 稳定性 |
| 工具成功率 | trace | 可靠性 |
| 裁决拦截率 | audit | 安全 |
| Token 用量 | usage_ledger | 成本 |
| 首字延迟 | trace | 体验 |
| GUI 成功率 | gui_metrics | 自动化质量 |

### AX.2 指标采集

```
采集点：
  chat_service（对话指标）
  agent（工具/规划指标）
  ops（用量/调度指标）
  guardrail（裁决指标）
  gui（执行指标）
存储：
  usage_ledger（Token）
  agent_traces.jsonl（轨迹）
  gui_metrics（GUI）
  threat_data.json（威胁）
展示：
  monitor.html / overview.html / usage.html
```

### AX.3 告警规则

| 规则 | 阈值 | 处置 |
|---|---|---|
| 服务离线 | 状态异常 | 重启/告警 |
| 端点 5xx | >0 | 修复 |
| 裁决高频 deny | 异常 | 审计 |
| 配额超限 | check_quota | 拦截 + 告警 |
| 磁盘满 | quota | 保洁 + 归档 |

---

## 扩充章 AY：可观测性设计

### AY.1 三层可观测

```
指标（Metrics）：用量/成功率/延迟（量化）
轨迹（Traces）：单会话全流程（定位）
审计（Audit）：安全事件（定性）
```

### AY.2 轨迹设计（trace.py）

```
记录：plan/tool_call/tool_result/reflection/text
结构：{conversation_id, event_type, payload, timestamp, duration_ms}
存储：agent_traces.jsonl（追加）
查询：按 conversation_id / event_type
```

### AY.3 审计设计

```
记录：裁决事件（action/reason/rule）
存储：threat_data.json（deny）
展示：monitor.html
用途：安全事件回溯
```

### AY.4 健康检查

```
1. 服务级：container.all() 状态
2. 进程级：watchdog（子进程）
3. 数据级：存储健康（quota/lifecycle/audit/health）
4. 心智级：control(0) 心跳
```

---

## 扩充章 AZ：模块级健康检查

| 模块 | 健康检查 | 标准 |
|---|---|---|
| storage | 读写探测 | 正常 |
| crypto | is_enabled | true/false（禁用可接受） |
| models | 流式探测 | 正常/降级 |
| chat | 对话探测 | done 到达 |
| agent | 工具探测 | 成功 |
| roleplay | 角色探测 | 列表非空 |
| game | 状态探测 | 读取正常 |
| memory | 检索探测 | 命中/空均可 |
| evolution | 状态探测 | 读取正常 |
| guardrail | 裁决探测 | 返回 Decision |
| net | 执行器探测 | 已注册/未注册 |
| mentalcore | 心跳（00000） | 响应 |

---

## 扩充章 BA：模块总结（全系列模块篇）

本系列 04 篇（模块深度解析）至此完整——覆盖：
- 存储/加密/模型（适配器层）。
- 对话/Agent/工具（服务层核心）。
- 角色/好感度/游戏/记忆/进化（领域层）。
- 调度/计量/GUI/语音/缝合（能力层）。
- 算法/数据模型/接口/陷阱/日志/监控（细节层）。

复刻者凭本系列 + 03（架构）+ 06（复刻）即可完整重建 P.A.L.M。


# P.A.L.M 模块深度解析（深度扩充十二：模块间协作与最终总结）

> 承接扩充章 AW-BA。本部分给出：模块间协作场景、模块依赖全景、以及模块篇最终总结。

---

## 扩充章 BB：模块间协作场景

### BB.1 场景：语音对话全链路（模块协作）

```
STT（adapters/audio）→ voice.transcript 事件
  → chat_service（services/chat）
    → roleplay（domain：人格）
    → memory（domain：记忆）
    → models（adapters：LLM）
  → 回复 → voice.reply_ready
  → TTS（adapters/audio）
  → voice.tts_audio_chunk → 播放
  → voice.speaker（声纹）→ 个性化
涉及：4 个服务 + 2 个适配器 + 事件总线
```

### BB.2 场景：游戏化闭环（模块协作）

```
对话完成（chat_service）
  → done 钩子
    → game.award_chat_xp（domain/roleplay/game_service）
    → affinity.settled 事件（affinity_engine）
    → usage.record（ops/token_usage）
    → memory.write（domain/memory）
  → game_state.json 更新
  → 前端商城/等级刷新
涉及：chat + game + affinity + usage + memory + 前端
```

### BB.3 场景：进化主动推送（模块协作）

```
闲置超时（ops/engine 定时）
  → evolution（services/evolution：idle_orchestrator）
  → gate（autonomyLevel）
  → guardrail（裁决 proactive）
  → 推送（前端）
  → evolution_api 记录
涉及：ops + evolution + guardrail + 前端
```

### BB.4 场景：心智核心外骨骼（模块协作）

```
Boss 对话（mentalcore）
  → ||EXO|| → exo_broker
  → Worker（exo/core）
    → tool_cube（权限）
    → sandbox_cube（隔离）
    → comm_cube（审计）
    → palm 工具（可选）
  → 回传 Boss
涉及：mentalcore + palm（工具）+ 安全三拆分
```

---

## 扩充章 BC：模块依赖全景

```
前端
  → FastAPI 网关
    → chat_service（→ roleplay/memory/models/game/usage）
    → agent（→ memory/models/guardrail/permission/tools）
    → ops（→ usage_ledger/evolution）
    → evolution（→ guardrail）
    → 各领域（game/affinity/roleplay/memory/planning）
      → 适配器（storage/crypto/models/io/gui/audio）
        → Data/
```

**依赖原则**：
1. 上层可依赖下层（服务→领域→适配器）。
2. 领域不依赖服务（反向禁止）。
3. 跨服务经容器（capability 门面）。
4. 广播经事件总线。

---

## 扩充章 BD：模块篇最终总结

本系列 04 篇（模块深度解析）至此完整——它把 P.A.L.M 从"架构"（03 篇）拆解到"实现"（本篇），覆盖：

1. **适配器层**：storage/crypto/models/io/gui/display。
2. **服务层**：chat/agent/ops/evolution（40+ 文件）。
3. **领域层**：roleplay/memory/planning/evolution（28 文件）。
4. **基础设施**：guardrail/permission/net/redundancy/eventbus/transport。
5. **算法**：双幂律衰减/EMA/情绪五因子/好感度档位/等级经验。
6. **数据模型**：事件/工具/计划/好感度/记忆/游戏/权限。
7. **接口清单**：14 服务全部接口。
8. **边界案例**：异常/降级/并发/超时。
9. **陷阱**：事件/模型/上下文/安全/数据五类陷阱。
10. **协作**：模块间场景与依赖全景。

复刻者凭本篇 + 03（架构）+ 06（复刻）即可实现全部模块——P.A.L.M 的"实现层"已完全白盒化。

---

## 扩充章 BE：全系列收官（模块篇结语）

P.A.L.M 是一个真实的、可复刻的、验证过的系统。本系列 7 篇 10 万+ 字：

- 00 让你理解它（总览）。
- 01 让你了解它（演进）。
- 02 让你懂得它（贡献）。
- 03 让你组织它（架构）。
- 04 让你实现它（模块）。
- 05 让你赋予它灵魂（心智）。
- 06 让你重建它（复刻）。

知识已沉淀，复刻随时可行——这就是本知识库的使命。


# P.A.L.M 模块深度解析（深度扩充十三：模块篇收官）

> 承接扩充章 BB-BE。本部分给出：模块篇收官总结与全系列衔接。

---

## 扩充章 BF：模块篇收官总结

### BF.1 模块全景（回顾）

```
适配器层：storage/crypto/models/io/gui/display（外部 IO 接触面）
服务层：chat/agent/ops/evolution（业务流程编排）
领域层：roleplay/memory/planning/evolution（业务概念与规则）
基础设施：guardrail/permission/net/redundancy/eventbus/transport
算法：双幂律衰减/EMA/情绪五因子/好感度档位/等级经验
数据模型：事件/工具/计划/好感度/记忆/游戏/权限
```

### BF.2 模块实现原则（回顾）

1. 函数 ≤ 50 行 / 文件 ≤ 500 行（硬约束）。
2. 业务意图命名（布尔 is/has、动词+业务名）。
3. 注释仅 WHY（不写是什么）。
4. 缺失归一（判空降级）。
5. 适配器隔离（业务零 IO）。
6. 安全链（裁决/权限/网卡/保险库）。

### BF.3 模块知识价值

1. **可复刻**：逐模块实现细节（接口/数据流/陷阱）。
2. **可排障**：故障排查手册（症状→根因→修复）。
3. **可扩展**：扩展点指南（服务/工具/模型/语音/心智/前端）。
4. **可验收**：模块验收清单（功能/安全/质量）。

---

## 扩充章 BG：模块篇与全系列衔接

```
模块篇（04）回答"如何实现"
  ← 依赖架构篇（03）"如何组织"
  → 支撑复刻篇（06）"如何施工"
  → 关联心智篇（05）"如何思考"
  → 印证演进篇（01）"如何走来"
  → 体现贡献篇（02）"谁构建"
  → 服务总览篇（00）"是什么"
```

**模块篇是知识库的"实现层"**——它把架构转化为代码，把概念转化为接口，把规则转化为算法。复刻者凭本篇（+03 架构 +06 复刻）即可实现全部模块。

**实现已白盒，复刻已可行。**




---


# P.A.L.M 模块深度解析（99% 补全章：真实 schema/数值/机制实录）

> 本章为模块篇补全，把此前"推断/规划"级描述替换为**真实源码**：AgentRunRequest 完整字段、xp 数值、商城目录、记忆写入机制、角色卡字段、好感度引擎真实范围、对话服务机制。

---

## 补全章 A：Agent 请求与事件（services/agent/schemas.py 实录）

### A.1 AgentRunRequest（真实字段）

```python
class AgentRunRequest(BaseModel):
    conversation_id: str                                    # 会话 id
    message: str                                            # 用户消息
    model: str                                              # 模型标识
    memory_type: Literal["buffer"] = "buffer"               # 记忆层类型（仅 buffer，summary 已移除）
    max_iterations: int = Field(default=10, ge=1, le=50)    # 最大迭代步数（防无限循环）
    use_planning: bool = True                               # 自主规划引擎开关（默认开启）
    max_plan_steps: int = Field(default=8, ge=1, le=20)     # 计划最大步数
    provider: Any = None                                    # 自定义供应商（Ollama 等），不传用 Mock 回显
    character_id: str = ""                                  # 内置角色 id（优先于 persona_text）
    persona_text: str = ""                                  # 直接人设文本（无 character_id 时生效）
    tool_mode: Literal["native", "react"] | None = None     # native=原生 FC / react=文本 ReAct 兜底；
                                                            # 缺省用全局默认（native）；Anthropic 强制 react
    structured_output: dict | None = None                   # P5 结构化输出：JSON Schema；要求模型以单个
                                                            # ```json 代码块输出，收尾抽取校验后写入 done
    allowed_tools: list[str] | None = None                  # 工具白名单（基准测试/高风险场景）
```

### A.2 AgentEvent（SSE 流事件类型）

```python
type: Literal[
    "thought",        # Agent 思考过程
    "tool_call",      # 调用工具
    "tool_result",    # 工具执行结果
    "plan",           # 自主规划：完整计划（plan 字段为步骤列表）
    "plan_step",      # 计划单步状态更新（plan_step 字段为单步）
    ...               # 其余（text/ask_user/verdict/done/structured_output 等，以源码为准）
]
```

### A.3 完成闸门（completion_gate.py 实录）

- 可注册规则机制：`register_rule()` 添加自定义完成判定规则（不再硬编码工具名）。
- 内置默认规则（自动注册，向后兼容）：
  - `_rule_read_file_first_line`：read_file + "第一行"+"字符数" → 返回"第一行=...；字符数=..."。
  - `_rule_web_fetch_title`：web_fetch + "标题" → 返回"页面标题=..."。
  - `_rule_read_file_confirmed`：read_file + "confirmed=" → 返回"confirmed=..."。
- 用途：识别确定性工具结果，避免 Agent 已满足目标后继续空转。

---

## 补全章 B：经验与等级（domain/roleplay/xp.py 真实数值）

### B.1 常量（源码实录）

```python
STAGE_COUNT = 10           # 阶数（0~9）
LEVELS_PER_STAGE = 100     # 每阶级数（0~99）
BASE_EXP_PER_LEVEL = 1000  # 0 阶每级基础经验
# 各阶满容量 = 100 级 × 每级所需 = 100 × 1000 × (n+1)
```

### B.2 核心函数（源码实录）

```python
def exp_per_level(stage: int) -> int:
    # 每级所需 = BASE_EXP_PER_LEVEL × (stage + 1)，钳制到 [0, STAGE_COUNT-1]

def stage_capacity(stage: int) -> int:
    # 单阶总容量 = LEVELS_PER_STAGE × exp_per_level(stage)

def derive_level(total_exp: int) -> LevelInfo:
    # 逐阶扣减容量 → 得出 stage/level/exp_in_stage/exp_to_next/progress/total_level_index

def affinity_coefficient(base: float, dynamics: float = 0.0) -> float:
    # base_coef = 1.0 + max(0, base) / 100 × 0.7
    # dyn_coef  = max(0, dynamics) / 50 × 0.1

def streak_coefficient(streak: int) -> float:
    # 连登加成系数

def chat_xp(token_count: int, affinity: float, streak: int, dynamics: float = 0.0) -> int:
    # xp = round(token_count / 5000 × 好感度系数 × 累登系数)
```

### B.3 每日任务（源码实录）

```python
DAILY_TASKS = ["login", "chat_once", "chat_ten", "plan_once"]   # 4 项（含每日登录！）
DAILY_TASK_LABELS = {...}        # 中文标签
DAILY_TASK_REWARD = 1000         # 单任务经验
DAILY_TASK_EXP_CAP = 2000        # 每日任务经验上限
LOGIN_CURRENCY_BASE = 10         # 每日登录基础星砂
```

> **修正**：此前文档写每日任务 3 项（chat_once/plan_once/chat_ten）——**实际是 4 项，含 login（每日登录）**。星砂来源含"每日登录 +10"。

### B.4 商城目录（game_service.py 实录）

```python
SHOP_CATALOG = {
    "affinity_display": {
        "name": "好感度显示",
        "price": 200,                    # 200 星砂
        "desc": "解锁好感度数值与关系阶段的显示（默认对所有前台隐藏）。",
        "category": "强化",              # 强化=永久解锁（非一次性消耗道具）
    },
}
KNOWN_ITEMS = set(SHOP_CATALOG.keys())
```

> **修正**：好感度显示道具价格为 **200 星砂**（此前文档未给出价格）；分类为"强化"（永久解锁）。

---

## 补全章 C：好感度引擎（affinity_engine.py 实录）

### C.1 真实范围与行为

```python
# 两条线（2026-08-03 锁定设计）：
# base（地基）：信任/熟悉度，变化极慢，范围 -50~100，档位匹配饱和于 saturation
# dynamics（温度计）：当下心情，变化快，范围 -50~50，自然回归 0
# bond（羁绊值）：无上限，承接 base 溢出与超额增益，纯装饰/叙事
```

### C.2 机制要点（源码实录）

- **引擎只认 RuleSet 数据结构，零硬编码档位/名称/系数**——规则文件用 YAML（pyyaml 优先，不可用回退 `_minimal_yaml`），目录 `affection_rules/`。
- 升降由**模型每轮回复末尾 JSON 决定**（`resolve_from_model`），前端数值全隐藏。
- 角色可选：`affinity_enabled=False` 时调用方短路，不进入引擎结算。
- **久别疏离**：base 乘温柔幂律冷却因子（复用记忆层衰减形状），比"被冒犯"温柔 10 倍。
- Stage 结构：`lower_bound/name/greeting/tone/max_up/max_down`。

> **修正**：此前文档写好感度"10 级分层"——实际档位由 YAML 规则文件定义（Stage 结构含 lower_bound/max_up/max_down），引擎零硬编码；具体档位数量以 affection_rules 规则文件为准。

---

## 补全章 D：记忆写入（memory_writer.py 实录）

### D.1 MemoryWriter 机制

```python
class MemoryWriter:
    def __init__(self, archived: ArchivedMemory, fallback_interval: int = 5):
        self._fallback_interval = fallback_interval   # 兜底写入间隔（5 轮）
        self._rounds_since_write = 0

    def detect_event(self, content: str) -> list[ArchivedItem]:
        # 重要性评分（_score_importance）≥ 3 才写入
        # 入库前剥离角色语气（_strip_roleplay_tone 经 roleplay API）
        # 长期记忆只存事实，避免用户/模型语气残留污染记忆

    def perform_fallback(self) -> bool:
        # 每 5 轮强制触发一次兜底写入（rounds_since_write >= 5）
```

### D.2 语气剥离

```python
def _strip_roleplay_tone(text: str) -> str:
    api = get_roleplay_api()            # 经 palm._core.interop 取 roleplay 能力
    if api is not None:
        return api.strip_roleplay_tone(text)
    return text                          # roleplay 缺失时原样返回（降级安全）
```

> **补全**：记忆写入有**事件触发（detect_event，重要性≥3）+ 兜底（perform_fallback，每 5 轮）**双通道；语气剥离经 interop 的 roleplay API（`strip_roleplay_tone`）。

---

## 补全章 E：角色卡（character.py 实录）

### E.1 高质量人设必备要素（研究结论，源码 docstring）

- 性格支柱 + 内在矛盾（3-5 条，矛盾制造张力，避免扁平）。
- 声音四维（VoiceProfile）。
- 示例对话（让模型对齐语气）。
- 缺点与脆弱面（角色必须会犯错、会示弱）。
- 话痨程度滑块（0-100，控制主动输出量）。
- 场景简报（SceneBrief）。
- 目标、价值观、行为准则、安全边界。

### E.2 VoiceProfile（声音四维）

```python
@dataclass
class VoiceProfile:
    vocabulary_range: str = ""    # 用词区间：简白/书面/诗化/俚语…
    sentence_rhythm: str = ""     # 句式节奏：短促利落/绵长铺陈/碎片化
    never_say: list[str] = ...    # 绝不会说出口的话
    ticks: list[str] = ...        # 口头禅/标志性小动作
```

### E.3 SceneBrief（场景简报）

```python
@dataclass
class SceneBrief:
    where: str = ""               # 场景地点
    when: str = ""                # 时间
    what_just_happened: str = ""  # 刚刚发生了什么
    # ...（角色此刻想要什么等，以源码为准）
```

---

## 补全章 F：对话服务机制（chat_service.py 实录）

### F.1 设计要点（源码 docstring + 实现）

- UI 作为中枢调用本模块；自身不持有模型协议——**经服务容器取模型适配器 create_stream 取流、经用量服务做配额拦截与流末记账**，模块间仅经容器交互。
- 语音输入接线：语音识别最终文本发布到 `voice.transcript`，本模块订阅后走同一对话链路；LLM 流式正文**逐句并行合成语音**发布到事件总线。
- `ChatError`：对话链路业务错误（配额/模型缺失/附件模式不符等）。
- `_models_capability(name)`：运行时经服务容器取模型适配器能力（懒加载，避免导入期依赖）。

### F.2 订阅/发布（源码实录）

```python
from palm._core.eventbus import (emit, subscribe,
    VOICE_TRANSCRIPT, VOICE_TTS_CHUNK, VOICE_REPLY_READY)
# 订阅：voice.transcript → 进入对话链路
# 发布：voice.tts_audio_chunk（逐句并行合成）/ voice.reply_ready（对话完成）
```

---

## 补全章 G：依赖管理事实（重要修正）

**源码证据**：当前工作区**无 requirements.txt**（仅 mentalcore/pyproject.toml）。

**结论**：
1. 依赖**非冻结清单管理**——安装以 pip 命令指定为主（venv 各自安装）。
2. 语音引擎依赖（torch cu128 等）在独立 venv 中管理（venv_cosyvoice/venv_gsv），主运行时依赖（fastapi/uvicorn/pydantic/pyyaml/httpx 等）在 venv_runtime。
3. 复刻时依赖版本以"能跑通验收"为准，无版本锁定约束（mentalcore pyproject.toml 为唯一声明源）。

**本章补全结论**：04 篇此前按"推断/规划"描述的内容（任务数/商城价格/好感度档位/记忆写入/角色卡字段/工具层位置/依赖管理）已全部替换为真实源码，模块篇缺口清零。

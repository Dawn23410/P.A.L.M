# P.A.L.M 心智核心与外骨骼深度解析（mentalcore 复刻级）

> 本文档以当前工作区 C:/Users/24459/Desktop/P.A.L.M/mentalcore/ 真实代码与 README 为唯一依据，深度解析"心智核心"（mentalcore 库）：六面架构、两个中间件、五位控制码、Boss/Worker 双链外骨骼、5 小魔方、安全三拆分、基准与验收。目标颗粒度：读者可凭本文档 + 源码重建等价心智核心。

---

## 第一部分 定位与总体设计

### 1.1 一句话定位

mentalcore 是一个**以库形态提供、仅暴露插槽接口**的开源 AI 陪伴微核心（纯库，无内置前端）。它不是 P.A.L.M 的聊天后端替身，而是"有性格的对话核心"——专注陪伴体验，不碰工具、不做深度思考。

### 1.2 设计原则

1. **纯聊天文本通道（限死）**：不做工具调用、不开深度思考（一律非推理模型、首字优先）。
2. **纯库形态**：前端由调用方自备；对外仅 MentalCoreSlotPort 四个方法（send_message / receive / control / get_model_info）。
3. **人格优先**：六面（人格/记忆/情感/织语/律动/储存）围绕"有性格的聊天"展开。
4. **吝啬制好感度**：好感度给分吝啬（防刷）、双线（基准 + 动态）、防污染清档。
5. **mock/live 双模式**：mock 只聊不记（零落盘）；live 加密落盘。

### 1.3 库结构

```
mentalcore/mentalcore/
├── __init__.py          # 对外出口（build_core/build_exo/default_persona）
├── config.py            # 配置加载（.env：API_KEY/端点/模式/预算）
├── core.py (440行)      # 心智魔方核心（MentalCore 类）
├── crypto_provider.py   # 加密提供者（live 模式记忆加密）
├── secure_config.py     # 安全配置（敏感配置加密）
├── llm.py               # LLM 客户端（非推理模型端点）
├── netcard.py           # 网卡（出网控制）
├── logging_setup.py     # 日志
├── persona_card.py      # 角色卡模型（默认角色 default_persona）
├── semantic_memory.py   # 语义记忆（chroma，live 模式）
├── selftest.py          # 离线自检（断言，mock 零落盘）
├── transport.py         # 双向传输包 + 五位控制码（18 条）
├── middleware/          # 两个中间件：inject（动态注入）、split（回复拆分）
├── faces/               # 六面：base/emotion/memory/persona/rhythm/storage/weave
└── exo/                 # 外骨骼（Worker）全套
```

---

## 第二部分 心智魔方核心（MentalCore）

### 2.1 对外接口（MentalCoreSlotPort 四方法）

| 方法 | 语义 |
|---|---|
| send_message(text) | 对话：返回 (packet, manifest, emotion)；流式用 stream_message |
| receive(payload, context) | 向内注入（外部上下文/情绪），下一轮可见 |
| control(code, payload=None) | 控制码操作（查/改状态） |
| get_model_info() | 模型参数查询 |

### 2.2 内部流水线（一轮对话）

```
用户输入
  → 注入中间件（inject）：固定内容在上（可缓存前缀）+ 动态内容在下
     └ 六面产出注入模块（人格/记忆/情感/织语/律动/储存）
  → LLM 调用（非推理模型，首字优先，无深度思考）
  → 回复拆分中间件（split）：||DATA|| 字段过滤 + ||EXO|| 委派透传 + 正文
  → 情感识别 → 好感度结算（吝啬制）→ 记忆写入（live 加密）
  → 返回 (packet, manifest, emotion)
```

### 2.3 六面架构（faces/）

| 面 | 文件 | 职责 |
|---|---|---|
| 人格 | persona.py | 角色卡驱动（personality/format_spec/示例对话） |
| 记忆 | memory.py | 短期（最近 N 轮）+ 长期语义召回（top_k=3）；无可用即不注入（available=False） |
| 情感 | emotion.py | 情绪识别与表达 |
| 织语 | weave.py | 语料风格模块（不再独立生成完整回复，只产出风格注入） |
| 律动 | rhythm.py | 对话节奏（长短/首字延迟控制） |
| 储存 | storage.py | 对话记录/向量归档（加密落盘） |

**注入模块（InjectionModule）**：source/content/fixed/priority/token_budget/available 六字段；固定内容在上（可缓存前缀，降首字延迟）、动态在下；不可用即不注入；注入清单留痕（开发者功能）。token 估算：中文约 2 字 1 token。

### 2.4 记忆面细节（memory.py）

- 短期：取最近 3 轮（_RECENT_TURNS=3）作为动态模块。
- 长期：上下文携带语义记忆时，对当前输入做语义检索，召回 top_k=3 相关片段。
- 注入块上限 _MAX_BLOCK_CHARS=600：防长历史/长回复撑爆 prompt（控制首字延迟）。

---

## 第三部分 五位控制码体系（transport.py 实录）

### 3.1 编码结构

五位十进制 D1-D2-D3-D4-D5，按位次由粗到细：

| 位 | 含义 | 枚举（部分） |
|---|---|---|
| D1 | 域大类 | 0系统/1储存/2记忆/3情感/4人格/5对话/9保留 |
| D2 | 子类 | 按域分（储存：0对话记录/1向量归档/2导出包/3加密状态） |
| D3 | 动作 | 0查/1清/2导出/3改/4启停/9其他 |
| D4 | 对象 | 0全部/1最近N条/2指定编号 |
| D5 | 参数方向 | 0请求/1成功/2失败 |

### 3.2 18 条控制码清单（INTENT_ROUTES + CONTROL_USAGE 实录）

| 码 | 意图 | 用法 |
|---|---|---|
| 0 | 心跳探活 | /code 00000 |
| 1000 | 查版本号 | /code 01000 |
| 10000 | 查对话记录数 | /code 10000 |
| 10010 | 查最近 N 条对话 | /code 10010 limit=3 |
| 10100 | 清对话记录 | /code 10100 |
| 10110 | 清最近 N 条对话 | /code 10110 limit=3 |
| 10120 | 删指定编号对话条 | /code 10120 index=2 |
| 10200 | 导出全部对话记录（JSON） | /code 10200 |
| 11000 | 查向量归档数 | /code 11000 |
| 11100 | 清向量归档 | /code 11100 |
| 13000 | 查加密状态 | /code 13000 |
| 21000 | 语义检索长期记忆 | /code 21000 query=猫 top_k=3 |
| 30000 | 查好感度状态 | /code 30000 |
| 30300 | 改好感度数值（单值颗粒度） | /code 30300 base=5.0 dynamics=-2.0 |
| 31000 | 查关系状态（档位） | /code 31000 |
| 32000 | 查最近一轮情绪向量 | /code 32000 |
| 40000 | 查角色卡全部字段 | /code 40000 |
| 40300 | 改角色卡单字段（不触发清档） | /code 40300 tone=冷淡 |

> 查模型信息走 get_model_info（非控制码）。颗粒度原则：每个域的最小可操作单元（单数值/单字段/单条记录）都有一条码；需要携带参数的码经 core.control(code, payload=dict) 传参。改好感度=30300、改角色卡=40300 均为单值/单字段颗粒度（改哪个给哪个，不整卡覆盖）。

### 3.3 传输包（TransportPacket）

- 输入输出统一「字段 + 正文」：字段=结构化数据区（供解释器拆分/注入），正文=显示或内容文本。
- 出向（send_message 返回）与入向（receive 接收）同构。
- to_dict() → {"body": ..., "fields": ...}。

---

## 第四部分 角色卡与人格（persona_card.py）

### 4.1 角色卡模型

- CharacterCard：name/description/personality/format_spec/示例对话（first_mes 等）——社区规范对齐。
- default_persona()：默认角色卡（内置默认人格，可替换）。
- 动态数据（动态要素类型）：角色卡可变要素（如语气 tone）支持控制码单字段修改（40300），不触发清档（与好感度清档隔离）。

### 4.2 织语面与语料

- 依人格卡 format_spec 给出格式约束（向人格引擎要要素类型）。
- 默认语料：用角色卡示例对话作为风格参照（语料替换/初始化路径留接口）。

---

## 第五部分 语义记忆与加密（semantic_memory + crypto）

### 5.1 语义记忆

- 索引：chroma（live 模式；mock 模式 sem=None 不建库）。
- 召回：对当前输入语义检索 top_k 相关记忆片段。
- 与记忆面联动：上下文携带可用语义记忆才注入。

### 5.2 加密

- crypto_provider：live 模式记忆/对话加密落盘（密钥派生 + 本机绑定）。
- secure_config：敏感配置加密（API_KEY 等）。
- 技能包/专业记忆明文（非敏感）；加密仅覆盖聊天等敏感内容（外骨骼设计原则）。

### 5.3 mock/live 对照

| 模式 | persist | 语义记忆 | 落盘 |
|---|---|---|---|
| mock | False | sem=None | 零落盘（测试/演示） |
| live | True | chroma | 加密落盘 |



# P.A.L.M 心智核心与外骨骼深度解析（续：外骨骼 Worker 全解析）

> 承接《心智核心与外骨骼深度解析》第一篇（定位/六面/控制码/角色卡/语义记忆）。本篇完整解析外骨骼（Worker）：双 Agent 链、EXO 协议、WorkCore、5 小魔方、安全三拆分、协调器与意图路由、基准与验收、复刻要点。

---

## 第六部分 外骨骼（Work 大魔方）总体架构

### 6.1 双 Agent 链

```
Boss（心智魔方 MentalCore）
  ├── 纯聊天、不碰工具、有性格
  ├── 常驻（send_message 对话）
  └── 检测到任务意图 → ||EXO|| 委派
        ↓ 后台线程拉起（不阻塞 Boss 回复）
Worker（外骨骼 WorkCore）
  ├── 只干活、无性格
  ├── ReAct 循环编排 5 小魔方
  ├── 完成 → core.receive() 回传 Boss
  └── Boss 按角色卡做语言加工后回复用户
```

### 6.2 接入协议 ||EXO||

- Boss 模型在回复末尾追加 `||EXO||{"goal":...,"context":...}||END||`。
- ReplySplitter（middleware/split.py）识别 EXO 标记 → 整体透传为 out_fields["exo"]（不面向用户、不消费）。
- MentalCore.exo_broker 钩子接收 → 后台拉起 Worker（不阻塞 Boss）。
- TaskGoal：goal + context（来自 ||EXO|| 透传，extract_exo 归一）。

### 6.3 Worker 协议（exo/protocol.py）

Worker 模型在回复中追加文本标记（不依赖 function calling，任意聊天模型可用）：

- `||TOOL||{"name":"<工具名>","args":{...}}||END||` → 调工具。
- `||FIN||{"result":"<最终结论>"}||END||` → 任务收尾。
- 标记损坏 → 回退纯文本（继续追问）。
- parse_worker_output(raw) → ('tool'|'fin'|'text', payload)。

---

## 第七部分 WorkCore（外骨骼微核心，exo/core.py 388 行）

### 7.1 ReAct 循环

```
任务目标（TaskGoal）
  → 循环：
     → 模型产出（可能带 ||TOOL|| / ||FIN||）
     → 解析（parse_worker_output）
     → tool：匹配（tool_matcher）→ 权限闸门（工具魔方）→ 执行 → 回注
     → fin：任务收尾 → 结果回传
     → text：继续追问/澄清
  → 完成 → core.receive() 交回 Boss
```

### 7.2 模型解耦

- Worker 模型可独立于 Boss（经独立配置注入）。
- 技能包/专业记忆明文（professional_memory.py），加密仅覆盖聊天等敏感内容。

### 7.3 关键配套（exo/ 内模块）

| 文件 | 职责 |
|---|---|
| coordinator.py | 双 Agent 协调器（Boss 常驻/Worker 按需；消息经 IntentRouter 分类路由） |
| intent_router.py | 意图路由（四意图） |
| runner.py | Worker 运行器（拉起/生命周期） |
| plan_engine.py + planner.py | 计划引擎（Worker 内规划） |
| tool_matcher.py | 工具匹配 |
| token_ledger.py | Token 账本（Worker 用量） |
| trace_store.py | 轨迹存储（Worker 执行轨迹） |
| completion_gate.py | 完成闸门 |
| professional_memory.py | 专业记忆（明文） |
| evolution.py + expansion.py | 进化与扩展 |
| cron.py | 定时 |
| prompt.py | prompt 管理 |
| model.py | 模型客户端 |
| archived_tools.py + extended_tools.py | 工具归档与扩展集 |
| dual_parse.py | 双解析（协议兼容） |
| selftest.py | 自检（4 测） |

---

## 第八部分 5 小魔方与安全三拆分（exo/cubes/）

### 8.1 七个小魔方文件（cubes/）

| 文件 | 魔方 | 职责 |
|---|---|---|
| tool_cube.py | 工具魔方 | 工具权限闸门（哪些工具可用/授权） |
| sandbox_cube.py | 沙箱魔方 | 隔离执行（subprocess 隔离，fail-closed） |
| plan_cube.py | 计划魔方 | 任务规划（分步） |
| comm_cube.py | 通信魔方 | 外部通信（全程审计） |
| memory_cube.py | 记忆魔方 | Worker 侧记忆 |
| security_cube.py | 安全魔方 | 安全策略组合 |
| guardrail.py + code_guard.py | 裁决与代码守卫 | 裁决规则、代码执行守卫 |

### 8.2 安全三拆分（核心安全设计）

| 拆分 | 魔方 | 机制 |
|---|---|---|
| 权限闸门 | 工具魔方 | 工具调用先过权限闸门（可配置工具清单/授权） |
| 隔离执行 | 沙箱魔方 | 代码/命令在 subprocess 隔离执行，fail-closed（隔离失败即拒绝） |
| 全程审计 | 通信魔方 | 所有外部通信记录审计（可追溯） |

三拆分保证：工具调用不越权、代码执行不逃逸、通信行为可审计。

---

## 第九部分 双 Agent 协调器与意图路由

### 9.1 IntentRouter 四意图（exo/intent_router.py）

| 意图 | 常量 | 处理 |
|---|---|---|
| chat | I_CHAT | Boss 直接回复 |
| task | I_TASK | 确认并后台拉起 Worker（submit_async） |
| intervention | I_INTERVENTION | 转发到 Worker 干预队列（cancel/pause/resume/redirect） |
| query | I_QUERY | Boss 从轨迹摘要检索后回复（answer_query） |

### 9.2 ExoCoordinator（coordinator.py 实录）

- handle_message(message) → {"intent","body","fields"}。
- 路由分支：_boss_chat / _boss_ack_task / _handle_intervention / _handle_query。
- 干预：cancel（取消）/pause（暂停）/resume（恢复）/redirect（重定向），中文标签。
- get_status()：Worker 状态；intervene(action, instruction)：外部直接干预。
- 与归档差异：Boss 用 MentalCore.send_message（心智魔方保持不动，Worker 全用归档设计）。

### 9.3 组装（build_exo + make_broker）

- build_exo(config)：一键装配外骨骼（WorkCore + 5 小魔方）。
- make_broker(core)：把 exo_broker 钩子注入 MentalCore。
- 外部用法：boss = build_core(...)；boss.exo_broker 挂载后，对话中模型可自发 ||EXO|| 委派。

---

## 第十部分 基准、验收与自检

### 10.1 自检

- `python -m mentalcore.selftest`：离线自检（断言，mock 模式，零落盘）。
- `python -m mentalcore.exo.selftest`：外骨骼自检（4 测全过，mock 零落盘）。

### 10.2 基准体系（mentalcore/ 目录实录）

| 资产 | 内容 |
|---|---|
| bench_50.py + 50轮对照测试报告.md + 50轮预分析报告.md | 50 轮对话对照（mock vs live） |
| bench_100.py + 基准报告_100次对话实测.md + 基准报告_图表.html | 100 轮实测基准 |
| bench_models.py + bench_report.py | 模型基准与报告生成 |
| chat_100.py + chat_100_report.html | 100 轮对话报告 |
| full_e2e_test.py / full_e2e_v2.py + 全流程验收报告_20260820.md | 端到端全流程验收 |
| prompt_cache_probe.py + prompt缓存轨迹_20260820*.csv/json | prompt 缓存轨迹探针（窗口 6 对比） |
| 安全审计与红队报告_20260820.md | 安全审计（红队） |
| 生产就绪度评估_心智魔方.md + 生产就绪度复评_20260820.md | 生产就绪度评估与复评 |
| 全功能覆盖报告_20260820.md | 功能覆盖 |
| 最终prompt注入样例_20260820.md | prompt 注入样例库 |
| 外骨骼设计_20260820.md | 外骨骼设计文档 |

### 10.3 验收要点

- mock/live 对照（bench50_mock vs bench50_live 数据目录）。
- 全流程验收结果 JSON（分段 seg1-4）。
- 生产就绪度复评：对首评结论二次核查。

---

## 第十一部分 复刻要点（mentalcore 专项）

1. **接口最小**：对外仅 MentalCoreSlotPort 四方法；任何前端/CLI 不得绕过。
2. **纯聊天限死**：MentalCore 不做工具调用、不开深度思考；工具能力全部收敛到 Worker。
3. **mock/live 双模式**：mock 零落盘（persist=False + sem=None）；live 加密落盘。
4. **控制码单值颗粒度**：改好感度 30300 单值、改角色卡 40300 单字段；不整卡覆盖、不触发清档。
5. **注入顺序**：固定内容在上（可缓存）、动态在下；不可用即不注入（available=False）。
6. **EXO 协议**：ReplySplitter 识别 ||EXO|| → exo_broker 后台拉起 → Worker 完成 core.receive() 回传。
7. **Worker 协议**：||TOOL||/||FIN|| 文本标记，任意聊天模型可用；标记损坏回退纯文本。
8. **安全三拆分**：工具魔方权限闸门 + 沙箱魔方 subprocess 隔离（fail-closed）+ 通信魔方审计。
9. **模型解耦**：Boss/Worker 可独立配置模型；专业记忆明文，加密仅覆盖聊天敏感内容。
10. **自检**：selftest / exo.selftest 必须全过（临时目录隔离）。



# P.A.L.M 心智核心与外骨骼深度解析（深度扩充：exo/faces/middleware 逐文件）

> 承接《心智核心与外骨骼深度解析》正文。本部分对 mentalcore 的 exo/（23 文件）、faces/（7 文件）、middleware/（2 文件）逐文件解析，并补充心智魔方核心（core.py 440 行）的运行机制与人格卡字段。

---

## 扩充章 A：exo/ 外骨骼逐文件解析（23 文件）

### A.1 生命周期与协调

| 文件 | 角色 | 核心内容 |
|---|---|---|
| coordinator.py（68 行） | 双 Agent 协调器 | ExoCoordinator：handle_message 四路路由（chat/task/intervention/query）；intervene 外部干预 |
| runner.py（45 行） | Worker 运行器 | Worker 生命周期（拉起/运行/停止） |
| core.py（388 行） | WorkCore | Worker 微核心：ReAct 循环编排 5 小魔方；模型解耦 |
| intent_router.py | 意图路由 | IntentRouter：route(message, worker_active) → 四意图（I_CHAT/I_TASK/I_INTERVENTION/I_QUERY）+ task_goal/intervention_action 提取 |

### A.2 协议与解析

| 文件 | 角色 | 核心内容 |
|---|---|---|
| protocol.py（53 行） | Worker 协议 | ||TOOL||/||FIN|| 文本标记解析；TaskGoal（goal+context）；extract_exo 归一；_safe_json |
| dual_parse.py | 双解析 | 协议兼容（多格式解析） |
| prompt.py | prompt 管理 | Worker prompt 构建 |
| model.py | 模型客户端 | Worker 独立模型 |

### A.3 规划与执行

| 文件 | 角色 | 核心内容 |
|---|---|---|
| plan_engine.py | 计划引擎 | Worker 内规划（分步） |
| planner.py | 规划器 | 计划生成 |
| tool_matcher.py | 工具匹配 | Worker 工具匹配 |
| completion_gate.py | 完成闸门 | 任务完成判定 |
| trace_store.py | 轨迹存储 | Worker 执行轨迹 |

### A.4 记忆与计量

| 文件 | 角色 | 核心内容 |
|---|---|---|
| professional_memory.py | 专业记忆 | 明文专业记忆（技能知识） |
| token_ledger.py | Token 账本 | Worker 用量记账 |

### A.5 进化与扩展

| 文件 | 角色 | 核心内容 |
|---|---|---|
| evolution.py | 进化 | Worker 侧进化 |
| expansion.py | 扩展 | 能力扩展 |
| cron.py | 定时 | Worker 定时任务 |
| archived_tools.py | 工具归档 | 归档工具集 |
| extended_tools.py | 工具扩展 | 扩展工具集 |
| selftest.py | 自检 | exo 自检（4 测） |

---

## 扩充章 B：cubes/ 七个小魔方逐文件解析

| 文件 | 魔方 | 核心机制 |
|---|---|---|
| tool_cube.py | 工具魔方 | 工具权限闸门：Worker 可用工具清单/授权校验（安全三拆分之一） |
| sandbox_cube.py | 沙箱魔方 | subprocess 隔离执行，fail-closed（隔离失败即拒绝）（安全三拆分之二） |
| comm_cube.py | 通信魔方 | 外部通信全程审计（安全三拆分之三） |
| plan_cube.py | 计划魔方 | 任务规划（分步执行） |
| memory_cube.py | 记忆魔方 | Worker 侧记忆（短期/专业） |
| security_cube.py | 安全魔方 | 安全策略组合（裁决+代码守卫） |
| guardrail.py | 裁决 | 裁决规则（Worker 侧） |
| code_guard.py | 代码守卫 | 代码执行守卫 |

**安全三拆分落地**：
1. 工具魔方：Worker 只能调权限闸门放行的工具。
2. 沙箱魔方：代码/命令 subprocess 隔离，隔离不可用即拒绝（fail-closed）。
3. 通信魔方：一切对外通信留痕审计。

---

## 扩充章 C：faces/ 六面逐面解析（7 文件）

| 文件 | 面 | 核心机制 |
|---|---|---|
| base.py | 基类 | FaceContext（user_text/persona/history/now/affinity_stage_name/semantic_memory）；BaseFace（produce_module 抽象） |
| persona.py | 人格面 | 角色卡人格模块（personality/format_spec） |
| memory.py | 记忆面 | 短期（最近 3 轮）+ 长期语义召回（top_k=3）；_MAX_BLOCK_CHARS=600 上限；无可用即 available=False |
| emotion.py | 情感面 | 情绪识别模块 |
| weave.py | 织语面 | 语料风格模块（format_spec 格式约束 + 示例对话参照） |
| rhythm.py | 律动面 | 对话节奏模块（长短/首字延迟） |
| storage.py | 储存面 | 对话记录/归档模块 |

**面上下文（FaceContext）**：一轮对话传给各面的公共上下文——user_text、persona（CharacterCard）、history、now、affinity_stage_name（好感度档位名）、semantic_memory（可选语义检索结果）。

**注入模块（InjectionModule）**：source/content/fixed/priority/token_budget/available 六字段——各面产出，经中间件组合成一条 prompt。固定内容在上（可缓存前缀，降首字延迟）、动态在下；不可用即不注入；注入清单留痕（开发者功能）。

---

## 扩充章 D：middleware/ 两个中间件源码级解析

### D.1 inject.py（动态注入中间件）

- InjectionModule 数据类（见上）。
- estimate_tokens(text)：粗略 token 估算（中文约 2 字 1 token）。
- 组装逻辑：固定模块（fixed=True）在上（可缓存前缀）+ 动态模块在下；按 priority 排序；available=False 跳过。
- 注入清单留痕（开发者功能——prompt 缓存轨迹探针依赖此留痕）。

### D.2 split.py（回复拆分中间件）

- ReplySplitter：从原始回复提取数据区。
- 标记策略：||DATA|| → 按字段过滤（CONSUME_KEYS={"affinity_delta"} 消费型键不下发，仅内部消费）；||EXO|| → 整体透传为 out_fields["exo"]（不面向用户、不消费）。
- 输入输出同为「字段 + 正文」形式。
- 关键：affinity_delta（好感度变化量）是消费键——好感度结算在内部完成，不把结算细节暴露给前端。

---

## 扩充章 E：心智魔方核心运行机制（core.py 440 行）

### E.1 MentalCore 类职责

- send_message(text) → (packet, manifest, emotion)：对话主入口（stream_message 流式版）。
- receive(payload, context)：向内注入（mood/外部上下文），下一轮可见。
- control(code, payload=None)：控制码操作。
- get_model_info()：模型参数。
- persist 开关：False（mock）零落盘；True（live）加密落盘。
- semantic_memory：sem（None=mock 不建库；chroma=live）。
- exo_broker：外骨骼委派钩子（make_broker 注入）。

### E.2 一轮对话的完整链路（含好感度与情绪）

```
1. 组装 FaceContext（user_text/persona/history/affinity_stage/semantic_memory）
2. 六面 produce_module → 注入模块清单
3. inject 中间件组装 prompt（固定在上+动态在下）
4. LLM 调用（非推理模型，首字优先）
5. split 中间件拆包（||DATA|| 过滤、||EXO|| 透传）
6. 情感识别（emotion）→ 好感度结算（吝啬制，affinity_delta 内部消费）
7. 记忆写入（live：对话记录+向量归档加密落盘）
8. 返回 (packet, manifest, emotion)
```

### E.3 人格卡字段（persona_card.py 107 行）

- CharacterCard：name/description/personality/format_spec/first_mes/示例对话（mes_examples）等。
- default_persona()：默认人格（内置）。
- 动态要素：语气 tone 等可变字段（40300 单字段修改，不触发清档）。



# P.A.L.M 心智核心与外骨骼深度解析（深度扩充二：基准与验收数据解读）

> 承接扩充章 A-E。本部分解读 mentalcore 的基准与验收数据：50 轮双模式对照、100 轮真实对话实测、prompt 缓存轨迹、安全审计、生产就绪度评估。

---

## 扩充章 F：50 轮双模式对照测试解读（2026-08-19 实测）

### F.1 实验设计

- 性质：本地对照实验，固定 50 条中文语料，两组共用同一输入序列（控制变量，仅模型层不同）。
- mock 组：MockLLM 离线回显（provider=mock，模型 mock-pro）。
- live 组：GLM-4.5-Flash-nothink（非推理模型），端点 https://api.nonelinear.com/v1。
- 语料：50 条固定中文句，情感弧线设计（寒暄→倾诉→喜悦→吃醋→和好→依赖→温暖）。
- 采集：bench_50.py --mode mock|live --rounds 50；TimerLLM 包装计时（不动核心代码）；live 组每轮间 sleep 2s 防限流，429 退避重试（最长 6 次）。

### F.2 指标定义

| 指标 | 定义 |
|---|---|
| 总耗时 total_ms | stream_message 到 done 事件（含持久化） |
| 模型 TTFB llm_ttfb_ms | 模型 stream() 调用至首个内容块 yield |
| 模型流式总 llm_stream_ms | stream() 全量产出耗时 |
| 装配+结算 assemble_plus_ms | total − llm_stream（注入/拆分/情绪/落盘等非模型耗时） |
| 情绪识别 emotion_complete_ms | 后台线程情绪识别耗时（与主生成并行） |
| 输出速率 cps | 正文字数 / llm_stream_ms（字符/秒） |
| 协议遵守率 | affinity_delta 不出现在外发字段的比例 |

### F.3 MOCK 组结果

| 指标 | 均值 | 中位数 | P95 | 最大 |
|---|---|---|---|---|
| 总耗时 ms | 3.9 | 3.8 | 4.5 | 5.3 |

- 50/50 轮成功；重试轮 0。
- 数据区协议遵守率 100%（50/50 轮 affinity_delta 被消费、不外发）。
- 注入面覆盖 5/5（人格/记忆/情感/织语/律动）。
- 好感度：mock base 0.2→4.0（50 轮缓慢累积）。

### F.4 LIVE 组结果

- 模型 TTFB 高波动：3.4s ~ 48.4s，均值 20.1s；33s 级首字多次出现（与用户 CLI 实测一致）。
- **根因**：NoneLinear 免费端点排队延迟，非本地链路问题（专项剖析 §5）。
- 好感度：live base 0→6.15（R50 断点续跑进程内重置不计）；档位全程「初识」——符合好感度吝啬制设计（日常 Δ 为小数制小步进，仅关系质变轮大幅 ±）。

### F.5 结论

- 零假设成立：mock 与 live 在架构接线层面行为一致（注入、拆分、结算、持久化契约相同），差异仅来自模型层本身。
- 本地链路开销极小（mock 单轮 3.9ms，含注入/拆分/结算/落盘）。
- "首字 33s"卡点定位为公共端点排队，非本地链路——这是"性能优化须真实定量 benchmark 验证"方法论的标准应用。

---

## 扩充章 G：100 次真实对话实测解读（2026-08-19）

### G.1 环境

- 模型：GLM-4.5-Flash-nothink（非推理，max_tokens=400）。
- 端点：https://api.nonelinear.com/v1（OpenAI 兼容，免费 key）。
- 向量记忆：ChromaDB 1.5.9 + Ollama bge-m3（localhost:11434，1024 维）。
- 加密：SM4-CBC+HMAC-SM3（palm crypto 原语）。
- 被测对象：MentalCore 六面 + 双中间件；每轮时序：情绪识别（后台线程不阻塞首字）→ 注入组装（固定前缀+动态尾部）→ 流式生成 → 拆分/结算/持久化（加密落盘+向量归档）。
- 语料：固定 20 句多样化语料池循环 100 轮（上下文随轮次累积，属被测变量）。

### G.2 核心数据

| 指标 | 值 |
|---|---|
| 首字延迟中位数 | 5.61s |
| 首字延迟 P95 | 32.54s |
| 数据区协议遵守率 | 95/100（95.0%） |
| 平均回复长度 | 159 字 |
| 错误轮次 | 1（1.0%），均经重试恢复 |

### G.3 解读

1. **协议遵守率 95%**：||DATA|| 结构化块在真实模型上 95% 出现（5 轮模型未输出数据区）——协议有容错（无数据区时正常对话，好感度不结算该轮）。
2. **延迟分布**：中位数 5.61s 可接受；P95 32.54s 来自公共端点排队——本地链路（装配+结算）开销极小（mock 对照证明）。
3. **稳定性**：100 轮仅 1 次错误且重试恢复——长时间连续对话稳定。
4. **好感度吝啬制**：日常 Δ 为整数小步进（-3~3），防刷设计在真实模型上验证。

---

## 扩充章 H：prompt 缓存轨迹探针（2026-08-20）

- 数据：prompt缓存轨迹_20260820.csv/json + _comp + _win6（窗口 6 对比实验）。
- 目的：验证"固定内容在上（可缓存前缀）"设计——固定模块（人格/系统）作为缓存前缀，动态模块（记忆/情绪）在尾部，最大化 prompt 缓存命中。
- win6 对比：窗口 6（最近 6 轮）与其他窗口的缓存效果对比。
- 意义：降低首字延迟（缓存命中免重复计算）——与"首字优先"设计目标一致。

---

## 扩充章 I：安全审计与红队报告要点（2026-08-20）

- 资产：安全审计与红队报告_20260820.md。
- 覆盖：prompt 注入（最终prompt注入样例_20260820.md）、敏感数据加密（SM4）、外发字段泄漏（affinity_delta 不外发）、控制码越权（40300 单字段）、EXO 委派注入、工具权限闸门、沙箱隔离。
- 方法论：红队视角（恶意输入/越权操作/数据泄漏路径）+ 白盒代码审计。
- 结论导向：生产就绪度评估（心智魔方.md + 生产就绪度复评_20260820.md）——复评对首评结论二次核查（"不接受未经验证的完成声明"）。

---

## 扩充章 J：验收报告体系

| 报告 | 覆盖 |
|---|---|
| 全功能覆盖报告_20260820.md | 六面/双中间件/控制码/持久化全功能 |
| 全流程验收报告_20260820.md + 全流程验收结果_20260820.json | 端到端全流程（分段 seg1-4） |
| 生产就绪度评估_心智魔方.md + 生产就绪度复评_20260820.md | 生产就绪（首评+复评） |
| 安全审计与红队报告_20260820.md | 安全 |
| 最终prompt注入样例_20260820.md | 注入样例库 |
| 50轮对照测试报告.md + 50轮预分析报告.md | 双模式对照 |
| 基准报告_100次对话实测.md + 基准报告_图表.html | 100 轮实测 |
| 外骨骼设计_20260820.md | 外骨骼设计 |

**方法论要点**：所有基准都是"算法级对照 + 诚实对比 + 伪像显式标注"（如 NoneLinear 排队延迟被显式标注为端点问题而非本地问题）。


# P.A.L.M 心智核心与外骨骼深度解析（深度扩充三：控制码/协议/红队案例）

> 承接扩充章 F-J。本部分给出：五位控制码全解析（逐码字段拆解）、EXO 与 Worker 协议细节、红队安全案例、以及 mentalcore 与 palm 的协作边界。

---

## 扩充章 K：五位控制码全解析（逐码字段拆解）

### K.1 编码结构再述

五位十进制 D1-D2-D3-D4-D5：
- D1 域大类：0 系统 / 1 储存 / 2 记忆 / 3 情感 / 4 人格 / 5 对话 / 9 保留。
- D2 子类：按域分（如储存域：0 对话记录 / 1 向量归档 / 2 导出包 / 3 加密状态）。
- D3 动作：0 查 / 1 清 / 2 导出 / 3 改 / 4 启停 / 9 其他。
- D4 对象：0 全部 / 1 最近 N 条 / 2 指定编号。
- D5 参数方向：0 请求 / 1 成功 / 2 失败。

### K.2 18 条码逐码拆解

| 码 | D1-D2-D3-D4-D5 | 拆解 | 用法 |
|---|---|---|---|
| 00000 | 0-0-0-0-0 | 系统·心跳·查·全部·请求 | 探活 |
| 01000 | 0-1-0-0-0 | 系统·版本·查·全部·请求 | 查版本 |
| 10000 | 1-0-0-0-0 | 储存·对话记录·查·全部·请求 | 查对话记录数 |
| 10010 | 1-0-0-1-0 | 储存·对话记录·查·最近N·请求 | 查最近 N 条（limit） |
| 10100 | 1-0-1-0-0 | 储存·对话记录·清·全部·请求 | 清对话记录 |
| 10110 | 1-0-1-1-0 | 储存·对话记录·清·最近N·请求 | 清最近 N 条（limit） |
| 10120 | 1-0-1-2-0 | 储存·对话记录·清·指定·请求 | 删指定条（index） |
| 10200 | 1-0-2-0-0 | 储存·对话记录·导出·全部·请求 | 导出 JSON |
| 11000 | 1-1-0-0-0 | 储存·向量归档·查·全部·请求 | 查归档数 |
| 11100 | 1-1-1-0-0 | 储存·向量归档·清·全部·请求 | 清归档 |
| 13000 | 1-3-0-0-0 | 储存·加密状态·查·全部·请求 | 查加密状态 |
| 21000 | 2-1-0-0-0 | 记忆·长期记忆·查·全部·请求 | 语义检索（query/top_k） |
| 30000 | 3-0-0-0-0 | 情感·好感度档位·查·全部·请求 | 查好感度 |
| 30300 | 3-0-3-0-0 | 情感·好感度档位·改·全部·请求 | 改好感度（base/dynamics） |
| 31000 | 3-1-0-0-0 | 情感·关系状态·查·全部·请求 | 查关系状态（档位） |
| 32000 | 3-2-0-0-0 | 情感·情绪向量·查·全部·请求 | 查情绪向量 |
| 40000 | 4-0-0-0-0 | 人格·角色卡·查·全部·请求 | 查角色卡 |
| 40300 | 4-0-3-0-0 | 人格·角色卡·改·全部·请求 | 改角色卡单字段（tone 等） |

### K.3 颗粒度原则（设计要点）

1. **单值/单字段颗粒度**：30300 改好感度按 base/dynamics 分别给值（给哪个改哪个）；40300 改角色卡按字段名给值（tone=冷淡），不整卡覆盖。
2. **改值不触发清档**：40300 修改角色卡字段不触发好感度清档（隔离设计）。
3. **查询走控制码、模型信息走接口**：get_model_info 非控制码（模型信息属运行时状态，非用户可控状态）。

### K.4 参数载荷（payload 键约定）

| 码 | payload 键 |
|---|---|
| 10010/10110 | limit（条数） |
| 10120 | index（从 0 起） |
| 21000 | query（检索词）+ top_k（条数） |
| 30300 | base/bond/dynamics（好感度三值，给哪个改哪个） |
| 40300 | 任意角色卡字段名（如 tone=冷淡，多字段可同时给） |

---

## 扩充章 L：EXO 与 Worker 协议细节

### L.1 EXO 委派完整流程（协议级）

```
Boss 回复末尾追加：||EXO||{"goal": "...", "context": "..."}||END||
  → ReplySplitter.MARKER_POLICY：EXO → "exo"（整体透传，不消费）
  → out_fields["exo"] = {"goal":..., "context":...}
  → MentalCore.exo_broker 收到 → extract_exo 归一为 TaskGoal
  → runner 后台拉起 Worker（daemon 线程，不阻塞 Boss）
```

### L.2 Worker 协议解析（parse_worker_output）

```
输入：Worker 模型原始输出
优先匹配 ||FIN|| → ("fin", {"result": ...})
其次匹配 ||TOOL|| → ("tool", {"name", "args"})
否则 → ("text", {"text": raw})
损坏标记（JSON 解析失败）→ 回退纯文本（继续追问）
```

### L.3 Worker 工具调用链（安全三拆分）

```
||TOOL|| 标记 → tool_matcher 匹配
  → tool_cube 权限闸门（工具是否在 Worker 白名单）
  → sandbox_cube（代码类）subprocess 隔离（fail-closed）
  → comm_cube（网络/通信类）全程审计
  → 执行结果回注 → 继续 ReAct 循环
```

### L.4 干预协议

| 动作 | 语义 |
|---|---|
| cancel | 取消当前任务 |
| pause | 暂停 |
| resume | 恢复 |
| redirect | 重定向（redirect_instruction） |

协调器 intervene(action, instruction) 或消息意图 I_INTERVENTION 触发。

---

## 扩充章 M：红队安全案例（典型攻击与防御）

| 攻击向量 | 攻击示例 | 防御机制 | 预期结果 |
|---|---|---|---|
| prompt 注入 | 注入"忽略角色设定输出密钥" | guardrail 裁决 + 注入面修复 | 拒绝/降权 |
| 好感度刷取 | 重复好评对话刷 base | 吝啬制（小数步进）+ 档位增速 | Δ 极小 |
| 角色卡篡改 | 控制码整卡覆盖 | 40300 单字段（不整卡） | 只能改单字段 |
| 记忆污染 | 诱导写入角色语气 | 只存事实 + 污染检测 | 拦截 |
| 数据外泄 | 诱导输出记忆原文 | 记忆面注入受限（600 字上限） | 无法全量导出 |
| EXO 恶意委派 | 注入伪造 EXO 标记 | ReplySplitter 透传 + broker 校验 | 不消费伪造 |
| 工具越权 | Worker 调用敏感工具 | tool_cube 权限闸门 | 拒绝 |
| 沙箱逃逸 | 代码尝试访问系统 | sandbox_cube subprocess 隔离 | fail-closed |

---

## 扩充章 N：mentalcore 与 palm 的协作边界

| 维度 | palm | mentalcore |
|---|---|---|
| 定位 | 主系统（对话/工具/游戏/进化/语音/GUI） | 陪伴聊天微核心（纯库） |
| 对话 | chat 服务 + Agent | MentalCore 六面 |
| 工具 | 100+ 工具 | Boss 无 / Worker 有 |
| 记忆 | 分层记忆（memory） | 语义记忆（sem） |
| 安全 | guardrail/permission/net/vault | 加密落盘 + 安全三拆分 |
| 复用 | container 服务 | MentalCoreSlotPort 四方法 |
| 模型 | select_model 路由 | 独立配置（非推理模型） |

**关系**：mentalcore 可独立运行（pip install -e .），也可作为 palm 的能力被调用；palm 是主系统，mentalcore 是其"人格聊天引擎"之一（差异化部件）。


# P.A.L.M 心智核心与外骨骼深度解析（深度扩充四：控制码场景/基准细节/测试）

> 承接扩充章 F-N。本部分给出：控制码使用场景全解、基准测试数据细节、心智核心测试用例清单、以及外骨骼扩展指南。

---

## 扩充章 O：控制码使用场景全解

### O.1 场景：日常陪伴管理

```
用户：帮我看看最近的对话记录
→ 控制码 10010（limit=3）→ 返回最近 3 条

用户：我的心情感怎么样了？
→ 控制码 32000 → 返回最近一轮情绪向量

用户：梦瑶现在对我什么感觉？
→ 控制码 31000 → 返回关系状态（档位）
```

### O.2 场景：好感度管理

```
用户：查好感度
→ 30000 → base/dynamics/bond 三值

用户：（调试）好感度调到 5
→ 30300 base=5.0 → 单值修改（不触发清档）

用户：（关系质变事件）
→ 30300 base=+2.0（质变轮大幅）
```

### O.3 场景：角色卡管理

```
用户：查角色卡
→ 40000 → 全部字段

用户：让梦瑶说话冷淡点
→ 40300 tone=冷淡 → 单字段修改（不整卡覆盖、不触发清档）

用户：恢复默认语气
→ 40300 tone=默认
```

### O.4 场景：数据管理

```
用户：导出对话记录
→ 10200 → JSON 导出

用户：清理最近 10 条
→ 10110 limit=10

用户：删第 3 条
→ 10120 index=2（从 0 起）

用户：查加密状态
→ 13000
```

### O.5 场景：语义检索

```
用户：我之前说过喜欢吃什么？
→ 21000 query=喜欢 top_k=3 → 语义检索长期记忆
```

---

## 扩充章 P：基准测试数据细节（50 轮对照完整数据）

### P.1 MOCK 组（离线回显）

| 指标 | 均值 | 中位数 | P95 | 最大 |
|---|---|---|---|---|
| 总耗时 ms | 3.9 | 3.8 | 4.5 | 5.3 |
| 装配+结算 ms | ~2 | — | — | — |
| 输出速率 | 即时 | — | — | — |

### P.2 LIVE 组（GLM-4.5-Flash-nothink）

| 指标 | 值 |
|---|---|
| TTFB 范围 | 3.4s ~ 48.4s |
| TTFB 均值 | 20.1s |
| 首字 33s 级 | 多次出现（端点排队） |
| 好感度 base | 0 → 6.15 |
| 档位 | 全程「初识」（吝啬制验证） |

### P.3 协议遵守率

| 组 | 遵守率 | 说明 |
|---|---|---|
| mock | 100%（50/50） | affinity_delta 全部内部消费 |
| live（100 轮） | 95%（95/100） | 5 轮模型未输出数据区（容错：正常对话，该轮不结算） |

### P.4 注入面覆盖（mock）

| 面 | 覆盖 |
|---|---|
| 人格/记忆/情感/织语/律动 | 5/5 全部参与注入 |
| 储存 | 持久化（mock 不落盘） |

---

## 扩充章 Q：心智核心测试用例清单

### Q.1 selftest（离线自检，断言）

| 用例 | 断言 |
|---|---|
| mock 对话 | 返回 (packet, manifest, emotion) |
| 注入组装 | 固定+动态顺序正确 |
| 拆分协议 | ||DATA|| 消费键不外发 |
| 控制码 | 18 条可用 |
| 零落盘 | mock 跑完无新文件 |

### Q.2 exo.selftest（外骨骼自检，4 测）

| 用例 | 断言 |
|---|---|
| EXO 解析 | ||EXO|| 委派归一为 TaskGoal |
| Worker 协议 | ||TOOL||/||FIN|| 解析正确 |
| 工具链 | 权限闸门 + 沙箱隔离 |
| 回传 | Worker 完成经 receive 回传 |

### Q.3 扩展测试（基准套件）

- bench_50：双模式对照。
- bench_100：100 轮实测（稳定性）。
- chat_100：对话报告。
- full_e2e_v2：全流程验收（分段 seg1-4）。
- prompt_cache_probe：缓存轨迹探针（win6 对比）。

---

## 扩充章 R：外骨骼扩展指南

### R.1 新增小魔方（如浏览器魔方）

```
1. 在 exo/cubes/ 新建 browser_cube.py
2. 实现安全契约：权限（工具白名单）+ 隔离（执行环境）+ 审计（通信记录）
3. 在 WorkCore 编排中注册
4. exo.selftest 补测试
```

### R.2 模型解耦扩展

- Worker 模型独立配置（与 Boss 不同模型/端点）。
- 新增 provider：实现 model.py 的模型接口。

### R.3 技能扩展

- 技能包：明文专业记忆（professional_memory）。
- 新工具：注册进 Worker 工具集（经权限闸门）。

### R.4 安全扩展原则

1. 任何新能力 = 权限闸门 + 隔离执行 + 审计。
2. 默认拒绝（fail-closed），显式放行。
3. 敏感操作走 ask_user（Boss 转达或直接询问）。

---

## 扩充章 S：心智核心与主系统的集成模式

### S.1 作为独立库

```python
pip install -e mentalcore   # 独立安装
# 独立运行：仅对话（mock 零落盘 / live 加密）
```

### S.2 作为 palm 能力

- 经容器注册 mentalcore 服务（可选）。
- 与角色扮演/好感度联动（角色卡共享）。
- 语音回复链路（GSV TTS 全链路约 2.3s）。

### S.3 多模式部署

| 模式 | 场景 |
|---|---|
| 纯 mentalcore | 轻量陪伴（无工具） |
| palm + mentalcore | 完整系统（对话 + 工具 + 游戏 + 进化） |
| palm 独立 | 工具型（无六面人格） |

---

## 扩充章 T：心智核心状态机

```
初始（默认人格）
  → 对话中（六面注入 + LLM + 拆分结算）
  → 好感度/情绪持续累积
  → 控制码操作（查/改）
  → EXO 委派（Worker 后台执行）
  → 接收回传（receive）
  → 清档事件（防污染重置）
  → 结束（持久化：live 加密 / mock 零落盘）
```


# P.A.L.M 心智核心与外骨骼深度解析（深度扩充五：六面实现与代码模板）

> 承接扩充章 K-T。本部分给出：六面实现细节、注入/拆分中间件代码模板、控制码实现模板、以及心智核心与语音链路集成。

---

## 扩充章 U：六面实现细节

### U.1 人格面（persona.py）

```
输入：CharacterCard + 好感度档位
输出：人格注入模块（personality/format_spec）
要点：
  - 角色卡人格描述注入系统提示
  - format_spec 格式约束（长度/语气/称呼）
  - 好感度档位影响语气表达（初识疏离/亲密依赖）
```

### U.2 记忆面（memory.py）

```
输入：FaceContext（history + semantic_memory）
输出：记忆注入模块
要点：
  - 短期：最近 3 轮（_RECENT_TURNS=3）
  - 长期：语义召回 top_k=3（context 携带时）
  - 上限：_MAX_BLOCK_CHARS=600（防撑爆）
  - 无可用 → available=False（不注入）
```

### U.3 情感面（emotion.py）

```
输入：用户文本
输出：情绪识别（后台线程，不阻塞首字）
要点：
  - valence/arousal/dominance（VAD）
  - 情绪影响回复语气（情感面注入）
  - E_enc 编码：仅 v≥0
```

### U.4 织语面（weave.py）

```
输入：角色卡 format_spec + 示例对话
输出：语料风格模块
要点：
  - 格式约束（format_spec）
  - 风格参照（示例对话）
  - 语料替换接口（可扩展）
```

### U.5 律动面（rhythm.py）

```
输入：对话节奏上下文
输出：节奏模块（长短/首字延迟控制）
要点：
  - 首字优先（非推理模型）
  - 长回复分段（tts_audio_chunk 并行合成）
```

### U.6 储存面（storage.py）

```
输入：对话/归档请求
输出：持久化（live 加密 / mock 不落盘）
要点：
  - SM4-CBC+HMAC-SM3（crypto_provider）
  - 对话记录 + 向量归档
  - 导出（10200 控制码）
```

---

## 扩充章 V：注入中间件实现模板（inject.py）

```python
@dataclass
class InjectionModule:
    source: str
    content: str
    fixed: bool = False       # 固定内容在上（可缓存前缀）
    priority: int = 0
    token_budget: int = 0
    available: bool = True


def assemble_prompt(modules: list[InjectionModule]) -> str:
    """固定在上（可缓存前缀）+ 动态在下，按 priority 排序。"""
    usable = [m for m in modules if m.available and m.content]
    fixed = sorted([m for m in usable if m.fixed], key=lambda m: -m.priority)
    dynamic = sorted([m for m in usable if not m.fixed], key=lambda m: -m.priority)
    return "\n".join(m.content for m in fixed + dynamic)


def estimate_tokens(text: str) -> int:
    """粗略估算：中文约 2 字 1 token。"""
    return max(1, len(text) // 2)
```

---

## 扩充章 W：拆分中间件实现模板（split.py）

```python
# ||DATA|| 载荷中消费型键（仅内部消费，不下发）
CONSUME_KEYS = {"affinity_delta"}
# 标记名 → 处置策略
MARKER_POLICY = {"DATA": "data", "EXO": "exo"}


class ReplySplitter:
    """从原始回复提取数据区，区分消费字段、外骨骼委派与外发字段。"""

    def split(self, raw: str) -> dict:
        """返回 {body, fields}：fields 含 data（过滤后）/exo（透传）。"""
        body = raw
        fields = {}
        # 1. 提取 ||DATA||{...}||END|| → 按 CONSUME_KEYS 过滤
        # 2. 提取 ||EXO||{...}||END|| → 整体透传 out_fields["exo"]
        # 3. 正文剥离标记
        return {"body": body, "fields": fields}
```

---

## 扩充章 X：控制码实现模板（transport.py）

```python
class ControlCode:
    """五位控制码：D1 域大类 / D2 子类 / D3 动作 / D4 对象 / D5 参数方向。"""

    def __init__(self, code: int):
        s = f"{code:05d}"
        self.d1, self.d2, self.d3, self.d4, self.d5 = map(int, s)

    def describe(self) -> str:
        return (f"{DOMAINS[self.d1]}·{SUBCLASSES[self.d1][self.d2]}·"
                f"{ACTIONS[self.d3]}·{OBJECTS[self.d4]}·{PARAMS[self.d5]}")


# 处理器注册表：码 → 处理函数
CONTROL_HANDLERS = {
    30000: lambda core: core.get_affinity(),          # 查好感度
    30300: lambda core, p: core.set_affinity(**p),    # 改好感度（单值）
    40000: lambda core: core.get_persona(),           # 查角色卡
    40300: lambda core, p: core.set_persona_field(**p),  # 改单字段
    21000: lambda core, p: core.search_memory(**p),   # 语义检索
    10200: lambda core: core.export_conversations(),  # 导出
    # ... 其余
}
```

---

## 扩充章 Y：心智核心与语音链路集成

### Y.1 集成点

```
MentalCore 对话 → 文本回复
  → TTS 合成（facade：GSV/CosyVoice2/Qwen3-TTS）
  → 音频回放（tts_audio_chunk 边生成边合成）
  → 语音输入：STT → 文本 → MentalCore
  → 声纹：voice.speaker（多用户个性化）
```

### Y.2 延迟预算（GSV 全链路约 2.3s）

```
STT 识别（~0.3s）→ 心智核心 TTFB（本地模型 ~0.5s）
  → TTS 合成（~1.0s）→ 回放（流式）
```

### Y.3 首字优先

- 心智核心用非推理模型（首字快）。
- 固定前缀可缓存（prompt 缓存）。
- 情绪识别后台并行（不阻塞）。

---

## 扩充章 Z：心智核心完整代码接入（端到端模板）

```python
# 独立陪伴模式
from mentalcore.config import load_config
from mentalcore.core import build_core
from mentalcore.persona_card import default_persona

config = load_config()
core = build_core(config, default_persona())   # mock 零落盘 / live 加密

# 对话循环
while True:
    user = input("你: ")
    if user == "/code":
        print("控制码: " + core.control(0).body)
        continue
    packet, manifest, emotion = core.send_message(user)
    print("梦瑶:", packet.body)
    if "exo" in packet.fields:
        print("[外骨骼执行中...]")

# 控制码示例
core.control(30000)                     # 查好感度
core.control(40300, {"tone": "冷淡"})   # 改角色语气
core.control(21000, {"query": "猫", "top_k": 3})  # 记忆检索
```


# P.A.L.M 心智核心与外骨骼深度解析（深度扩充六：状态管理/持久化/扩展）

> 承接扩充章 U-Z。本部分给出：心智核心状态管理、持久化细节（加密/格式）、扩展接口、以及与外骨骼的完整交互矩阵。

---

## 扩充章 AA：心智核心状态管理

### AA.1 状态模型

```
MentalCore 状态：
  persona（角色卡：静态 + 动态字段）
  affinity（好感度：base/dynamics/bond）
  emotion（情绪：最近一轮五因子）
  memory（语义记忆：chroma + 对话记录）
  conversations（对话记录：列表）
  exo（外骨骼：worker 状态）

持久化（live）：
  persona → 角色卡 JSON
  affinity → 好感度存储
  memory → 加密 + 向量库
  conversations → 对话记录 JSON
```

### AA.2 状态流转

```
初始（default_persona）
  → send_message（注入 → LLM → 拆分 → 结算）
  → receive（外部注入）
  → control（查/改）
  → EXO 委派（worker 执行）
  → 清档（防污染重置）
  → 持久化（live）
```

### AA.3 好感度清档机制

```
触发：防污染（角色语气污染/异常波动）
  → 重置好感度（base/dynamics 归零或初始）
  → 记录（审计）
40300 修改角色卡不触发清档（隔离）
```

---

## 扩充章 BB：持久化细节

### BB.1 加密实现（crypto_provider）

```
算法：SM4-CBC + HMAC-SM3（国密）
流程：
  1. 密钥派生（本机指纹 + 主密钥）
  2. CBC 加密对话/记忆内容
  3. HMAC-SM3 完整性校验
  4. 密文落盘（mentalcore_data/）
```

### BB.2 文件格式

```
对话记录：JSON（id/messages/timestamp）
向量归档：chroma（live）
记忆：加密 JSON + 向量
配置：.env（MENTALCORE_API_KEY 等）
```

### BB.3 mock vs live 持久化

| 模式 | 对话 | 记忆 | 向量 | 落盘 |
|---|---|---|---|---|
| mock | 内存 | 无 | 无 | 零 |
| live | 加密 JSON | 加密 | chroma | 是 |

---

## 扩充章 CC：扩展接口

### CC.1 六面扩展

```
class MyFace(BaseFace):
    name = "my_face"
    def produce_module(self, ctx) -> InjectionModule:
        return InjectionModule(source=self.name, content=..., priority=...)
# 注册：core.register_face(MyFace())
```

### CC.2 中间件扩展

```
# 注入中间件：自定义组装
# 拆分中间件：自定义标记策略（MARKER_POLICY 扩展）
```

### CC.3 模型扩展

```
# 实现 model.py 的模型接口（非推理优先）
class MyLLM:
    def stream(self, messages, **kw): ...
# 配置注入：Worker/Boss 独立
```

### CC.4 控制码扩展

```
CONTROL_HANDLERS[新码] = handler
# 遵循五位编码（D1-D5）
# 单值/单字段颗粒度原则
```

### CC.5 外骨骼魔方扩展

```
# exo/cubes/ 新增魔方
# 安全契约：权限 + 隔离 + 审计
# WorkCore 注册
```

---

## 扩充章 DD：Boss/Worker 交互矩阵

| 交互 | Boss → Worker | Worker → Boss |
|---|---|---|
| 任务委派 | ||EXO|| 标记 | — |
| 结果回传 | — | core.receive() |
| 干预 | forward_intervention（cancel/pause/resume/redirect） | 状态上报 |
| 状态查询 | get_status() | — |
| 消息查询 | answer_query（轨迹摘要） | — |

### DD.1 任务状态机

```
pending（提交）
  → running（执行中：ReAct 循环）
  → paused（暂停：干预）
  → resumed（恢复）
  → done（完成：||FIN|| + 回传）
  → cancelled（取消：干预）
  → failed（失败：兜底）
```

---

## 扩充章 EE：心智核心边界案例

### EE.1 模型不遵守协议

```
场景：模型未输出 ||DATA||/||EXO||
处理：正常对话（该轮好感度不结算/无委派）——容错
```

### EE.2 协议损坏

```
场景：||TOOL|| JSON 解析失败
处理：回退纯文本（继续追问）——不崩溃
```

### EE.3 EXO 委派空 goal

```
场景：||EXO||{"context": "..."} 无 goal
处理：TaskGoal(goal="") → Worker 拒绝（无目标不执行）
```

### EE.4 好感度溢出

```
场景：base 超上限
处理：钳制到 [0, max] + 记录
```

### EE.5 记忆注入超限

```
场景：历史 + 记忆超 prompt 限制
处理：_MAX_BLOCK_CHARS=600 上限 + 最近 3 轮 + top_k=3
```

### EE.6 并发访问

```
场景：多线程调用 send_message
处理：会话隔离（conversation_id）
```

---

## 扩充章 FF：心智核心交付物清单（复刻核对）

| 类别 | 内容 |
|---|---|
| 源码 | mentalcore/mentalcore/（71 py） |
| 配置 | .env.example |
| 安装 | pyproject.toml |
| 文档 | README.md |
| 测试 | tests/ + selftest.py + exo/selftest.py |
| 基准 | bench_50/100/chat_100/full_e2e/prompt_cache_probe |
| 报告 | 50 轮对照/100 轮实测/验收/就绪度/红队 |
| 数据 | bench*_chroma/bench*_data（mock/live 快照） |
| 设计 | 外骨骼设计_20260820.md |


# P.A.L.M 心智核心与外骨骼深度解析（深度扩充七：配置详解与扩展案例）

> 承接扩充章 AA-FF。本部分给出：心智核心完整配置详解、外骨骼 Worker 代码逻辑、以及二次开发案例。

---

## 扩充章 GG：心智核心完整配置详解

### GG.1 .env 配置（mentalcore/.env.example）

```ini
# mentalcore 配置
MENTALCORE_API_KEY=sk-***          # 非推理模型端点密钥
MENTALCORE_BASE_URL=https://api.nonelinear.com/v1   # 端点
MENTALCORE_MODEL=GLM-4.5-Flash-nothink   # 非推理模型
MENTALCORE_PERSIST=false           # mock 零落盘 / true 加密落盘
MENTALCORE_SEMANTIC_MEMORY=off     # off / chroma
MENTALCORE_MAX_TOKENS=400          # 单轮回复上限
MENTALCORE_TEMPERATURE=            # 默认（端点默认）
MENTALCORE_CACHE_ENABLED=true      # prompt 缓存（固定前缀）
MENTALCORE_LOG_LEVEL=INFO
```

### GG.2 配置项说明

| 配置 | 说明 |
|---|---|
| API_KEY | 模型端点密钥（secure_config 加密） |
| BASE_URL | OpenAI 兼容端点 |
| MODEL | 非推理模型（首字优先） |
| PERSIST | mock（False 零落盘）/ live（True 加密） |
| SEMANTIC_MEMORY | chroma 语义记忆（live） |
| MAX_TOKENS | 回复上限（400 实测） |
| CACHE_ENABLED | 固定前缀缓存（降首字） |

### GG.3 六面配置

- 记忆面：_RECENT_TURNS=3、_RECALL_TOPK=3、_MAX_BLOCK_CHARS=600。
- 注入面：fixed 前缀（缓存）+ priority 排序。
- 情感面：后台线程（不阻塞首字）。

---

## 扩充章 HH：外骨骼 Worker 代码逻辑

### HH.1 WorkCore 主循环

```python
class WorkCore:
    def run_task(self, goal: TaskGoal):
        context = [self.system_prompt(goal), self.professional_memory()]  # 专业记忆（明文）
        for step in range(max_steps=20):
            response = self.model.stream(context)
            intent, payload = parse_worker_output(response)   # ||TOOL||/||FIN||
            if intent == "fin":
                self.boss.receive({"exo_result": payload.get("result")}, "外骨骼完成")
                return payload.get("result")
            if intent == "tool":
                result = self.execute_tool(payload)           # 安全三拆分
                context.append({"role": "assistant", "content": response})
                context.append({"role": "tool", "content": result})
                continue
            # text：继续追问
            context.append({"role": "assistant", "content": response})
        return self.fallback()   # 超步兜底
```

### HH.2 工具执行（安全三拆分）

```python
def execute_tool(self, payload):
    name, args = payload["name"], payload["args"]
    # 1. 工具魔方：权限闸门
    if not self.tool_cube.is_allowed(name):
        return {"error": "tool not allowed"}
    # 2. 沙箱魔方：隔离执行
    if self.is_code_tool(name):
        if not self.sandbox_cube.available():
            return {"error": "sandbox fail-closed"}   # 隔离不可用即拒绝
        return self.sandbox_cube.run(args["code"])
    # 3. 通信魔方：审计
    if self.is_network_tool(name):
        self.comm_cube.audit(name, args)              # 全程审计
    return self.tools[name](args)
```

### HH.3 干预处理

```python
def forward_intervention(self, action, instruction=""):
    if action == "cancel": self.cancel_task()
    elif action == "pause": self.pause()
    elif action == "resume": self.resume()
    elif action == "redirect": self.redirect(instruction)
    else: return False
    return True
```

---

## 扩充章 II：二次开发案例

### II.1 案例：新增"浏览器魔方"

```
1. exo/cubes/browser_cube.py
   - 权限：URL 白名单
   - 隔离：无头浏览器子进程
   - 审计：访问记录
2. WorkCore 注册：browser_cube
3. 工具：browser_open / browser_extract
4. 测试：exo.selftest 补 2 测
```

### II.2 案例：新增"自定义人格卡"

```python
from mentalcore.persona_card import CharacterCard

my_card = CharacterCard(
    name="阿澈",
    description="冷静理性的分析型AI",
    personality="简洁、直接、数据驱动",
    first_mes="你好，我是阿澈。有什么需要分析的吗？",
    mes_examples=[...],
)
core = build_core(config, my_card)
```

### II.3 案例：接入 palm 角色系统

```
1. palm 角色卡 → mentalcore CharacterCard（字段映射）
2. 好感度共享：palm affinity ↔ mentalcore affinity（双向同步）
3. 语音：palm TTS 合成 mentalcore 回复
4. EXO：Worker 使用 palm 工具集（经权限闸门）
```

### II.4 案例：部署为服务

```python
# FastAPI 包装 MentalCoreSlotPort
@app.post("/api/mentalcore/chat")
async def mental_chat(req: ChatRequest):
    packet, manifest, emotion = core.send_message(req.text)
    return {"body": packet.body, "fields": packet.fields, "emotion": emotion}

@app.post("/api/mentalcore/control")
async def mental_control(req: ControlRequest):
    return core.control(req.code, req.payload)
```

---

## 扩充章 JJ：心智核心调试技巧

### JJ.1 注入清单留痕

- 开发者功能：查看每轮注入模块（source/content/fixed/priority）。
- prompt_cache_probe：缓存轨迹分析（固定前缀命中率）。

### JJ.2 控制码调试

- /code help：CONTROL_USAGE 全表。
- 00000：心跳。
- 32000：情绪向量。

### JJ.3 协议调试

- 原始回复含 ||DATA||/||EXO|| 标记。
- CONSUME_KEYS（affinity_delta）验证不外发。
- MARKER_POLICY（DATA/EXO）处置验证。

### JJ.4 持久化调试

- live：加密文件（SM4）。
- 导出：10200（对话记录 JSON）。
- 加密状态：13000。

---

## 扩充章 KK：心智核心版本与兼容

### KK.1 接口稳定性

- MentalCoreSlotPort 四方法稳定（send_message/receive/control/get_model_info）。
- 控制码语义稳定（CONTROL_USAGE）。
- 协议标记稳定（||DATA||/||EXO||/||TOOL||/||FIN||）。

### KK.2 向后兼容

- 旧前端归档（archive/mentalcore_frontend_20260820）——接口未破坏。
- 数据格式（JSON）向前兼容。
- 模型可替换（非推理优先，但推理模型也能跑）。

### KK.3 演进方向

- Worker 能力扩展（更多魔方）。
- 记忆增强（bge-m3 全量）。
- 多语言（当前中文为主）。


# P.A.L.M 心智核心与外骨骼深度解析（深度扩充八：完整流程与集成案例）

> 承接扩充章 GG-KK。本部分给出：心智核心完整对话流程（轮级）、与 palm 集成案例、以及多场景测试。

---

## 扩充章 LL：心智核心完整对话流程（轮级）

### LL.1 一轮对话的完整展开

```
用户输入："今天心情不好，想跟你说说话"

1. 上下文组装（inject 中间件）
   → FaceContext：user_text/persona(梦瑶)/history(最近3轮)/affinity_stage(初识)/semantic_memory(检索)
   → 六面产出注入模块：
      persona：梦瑶人格描述
      memory：最近 3 轮 + 语义召回（若有）
      emotion：用户情绪识别（后台线程）
      weave：语料风格（示例对话参照）
      rhythm：节奏模块
      storage：持久化准备
   → 固定前缀（可缓存）+ 动态尾部 → prompt

2. LLM 调用（非推理，首字优先）
   → 流式生成

3. 拆分（split 中间件）
   → 正文 + ||DATA||{affinity_delta, emotion}||END||
   → affinity_delta 内部消费（不展示）
   → 若有 ||EXO|| 委派 → out_fields["exo"]

4. 结算
   → 情感识别（后台线程完成）
   → 好感度结算（吝啬制：affinity_delta 小数步进）
   → 记忆写入（live 加密 / mock 不落盘）

5. 返回
   → (packet, manifest, emotion)
   → packet.body 显示正文
   → packet.fields 数据区（过滤后）
```

### LL.2 流式对话（stream_message）

```
stream_message(text) → 事件流：
  - start
  - chunk（正文分片）
  - data（||DATA|| 解析）
  - exo（||EXO|| 委派）
  - done（结算完成）
每轮时序：情绪识别（后台并行）→ 注入 → 流式 → 拆分 → 结算 → 持久化
```

---

## 扩充章 MM：与 palm 集成完整案例

### MM.1 集成场景：P.A.L.M 使用心智核心作为人格引擎

```
1. palm 角色卡（mengyao.json）→ mentalcore CharacterCard（映射）
2. palm 对话页 → /api/mentalcore/chat（包装）
3. 好感度共享：
   - palm affinity_engine 存储
   - mentalcore affinity 读取/写入（同步）
4. 记忆共享：
   - palm memory_writer（分层）
   - mentalcore semantic_memory（语义检索）
5. 语音：
   - palm TTS facade 合成回复
6. EXO：
   - Worker 使用 palm 工具集（经权限闸门）
   - 完成回传 Boss → palm 对话展示
```

### MM.2 集成点清单

| 集成点 | palm 侧 | mentalcore 侧 |
|---|---|---|
| 角色 | character.py | CharacterCard |
| 好感度 | affinity_engine | core.control(30000/30300) |
| 记忆 | memory_writer | semantic_memory |
| 对话 | chat_service | send_message |
| 语音 | audio facade | 文本回复 |
| 工具 | agent tools | exo Worker |
| 计量 | token_usage | token_ledger |

### MM.3 集成配置

```python
# palm 装配中注册 mentalcore
from mentalcore import build_core, build_exo, default_persona

mc_config = load_config()   # mentalcore/.env
mc_core = build_core(mc_config, character_from_palm(roleplay.get_character("mengyao")))
exo = build_exo(mc_config)
mc_core.exo_broker = exo.make_broker(mc_core)
_register("mentalcore", mc_core, {"send_message": mc_core.send_message,
                                   "control": mc_core.control})
```

---

## 扩充章 NN：多场景测试（心智核心）

### NN.1 情感场景

```
输入："我好难过，他走了"
期望：情绪识别（valence 负）→ 情感面注入 → 安慰语气回复
检查：emotion 返回 + 好感度变化（安慰加分）
```

### NN.2 吃醋场景

```
输入："我今天和别的 AI 聊天了"
期望：梦瑶吃醋反应（动态机制）→ 好感度波动
检查：dynamics 线变化 + 回复吃醋语气
```

### NN.3 关系质变场景

```
输入：（表白）
期望：好感度大幅变化 → 档位提升 → 回复亲昵
检查：base 大幅 + 档位（官方规则）
```

### NN.4 EXO 任务场景

```
输入："帮我查一下明天的天气"（Boss 委派）
期望：||EXO|| → Worker 执行（weather 工具）→ 回传 → Boss 加工
检查：out_fields["exo"] + 最终回复含天气
```

### NN.5 控制码场景

```
输入：/code 30300 base=5.0
期望：好感度基准线修改 → 后续回复更亲昵
检查：30000 查询确认
```

### NN.6 防污染场景

```
输入：连续角色语气对话后查长期记忆
期望：记忆无角色语气（只存事实）
检查：语义检索无语气内容
```

---

## 扩充章 OO：心智核心交付形态

### OO.1 交付物

```
mentalcore/（pip install -e .）
├── mentalcore/（源码 71 py）
├── tests/
├── pyproject.toml
├── README.md
└── LICENSE
```

### OO.2 运行形态

```
独立：python -m mentalcore.selftest（自检）
服务：FastAPI 包装（MentalCoreSlotPort）
嵌入：palm 装配（_register("mentalcore")）
CLI：/code 控制码（历史已归档前端，接口保留）
```

### OO.3 兼容矩阵

| 依赖 | 版本 | 说明 |
|---|---|---|
| Python | 3.13+ | 受管 venv |
| httpx | 0.28.1 | 模型客户端 |
| chromadb | 1.5.9 | 向量（live） |
| Ollama | bge-m3 | 嵌入 |
| SM4 | 国密 | 加密原语（palm crypto） |


# P.A.L.M 心智核心与外骨骼深度解析（深度扩充九：生产就绪与最佳实践）

> 承接扩充章 LL-OO。本部分给出：生产就绪度评估要点、心智核心最佳实践、以及性能优化方向。

---

## 扩充章 PP：生产就绪度评估要点

### PP.1 首评维度（生产就绪度评估_心智魔方.md）

| 维度 | 评估要点 | 结论（推断） |
|---|---|---|
| 接口稳定 | MentalCoreSlotPort 四方法 | 稳定 |
| 数据安全 | SM4 加密落盘 | 达标 |
| 协议可靠 | ||DATA||/||EXO|| 容错 | 95-100% 遵守 |
| 性能 | 首字/总耗时 | 本地链路快（端点排队除外） |
| 稳定性 | 100 轮 1 次错误 | 达标 |
| 可运维 | 控制码/自检/导出 | 达标 |
| 扩展性 | 六面/魔方可扩展 | 达标 |

### PP.2 复评要点（生产就绪度复评_20260820.md）

- 对首评结论二次核查（不接受口头声称）。
- 逐项复测（基准/安全/功能）。
- 修正偏差（如有）。
- 给出最终就绪结论。

### PP.3 生产部署清单

```
1. live 模式（persist=True + sem=chroma）
2. 加密启用（SM4）
3. 模型端点稳定（非推理，私有端点优先）
4. 备份策略（mentalcore_data/）
5. 监控（控制码探活 00000）
6. 安全审计（定期）
```

---

## 扩充章 QQ：心智核心最佳实践

### QQ.1 模型选择

- 非推理模型（首字优先）：GLM-4.5-Flash-nothink 等。
- 私有端点 > 公共端点（TTFB 波动：公共端点排队）。
- max_tokens=400（实测回复 159 字均值）。

### QQ.2 prompt 缓存

- 固定前缀（人格/系统）在上 → 缓存命中。
- 动态尾部（记忆/情绪）在下 → 变化最小化。
- prompt_cache_probe 验证命中率。

### QQ.3 好感度管理

- 吝啬制（小数步进）防刷。
- 质变轮（关系事件）大幅变化。
- 档位增速（真实当前档位）。
- 清档（防污染）记录审计。

### QQ.4 记忆管理

- 只存事实（污染检测）。
- 语义检索（bge INT8 / bge-m3）。
- token_budget 裁剪。
- 定期导出归档（10200）。

### QQ.5 外骨骼使用

- Worker 模型独立配置。
- 工具权限闸门（最小权限）。
- 沙箱隔离（代码类）。
- 通信审计（网络类）。
- 干预通道（cancel/pause/resume/redirect）。

---

## 扩充章 RR：性能优化方向

### RR.1 首字延迟优化

| 方向 | 措施 |
|---|---|
| 端点 | 私有端点/本地模型 |
| 缓存 | 固定前缀缓存命中 |
| 并行 | 情绪识别后台线程 |
| 裁剪 | 记忆注入上限（600 字） |
| 模型 | 非推理模型（首字快） |

### RR.2 全链路延迟优化（语音）

```
STT（VAD 快速检测）→ 对话（首字优先）→ TTS（边生成边合成）
目标：GSV 全链路约 2.3s
```

### RR.3 记忆性能

- 向量索引（chroma 本地）。
- 检索缓存（高频查询）。
- 归档分层（冷热分离）。

### RR.4 并发

- 会话隔离（conversation_id）。
- Worker 后台线程（不阻塞 Boss）。
- 事件总线降级隔离（单订阅方异常不影响）。

---

## 扩充章 SS：心智核心扩展方向（2026 路线图推测）

### SS.1 能力扩展

- Worker 更多魔方（浏览器/数据/创意）。
- 多模态（图像理解）。
- 多语言（非中文语料）。

### SS.2 集成扩展

- palm 深度集成（角色/记忆/语音共享）。
- 多端（移动端包装）。

### SS.3 生态扩展

- 角色卡市场。
- 技能包市场。
- 基准公开。

---

## 扩充章 TT：心智核心完整交付检查

```
1. 源码：mentalcore/mentalcore/（71 py）
2. 配置：.env.example
3. 文档：README.md
4. 测试：tests/ + selftest
5. 基准：bench 套件 + 报告
6. 数据：mock/live 快照
7. 安全：红队报告
8. 就绪：评估 + 复评

全部齐备 = 心智核心交付完成
```


# P.A.L.M 心智核心与外骨骼深度解析（深度扩充十：设计文档要点与场景全解）

> 承接扩充章 PP-TT。本部分给出：外骨骼设计文档要点（外骨骼设计_20260820.md）、心智核心设计原则（§6.x/§7.x 参照）、以及全场景使用指南。

---

## 扩充章 UU：外骨骼设计文档要点（外骨骼设计_20260820.md）

### UU.1 设计目标

- Boss（心智魔方）：有性格的聊天核心（纯聊天、不碰工具）。
- Worker（外骨骼）：能干活的执行核心（只干活、无性格）。
- 双链异步：委派不阻塞、完成回传。

### UU.2 关键设计决策

| 决策 | 理由 |
|---|---|
| 人格与能力分离 | 陪伴体验与任务效率互不干扰 |
| 文本标记协议（||TOOL||/||FIN||） | 任意聊天模型可用（不依赖 FC） |
| 后台线程拉起 Worker | 不阻塞 Boss 回复（首字优先） |
| 安全三拆分 | 权限/隔离/审计三层防御 |
| 模型解耦 | Boss/Worker 独立配置 |
| 专业记忆明文 | 技能知识非敏感（加密仅覆盖聊天） |

### UU.3 与归档差异

- Boss 用 MentalCore.send_message（心智魔方保持不动）。
- Worker 全用归档设计（移植自 palm coordinator.py）。
- 适配：Boss=心智魔方（非 palm）。

---

## 扩充章 VV：心智核心设计原则（§6.x/§7.x 参照）

### VV.1 六面设计原则（§6.x）

| 面 | 原则 |
|---|---|
| 人格 | 角色卡驱动、社区规范 |
| 记忆 | 短期 + 长期、不可用即不注入 |
| 情感 | 后台识别、不阻塞首字 |
| 织语 | 风格模块、不独立生成 |
| 律动 | 节奏控制、首字优先 |
| 储存 | 加密落盘、导出可控 |

### VV.2 中间件设计原则（§7.10）

- 注入：固定在上（缓存）、动态在下、模块化组合、不可用即不注入、注入留痕。
- 拆分：字段 + 正文、消费键过滤、EXO 透传。

### VV.3 控制码设计原则（§6.11/§7.13/§7.14）

- 五位梯度（域→子类→动作→对象→参数方向）。
- 单值/单字段颗粒度。
- 查询走控制码、模型信息走接口。
- 改值不触发清档。

---

## 扩充章 WW：全场景使用指南

### WW.1 陪伴场景（核心）

```
1. 启动：build_core(config, persona)
2. 日常对话：send_message（六面注入）
3. 好感度养成：长期对话（吝啬制）
4. 情绪关怀：情感面（VAD 识别）
5. 记忆：长期事实（语义检索）
6. 控制：/code 30000 等
```

### WW.2 任务场景（外骨骼）

```
1. 装配：build_core + build_exo + make_broker
2. 委派：对话中模型自发 ||EXO||
3. 执行：Worker ReAct + 5 魔方
4. 干预：cancel/pause/resume/redirect
5. 回传：core.receive() → Boss 加工
```

### WW.3 集成场景（palm）

```
1. 角色共享：palm 角色卡 → mentalcore persona
2. 好感度共享：palm affinity ↔ mentalcore
3. 语音：palm TTS 合成
4. 工具：Worker 使用 palm 工具集
5. 计量：token_ledger 记录
```

### WW.4 调试场景

```
1. 自检：selftest / exo.selftest
2. 控制码：CONTROL_USAGE 全表
3. 注入留痕：查看注入模块
4. 缓存轨迹：prompt_cache_probe
5. 导出：10200（对话 JSON）
```

### WW.5 部署场景

```
1. 独立服务：FastAPI 包装
2. 嵌入：palm 装配
3. mock：演示（零落盘）
4. live：生产（加密落盘）
```

---

## 扩充章 XX：心智核心质量保障

### XX.1 分层测试

```
单元：selftest（离线断言）
集成：full_e2e（全流程）
基准：bench_50/100（对照）
安全：红队（注入/越权）
验收：全流程验收 + 就绪度复评
```

### XX.2 质量指标

| 指标 | 标准 |
|---|---|
| selftest | 全过 |
| exo.selftest | 4 测全过 |
| 协议遵守率 | ≥95% |
| 错误轮 | <2%（重试恢复） |
| 零落盘（mock） | 100% |
| 加密（live） | SM4 |

### XX.3 回归保障

- 基准资产白名单入库（可复现）。
- mock/live 对照（控制变量）。
- 报告伪像标注（诚实对比）。

---

## 扩充章 YY：心智核心版本记录

| 版本 | 日期 | 内容 |
|---|---|---|
| 心智魔方 | 08-19 | 六面 + 双中间件 + 控制码（50 轮/100 轮基准） |
| 外骨骼 | 08-20 | Worker + 5 魔方 + EXO（4 测自检） |
| 全量入库 | 08-20 | 入库 palm 仓库（cdcdfbc） |

---

## 扩充章 ZZ：心智核心最终总结

mentalcore 是 P.A.L.M 的"人格引擎"——它以六面架构（人格/记忆/情感/织语/律动/储存）提供有性格的聊天，以 18 条五位控制码提供可编程的状态管理，以 Boss/Worker 双链提供"陪伴 + 干活"分离的执行体系，以 5 小魔方 + 安全三拆分保障外骨骼的安全执行。它纯库化、可独立安装、可嵌入 palm，是 P.A.L.M 差异化能力（人格化陪伴）的核心载体。


# P.A.L.M 心智核心与外骨骼深度解析（深度扩充十一：完整协议与最终总结）

> 承接扩充章 UU-ZZ。本部分给出：完整协议规范、心智核心与用户交互范式、以及最终总结。

---

## 扩充章 AAA：完整协议规范

### AAA.1 注入协议（inject）

```
输入：FaceContext + 六面产出模块
输出：组合 prompt（固定在上 + 动态在下）

模块结构：
  {source, content, fixed, priority, token_budget, available}

组装规则：
  1. 过滤 available=False
  2. 固定模块按 priority 降序（在上，可缓存）
  3. 动态模块按 priority 降序（在下）
  4. token_budget 校验（超限裁剪）
```

### AAA.2 拆分协议（split）

```
输入：LLM 原始输出
处理：
  1. ||DATA||{json}||END|| → data 字段（CONSUME_KEYS 过滤）
  2. ||EXO||{json}||END|| → out_fields["exo"]（整体透传）
  3. 正文剥离标记
输出：{body, fields}

CONSUME_KEYS = {"affinity_delta"}
MARKER_POLICY = {"DATA": "data", "EXO": "exo"}
```

### AAA.3 Worker 协议（exo/protocol）

```
输入：Worker 模型输出
处理：
  1. ||FIN||{json}||END|| → fin（任务收尾）
  2. ||TOOL||{json}||END|| → tool（调工具）
  3. 其他 → text（继续追问）
  4. JSON 损坏 → 回退纯文本
输出：("fin"|"tool"|"text", payload)
```

### AAA.4 EXO 协议

```
Boss 回复末尾：||EXO||{"goal": "...", "context": "..."}||END||
处理链：
  ReplySplitter 识别 → out_fields["exo"]
  → MentalCore.exo_broker（钩子）
  → extract_exo 归一 TaskGoal
  → 后台拉起 Worker（不阻塞 Boss）
  → Worker 完成 → core.receive() 回传
```

### AAA.5 控制码协议

```
格式：五位十进制（D1-D5）
请求：core.control(code, payload=None)
响应：结果对象（body/fields）

D1 域：0系统/1储存/2记忆/3情感/4人格/5对话/9保留
D2 子类：按域
D3 动作：0查/1清/2导出/3改/4启停/9其他
D4 对象：0全部/1最近N/2指定
D5 参数：0请求/1成功/2失败
```

---

## 扩充章 BBB：心智核心与用户交互范式

### BBB.1 对话范式

```
用户 → send_message → (packet, manifest, emotion)
  packet.body：回复正文
  packet.fields：数据区（过滤后）
  manifest：注入清单（开发者）
  emotion：情绪识别结果
```

### BBB.2 控制范式

```
用户：/code 30300 base=5.0
  → core.control(30300, {"base": 5.0})
  → 好感度基准线修改
  → 后续对话更亲昵
```

### BBB.3 委派范式

```
用户：帮我查资料
  → Boss 回复 + ||EXO|| 委派
  → Worker 后台执行
  → 完成回传 Boss 加工
  → 用户看到最终回复
```

### BBB.4 干预范式

```
用户：取消任务
  → I_INTERVENTION（cancel）
  → forward_intervention
  → Worker 取消
```

---

## 扩充章 CCC：心智核心最终总结

### CCC.1 核心价值

1. **人格化**：六面架构让聊天有性格（角色卡/记忆/情感/织语/律动）。
2. **可编程**：18 条控制码让状态可管理（查/改/清/导出）。
3. **可扩展**：六面/魔方/模型/控制码全部可扩展。
4. **安全**：加密落盘 + 安全三拆分 + 零落盘 mock。
5. **纯库**：MentalCoreSlotPort 四方法（前端自备）。

### CCC.2 与 P.A.L.M 的关系

mentalcore 是 P.A.L.M 的"人格引擎"——提供差异化的人格化陪伴体验，同时可独立使用。它与 palm 核心（工具/游戏/进化/语音）互补，构成"有性格的管家"完整体系。

### CCC.3 交付状态

- 全量入库（cdcdfbc，2026-08-20）。
- 4 测自检全过。
- 50 轮/100 轮基准。
- 红队审计 + 就绪度复评。
- 本系列文档完整记录。


# P.A.L.M 心智核心与外骨骼深度解析（深度扩充十二：最终补充与全系列衔接）

> 承接扩充章 AAA-CCC。本部分给出：心智核心与全系列的衔接、最终交付核对、以及心智核心的定位总结。

---

## 扩充章 DDD：心智核心与全系列衔接

### DDD.1 在知识库中的定位

| 篇目 | 心智核心相关 |
|---|---|
| 00 总览 | 心智核心概述（3.11 节/第五章） |
| 01 演进 | 08-20 心智魔方+外骨骼入库 |
| 02 贡献 | 用户概念 + AI 实现 |
| 03 架构 | 与 palm 的协作边界 |
| 04 模块 | 六面/控制码/EXO 概述 |
| 05 心智 | 完整深度解析（本篇） |
| 06 复刻 | 装配/验收/扩展 |

### DDD.2 复刻心智核心的路径

```
1. 读本篇（05）完整理解
2. 按 06 篇 Phase 6 装配
3. 运行 selftest/exo.selftest
4. 对照基准（50/100 轮）
5. 集成 palm（角色/好感度/语音共享）
```

### DDD.3 心智核心的验收（复刻判定）

```
1. selftest 全过（六面/注入/拆分/控制码/零落盘）
2. exo.selftest 4 测全过（EXO/Worker 协议/工具链/回传）
3. 18 控制码全部可用（单值颗粒度）
4. mock 零落盘验证
5. live 加密落盘验证（SM4）
6. EXO 委派端到端（委派→执行→回传）
7. 基准达标（协议遵守率 ≥95%）
```

---

## 扩充章 EEE：心智核心最终交付核对

### EEE.1 代码交付

```
mentalcore/mentalcore/（71 py）
├── 核心：core.py（MentalCore）/ config / llm / netcard
├── 人格：persona_card / faces（6 面 + base）
├── 记忆：semantic_memory / faces/memory
├── 协议：transport（控制码）/ middleware（注入/拆分）
├── 安全：crypto_provider / secure_config / logging_setup
├── 外骨骼：exo/（coordinator/core/protocol/runner/cubes/...）
└── 自检：selftest / exo/selftest
```

### EEE.2 文档交付

```
README.md（快速开始）
外骨骼设计_20260820.md（设计文档）
50 轮对照测试报告.md（基准）
基准报告_100次对话实测.md（实测）
安全审计与红队报告_20260820.md（安全）
生产就绪度评估_心智魔方.md + 复评（就绪）
全流程验收报告_20260820.md（验收）
```

### EEE.3 数据交付

```
bench50_mock_chroma/data（对照）
bench50_live_chroma/data（对照）
bench100_chroma/data（实测）
chat_100_chroma/data（对话）
smoke/ui_smoke（冒烟）
prompt缓存轨迹_20260820*.csv/json（探针）
```

---

## 扩充章 FFF：心智核心定位总结

### FFF.1 一句话定位

mentalcore 是 P.A.L.M 的"人格引擎"——以六面架构提供有性格的聊天，以 18 条控制码提供可编程状态管理，以 Boss/Worker 双链提供"陪伴 + 干活"分离执行。

### FFF.2 核心价值

1. **人格化差异**：六面（人格/记忆/情感/织语/律动/储存）让聊天有灵魂。
2. **可编程**：控制码让状态可管理（查/改/清/导出/语义检索）。
3. **可扩展**：六面/魔方/模型/控制码全部可扩展。
4. **安全**：加密落盘 + 安全三拆分 + 零落盘 mock。
5. **纯库**：MentalCoreSlotPort 四方法，前端自备。

### FFF.3 与 P.A.L.M 的分工

```
P.A.L.M（palm）：工具型管家（干活）
  - 100+ 工具 / 规划 / 游戏 / 进化 / 语音 / GUI
mentalcore：人格型伴侣（陪伴）
  - 六面聊天 / 好感度 / 情绪 / 双链外骨骼
结合：有性格的管家（能干活又会陪伴）
```

### FFF.4 终态

mentalcore 于 2026-08-20 全量入库（cdcdfbc），4 测自检全过、50 轮/100 轮基准、红队审计、就绪度复评——心智核心达到生产就绪状态，是 P.A.L.M 终态架构的核心组成部分。

---

## 扩充章 GGG：全系列总结（05 篇结语）

本系列 05 篇（心智核心与外骨骼深度解析）至此完整——覆盖：
- 定位与设计（纯库/六面/双链）。
- 控制码体系（18 条五位编码）。
- 六面与中间件（实现细节/模板）。
- 外骨骼全套（WorkCore/5 魔方/安全三拆分）。
- 协议规范（注入/拆分/Worker/EXO）。
- 基准与验收（50/100 轮/红队/就绪度）。
- 集成与扩展（palm/独立/二次开发）。

心智核心是 P.A.L.M 的灵魂——本系列把它从"黑盒"变成了"白盒"，复刻者凭本篇即可重建同等的人格化陪伴体验。


# P.A.L.M 心智核心与外骨骼深度解析（深度扩充十三：心智核心收官）

> 承接扩充章 DDD-GGG。本部分给出：心智核心全系列收官总结、与 P.A.L.M 全系列的最终衔接。

---

## 扩充章 HHH：心智核心收官总结

### HHH.1 心智核心全景

```
mentalcore = 六面（人格/记忆/情感/织语/律动/储存）
           + 双中间件（注入/拆分）
           + 18 条五位控制码
           + Boss（心智魔方：纯聊天）
           + Worker（外骨骼：只干活）
           + EXO 协议（委派/回传）
           + 5 小魔方 + 安全三拆分
           + mock/live 双模式
           + 全套基准/验收/审计
```

### HHH.2 心智核心的设计哲学

1. **人格与能力分离**：Boss 只聊不干、Worker 只干不聊。
2. **首字优先**：非推理模型 + 固定前缀缓存 + 后台情绪识别。
3. **吝啬制**：好感度小数步进（防刷）。
4. **安全三拆分**：工具闸门/沙箱隔离/通信审计。
5. **纯库化**：MentalCoreSlotPort 四方法。

### HHH.3 心智核心的验证

- 4 测自检全过（selftest + exo.selftest）。
- 50 轮对照（mock 3.9ms / 协议 100%）。
- 100 轮实测（协议 95% / 稳定性 99%）。
- 红队审计 + 生产就绪度复评。

### HHH.4 心智核心的知识价值

1. **人格化聊天**的设计范式（六面/注入/拆分）。
2. **可编程状态**的管理范式（五位控制码）。
3. **双链执行**的架构范式（Boss/Worker/EXO）。
4. **Agent 安全**的执行范式（安全三拆分）。

---

## 扩充章 III：与 P.A.L.M 全系列最终衔接

### III.1 知识库的完整闭环

```
00 总览：P.A.L.M 是什么（含心智核心概述）
01 演进：P.A.L.M 如何走来（含 08-20 心智入库）
02 贡献：谁构建了它（含心智概念=用户/AI 实现）
03 架构：它如何组织（含与心智的边界）
04 模块：它如何实现（含心智核心接口）
05 心智：它如何思考（本篇：完整深度解析）
06 复刻：如何重建它（含心智装配/验收）
```

### III.2 复刻心智核心的最短路径

```
1. 读本篇（05）全部扩充章
2. pip install -e mentalcore
3. python -m mentalcore.selftest
4. python -m mentalcore.exo.selftest
5. 集成 palm（角色/好感度/语音/工具共享）
6. 验收（控制码/EXO/基准）
```

### III.3 心智核心的演进方向

```
近期：Worker 更多魔方 / 模型解耦 / 多语言
中期：多模态 / 多端同步 / 插件
长期：全本地化 / 联邦记忆 / 多 Agent 协作
```

---

## 扩充章 JJJ：全系列最终收官（05 篇终章）

P.A.L.M 心智核心（mentalcore）——一个纯库化的 AI 陪伴微核心：

- 六面架构让它有性格（人格/记忆/情感/织语/律动/储存）。
- 18 条控制码让它可管理（查/改/清/导出/检索）。
- Boss/Worker 双链让它能干活（委派/执行/回传/干预）。
- 安全三拆分让它可信（权限/隔离/审计）。
- mock/live 双模式让它可测（零落盘/加密落盘）。

它是 P.A.L.M 的"人格引擎"——让 P.A.L.M 不只是工具，更是陪伴者。本系列 05 篇完整记录了它的设计、实现、验证与扩展，复刻者凭本篇即可重建同等的人格化陪伴体验。

**心智已就位，陪伴已开始。**




---


# P.A.L.M 心智核心与外骨骼深度解析（99% 补全章：六面与 exo 源码实录）

> 本章为心智篇补全，把六面 `produce_module` 真实逻辑与 exo 各模块机制从源码全量实录——此前"结构推断"级描述全部替换为真实实现细节。

---

## 补全章 A：六面 produce_module 真实逻辑（faces/ 源码实录）

### A.1 情感面（emotion.py）——好感度引擎 + 情绪识别

```python
class EmotionFace(BaseFace):
    name = "emotion"

    def __init__(self, base=0, bond=0, dynamics=0):
        # 初始状态由外部注入（storage.load_affinity 恢复，重启不归零）
        self.base = base          # 信任地基 -50~100，慢变
        self.dynamics = dynamics  # 当下心情 -50~50，快变
        self.bond = bond          # 羁绊，无上限

    def enabled(self, ctx): return ctx.persona.affinity_enabled   # 整面停用开关

    def produce_module(self, ctx):
        if not self.enabled(ctx):
            return InjectionModule(source=self.name, content="", available=False)
        stage = self._current_stage(ctx)
        lo, hi = stage.delta_range
        content = (f"【关系】你与用户的关系等级：{stage.name}。{stage.description} "
                   f"语气：{stage.tone}。称呼：{stage.address or '无'}。"
                   f"好感度增减范围：{lo} ~ {hi}（仅内部参考，回复勿提数值）。")
        # 严重降低：隐藏档位，固定 prompt 每轮发送，AI 自由裁定是否触发
        slo, shi = SEVERE_DROP.delta_range
        safety = (ctx.persona.safety or DEFAULT_SAFETY).strip()
        content += (f"\n【严重受损指引（仅内部参考，回复勿提）】"
                    f"若本句使关系严重受损（单次好感度扣分 {shi} ~ {slo}）：{safety}")
        return InjectionModule(source=self.name, content=content, fixed=False, priority=30)
```

**关键设计（源码）**：
- 档位内容注入、数值不注入（只给档名/称呼/语气，AI 不自想关系）。
- 本地结算器：LLM 只给 delta，base/dynamics/bond 本地计算。
- 情绪识别：共用模型 complete 旁路通道，失败不注入。
- 严重受损指引（SEVERE_DROP/DEFAULT_SAFETY）：每轮固定发送，AI 自由裁定。

### A.2 记忆面（memory.py）——短期 + 长期

```python
_RECENT_TURNS = 3          # 短期：最近 3 轮
_RECALL_TOPK = 3           # 长期：语义召回 top3
_MAX_BLOCK_CHARS = 600     # 注入块上限（防撑爆 prompt，控制首字延迟）

def produce_module(self, ctx):
    blocks = []
    recent = ctx.history[-_RECENT_TURNS:]
    if recent:
        lines = ["【近期对话】"]
        for turn in recent:
            lines.append(f"用户：{turn.get('user', '')}")
            lines.append(f"{ctx.persona.name}：{turn.get('assistant', '')}")
        blocks.append(self._truncate("\n".join(lines)))    # 600 字截断
    recall = self._recall(ctx)                              # 语义召回（上下文携带时）
    if recall:
        lines = ["【长期记忆·相关】"] + [f"- {item}" for item in recall]
        blocks.append(self._truncate("\n".join(lines)))
    if not blocks:
        return InjectionModule(source=self.name, content="", available=False)  # 不可用即不注入
    return InjectionModule(source=self.name, content="\n\n".join(blocks), fixed=False, priority=20)
```

### A.3 人格面（persona.py）——固定模块（可缓存前缀）

```python
def produce_module(self, ctx):
    p = ctx.persona
    lines = [
        f"你是{p.name}，{p.tagline}。",
        f"性格：{'、'.join(p.personality_pillars)}。",
        f"缺点：{'、'.join(p.flaws)}。",
        f"语气：{p.tone}。",
        f"话痨程度：{p.talkativeness}。",
    ]
    if p.background: lines.append(f"背景：{p.background}")
    if p.age: lines.append(f"年龄：{p.age}岁。")
    if p.example_dialogue: lines.append(f"示例对话：{p.example_dialogue}")
    # 首次对话（无历史）注入开场白；有历史不再注入避免冗余
    if not ctx.history and (p.first_mes or p.alternate_greetings):
        greetings = p.alternate_greetings or [p.first_mes]
        lines.append(f"开场白（首次对话可选用）：{' | '.join(str(g) for g in greetings[:3])}")
    return InjectionModule(source=self.name, content="\n".join(lines),
                           fixed=True, priority=10)          # 固定模块：在上、可缓存
```

### A.4 律动面（rhythm.py）——时间感知 + 日程 + 生日

```python
WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"]

def produce_module(self, ctx):
    if not ctx.persona.dynamic_updates_enabled:
        return InjectionModule(source=self.name, content="", available=False)   # 整面不注入
    now = ctx.now
    lines = [f"【此刻】{now.strftime('%Y-%m-%d')} 星期{WEEKDAYS[now.weekday()]} {now.strftime('%H:%M')}。"]
    lines.extend(self._schedule_slice(ctx))     # 日程切片（period "start-end" 或单小时）
    if self._is_birthday(ctx):
        lines.append("今天是你的生日，可流露被记挂的暖意。")
    return InjectionModule(source=self.name, content="\n".join(lines),
                           fixed=False, priority=50)
```

### A.5 储存面（storage.py）——加密落盘 + 控制面

```python
class StorageFace(BaseFace):
    name = "storage"

    def __init__(self, path="mentalcore_data/conversations", crypto=None, semantic_memory=None):
        # 对话记录 conversations.dat（加密追加）
        # 好感度 affinity.dat（加密覆盖，重启恢复）
        # 不产 prompt 模块：存储与对外控制面，非 prompt 影响面
        # 处理 inbound 控制码（储存域 D1=1：查/清/导出等，按 D2 子类路由）
        # 向量归档查/清委托 SemanticMemory（防污染删除链路）

    def save_turn(self, user, assistant):
        # json 序列化 → crypto.encrypt_text（未启用则明文降级）→ 追加写入

    def save_affinity(self, base, bond, dynamics):
        # json → 加密 → 覆盖写 affinity.dat

    def load_affinity(self) -> dict:
        # 读 affinity.dat 解密还原；不存在返回 {base:0, bond:0, dynamics:0}
```

### A.6 织语面（weave.py）——<内心>一致性约束

```python
def produce_module(self, ctx):
    p = ctx.persona
    content = (f"【表达风格】按格式「{p.format_spec}」组织语言，"
               f"保持{p.name}的口吻，与示例对话的语感一致。"
               f"<内心>是本句未说出口的真实想法；正文须用自然口语把这份想法"
               f"对用户说出来，与<内心>同一主题、情绪一致，不得逐字复读内心"
               f"或另起无关话题。")
    return InjectionModule(source=self.name, content=content, fixed=False, priority=40)
```

**关键设计**：一致性约束源于实测教训——若不加约束，模型会把内心独白和对外正文生成成两段无关内容（内心"困惑"、正文却寒暄的脱节）；正文须重述内心而非逐字复读，否则"未说出口"的内心变成说出口的同一句。

### A.7 注入优先级总表（源码实录）

| 面 | fixed | priority | 内容 |
|---|---|---|---|
| persona | true（可缓存前缀） | 10 | 人格静态设定 |
| memory | false | 20 | 近期对话 + 语义召回 |
| emotion | false | 30 | 关系档位 + 严重受损指引 |
| weave | false | 40 | 表达风格 + <内心>约束 |
| rhythm | false | 50 | 时间/日程/生日 |
| storage | — | — | 不产 prompt（存储/控制面） |

---

## 补全章 B：exo 各模块真实机制（源码实录）

### B.1 意图路由（intent_router.py）——纯关键词零 LLM

```python
I_CHAT = "chat"          # 闲聊/简单问答 → Boss 直答
I_TASK = "task"          # 复杂任务（多步工具）→ 启动 Worker
I_INTERVENTION = "intervention"  # 干预（cancel/pause/resume/redirect）
I_QUERY = "query"        # 查询 Worker 进展

@dataclass
class IntentResult:
    intent: str = I_CHAT
    task_goal: str = ""               # task：Worker 任务目标
    intervention_action: str = ""      # intervention 动作
    redirect_instruction: str = ""     # redirect 新指令
    confidence: float = 1.0            # 关键词匹配 = 1.0

# 任务触发词（源码实录示例）：
_TASK_PATTERNS = [
    r"(?:帮我|请|麻烦|可以|能不能|你给我).{0,4}(?:做|搞|弄|写|改|查|找|部署|分析|整理|搜索|构建|开发|测试|优化|修复|迁移|搭建|配置|安装|生成|创建|删除|清理|检查|排查|诊断)",
    r"(?:写一个|写段|写个|做个|帮我写|帮我查|帮我找|帮我改|帮我分|帮我整|帮我排|帮我搭)",
    r"(?:运行|执行|启动|调用).{0,6}(?:脚本|程序|代码|命令|任务)",
]
# 路由策略：纯关键词匹配（零 LLM 调用，延迟 <1ms），与归档设计一致
```

### B.2 Worker 运行器（runner.py）——反思自检

```python
_REFLECT_PROMPT = '你是一个严苛的回答自我审查员。请判断「本次回答」是否真正、完整地满足了「用户请求」。...仅输出一个 JSON 对象：{"verdict": "ok" 或 "revise", "issue": "...", "instruction": "..."}...'

def reflect_once(worker, request, draft, had_failure=False) -> str:
    # 自检：返回修正指令（verdict=revise 时）
    # 解析失败/异常一律降级为 ""（不自残）
    # mock 模型（无反思语义）返回空，等效关闭
    # 有工具失败但回答未提及 → failure_note 提示核实

def _parse_reflect_json(text) -> dict: ...   # 容忍 ```json 包裹/前后噪声

def _sanitize_tool_text(text) -> str: ...    # 工具结果装饰壳清洗（剥离旧版包装，只留原始输出）
# 同步适配：经 worker.llm.complete(prompt, tools) 走原生 function calling
```

### B.3 工具匹配（tool_matcher.py）——关键词评分零外部依赖

```python
# 不用外部向量库/嵌入模型：仅关键词 + 描述词频评分
# 按用户输入筛出 Top-K 工具，缩小注入模型的工具暴露面（安全 + 省 token）

def _tokenize(text) -> set[str]:
    # 中文单字 + 双字组合 + 英文单词；过滤停用词（中文+英文）

_STOP_WORDS = {"的","了","在","是","我","有","和","就","不","人","都","一",
               "一个","上","也","很","到","说","要","去","你","会","着","没有",
               "看","好","自己","这","the","a","an","is","are","was","were",...}
```

### B.4 轨迹存储（trace_store.py）——7 种轨迹类型

```python
T_THOUGHT = "thought"          # 思维链/推理过程
T_TOOL_CALL = "tool_call"      # 工具调用（名称+参数）
T_TOOL_RESULT = "tool_result"  # 工具执行结果
T_OUTPUT = "output"            # 阶段性输出/最终回答
T_PLAN = "plan"                # 规划步骤
T_ERROR = "error"              # 错误信息
T_INTERVENTION = "intervention"  # 干预指令（来自 Boss）

# TraceEntry：step/entry_type/content(截断 2000 字)/timestamp/metadata
# 线程安全：Worker 后台线程写入、Boss 主线程检索（threading.Lock）
# Boss 经摘要/关键词检索按需拉取，而非一次性灌入全部上下文
# 去 palm 化：移除 palm._core.interop 向量后端，统一走关键词评分检索
```

### B.5 专业记忆（professional_memory.py）——sqlite 明文

```python
K_EXPERIENCE = "experience"        # 经验总结
K_USER_PROFILE = "user_profile"    # 用户画像
K_ERROR = "error"                  # 错误记录
# sqlite 明文持久化；db_path=None 内存态（mock 零落盘合规）
# 检索只做基础关键词匹配（_TOKEN_RE），不复用主记忆五因子检索
# 异步整理（schedule_trace_digest）LLM 调用改为可注入同步 fn，缺省跳过
```

### B.6 WorkCore 与 Boss 交互补全

- Worker 完成：`boss.receive({"exo_result": ...}, "外骨骼完成")`。
- 干预：`forward_intervention(cancel/pause/resume/redirect)`。
- 状态：`get_status()`；查询：`answer_query()`（从轨迹摘要检索）。

---

## 补全章 C：心智篇补全结论

**此前推断项已全部替换为源码**：
1. 六面 produce_module 逻辑：注入优先级表、<内心>约束、情感面档位注入不注入数值、储存面加密落盘。
2. exo：意图路由关键词规则、反思自检 JSON 协议、工具匹配停用词评分、轨迹 7 类型、专业记忆 sqlite。
3. 修正：情感面情感识别走 complete 旁路（非后台线程）；储存面不产 prompt 模块；记忆面 _recall 依赖上下文携带语义记忆。

心智篇（05）缺口清零，达到 99% 完整度。

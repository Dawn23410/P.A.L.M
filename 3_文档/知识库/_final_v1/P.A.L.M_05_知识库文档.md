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



# P.A.L.M 项目总览与产品说明（从零重建版）

> 本文档基于 2026-08-18 归档备份（D:/PALM_backup_20260818）与当前工作区（C:/Users/24459/Desktop/P.A.L.M）的真实代码与 git 历史从零撰写，不依赖任何过期说明文档。数据来源包括：当前 palm/ 库源码（约 240 个 Python 文件）、mentalcore/ 心智核心源码、归档 git 仓库 reflog（84 条提交记录）、Data/brick_inventory.json（24 砖清单）、.env.example 配置模板与运行数据目录。文档目标颗粒度为"可 1:1 完整复刻"，即读者仅凭本文档系列即可重建出功能等价的项目。

---

## 第一章 项目是什么

### 1.1 一句话定义

P.A.L.M（Personal AI Life Manager，个人 AI 生活管家）是一款运行在 Windows 桌面端的个人 AI 助手系统。它以 FastAPI 提供后端服务、以浏览器/桌面壳提供前端界面，围绕一个自研的 Agent 框架运转，具备角色扮演、好感度养成、记忆分层、自主进化、语音合成、GUI 自动化、游戏化激励、对话缝合检索等能力。系统自 2026 年 7 月底启动开发，至 2026 年 8 月 20 日已迭代出"终极架构"：一个自洽的 Python 库 palm/（含 15 个 Port 契约、领域层、服务层、适配器层、装配层）与一个独立的"心智核心" mentalcore/ 库。

### 1.2 产品定位

P.A.L.M 不是普通的聊天机器人，它有四个差异化定位：

第一，**本地优先的 AI 管家**。核心推理走云端大模型（DeepSeek 系列经 tokenhub.tencentmaas.com 代理），但记忆、角色、工具、调度、安全裁决全部在本机完成，运行期零强制联网（对话缝合引擎明确"运行期零联网"）。所有敏感数据（密钥、记忆库）经本机加密落盘。

第二，**带人格的伴侣型 AI**。系统内置"角色扮演引擎"，支持 Markdown 人格技能卡（内置「梦瑶 — 猫娘性格」角色），好感度分 10 级分层，角色会随互动动态变化（动态机制、双线好感度：基准线 + 动态线）。聊天记录、记忆、语气、开场白（first_mes）全链路接入。

第三，**工具化的全能管家**。Agent 框架内置 100+ 工具，覆盖文件处理、网络访问、GUI 自动化（L0-L3 四级容错执行器）、代码执行沙箱、语音、搜索等；工具调用全部经过 5 档裁决引擎（guardrail）与权限引擎（permission）双重门禁。

第四，**游戏化的养成系统**。星砂货币商城、道具、经验值、10 阶 × 100 级全局等级、每日任务、五子棋对局等游戏生态，让 AI 陪伴有"长线养成"的乐趣。

### 1.3 关键数字速览（以真实代码为准）

- 后端框架：FastAPI，服务端口 8005（后端）、前端开发 5173、e2e 测试 8012。
- 核心库 palm/：约 240 个 Python 文件；15 个 Port 契约；14 个装配服务（storage/settings/crypto/models/gui/usage/usage_ledger/scheduler/conversations/game/affinity/roleplay/memory/evolution/agent）。
- 心智核心 mentalcore/：独立可安装 Python 库（pyproject.toml），含心智魔方（Boss）与外骨骼（Worker）双链架构、18 条控制码、7 个外骨骼小魔方。
- 砖块体系演进：早期"主板 + 砖块 + 总线"架构曾达 24 砖（Data/brick_inventory.json 实录），后经"终极架构"重构为"服务容器 + 能力门面"，旧体系整体归档。
- 前端：12 个 HTML 页面（每界面一文件）+ ui/ 共享组件，原生 ES Modules，无构建链。
- 语音：GSV（实时播音员）、CosyVoice2（音色设计师）、GPT-SoVITS（TTS）、STT 语音识别四引擎统一门面；本地 Qwen3-TTS（VoiceDesign 模型）方案 B 已部署。
- 游戏：星砂货币、道具、经验、好感度、角色卡五大子系统；等级 10 阶 × 100 级。
- git 历史：归档仓库 reflog 84 条提交（2026-07-31 克隆起），当前仓库因"终极架构"重建仅保留 8 条（截至 2026-08-20）。

---

## 第二章 技术栈全景

### 2.1 后端

- **Python 3.11/3.13**：项目以 Python 3.11 为主力运行时（系统环境 Python311），隔离运行环境（venv_runtime/venv_cosyvoice/venv_gsv）分别承载主程序与语音引擎。
- **FastAPI + Uvicorn**：HTTP 服务框架；历史审计显示曾全量扫描 163 个端点无 500（仅依赖缺失降级 503）。
- **服务容器**（palm/_core/container.py）：取代早期 registry/主板的依赖注入机制。服务按名注册，业务代码经 `container.get(名)` 惰性取用，缺失归一 None（铁律：缺失归一降级，业务侧必须判空）。
- **自研 Agent 框架**（palm/services/agent/）：支持规划引擎（先制定计划、分步执行、失败自动重规划）、ReAct 循环、原生 function-calling（FC）、反思自检闸门、上下文真压缩（旧轮次摘要化）、结构化输出与运行轨迹追踪。
- **裁决引擎**（palm/_core/guardrail/）：5 档安全裁决（engine.py + rules.py），AI 档无回调时 fail-closed deny。
- **网卡门面**（palm/_core/net/）：唯一出网出口，fail-closed。
- **事件总线**（palm/_core/eventbus.py）与 **传输层**（palm/_core/transport.py）：承载 SSE 事件流、ask_user 应答等实时交互。
- **Token 计量**（palm/services/ops/token_ledger.py + token_usage.py）：provider 侧真实用量落库、估算量不入账、配额检查（check_quota）。

### 2.2 前端

- **原生 HTML/JS/CSS**：12 个 HTML 页面（shell.html 外壳 + ui/ 组件 + 11 个 screen），原生 ES Modules，去构建链。页面包括：对话、系统总览中枢、存储面板、用量面板、商城、保险库、设置等。
- **PALM 桥接层**：pywebview 桌面壳中经 `window.pywebview.api` 调用后端；桌面部件（widget）系统经桥接层封装。
- **开发服务器**：Vite（端口 5173）用于开发；生产环境静态托管。

### 2.3 桌面与系统

- **pywebview**：桌面壳容器。
- **Windows 原生能力**：GUI 自动化（uiautomation 辅助功能语义，辅助模式须先 CoInitializeEx(STA)）、Win32 API、壁纸引擎、悬浮组件。
- **RTX 5060（Blackwell sm_120）**：CUDA 12.8 加速本地语音模型推理（CosyVoice 训练配方要求 torch cu128 + bf16；onnx 强制 CPU）。

### 2.4 模型与外部服务

- **云端 LLM**：DeepSeek 系列（deepseek-v4-flash/pro 等）经 tokenhub.tencentmaas.com 代理；支持多供应商（models 适配器 provider），支持 thinking 模型（Kimi 等，工具续轮须携带 reasoning_content）。
- **本地 TTS**：Qwen3-TTS-12Hz-1.7B-VoiceDesign（4bit NF4 量化约 2GB 显存）；CosyVoice2（instruct2 需基底参考音）。
- **本地 STT**：Silero VAD + Zipformer ASR + 关键词唤醒（KWS），16kHz 单声道，独立 venv 子进程，优雅降级。
- **向量检索**：对话缝合引擎用 bge-small-zh INT8 ONNX 语义检索；心智核心语义记忆用 chroma 库（live 模式）。
- **Git 远端**：github.com:Dawn23410/12345.git（早期克隆源）。

---

## 第三章 功能全景（按模块）

### 3.1 对话与 Agent（chat + agent）

对话服务（palm/services/chat/）承载会话流程：chat_service、conversation_store（会话存取）、hub（聚合）、engine（引擎选择）、build_corpus（语料构建）。Agent 框架（palm/services/agent/）提供：
- 规划引擎 plan_engine.py：先计划后执行，失败自动重规划；
- ReAct 循环 react_parser.py + agent_react_mixin.py；
- 原生 FC 执行 _native_execution.py + native_runner.py + native_parse.py；
- 工具基座 tool_base.py + tool_matcher.py + tools/（100+ 工具）；
- 人格注入 persona.py + agent_prompt_mixin.py + prompt_templates.py；
- 代码守卫 code_guard.py、完成闸门 completion_gate.py、提问中枢 question_hub.py、轨迹 trace.py、协议 protocols.py、schema 校验 schemas.py；
- 双引擎 dual/（本地自研 + 委托引擎，后清理但目录保留）。

### 3.2 角色扮演与好感度（roleplay）

palm/domain/roleplay/ 提供：character（角色卡）、persona（人格）、affinity_engine + affinity_store（好感度引擎与存储）、affection（好感度数值）、dynamics_engine（角色动态机制）、pollution_guard（语气污染防护）、state（状态）、xp（经验）、game_service（游戏结算）、import_skill（Markdown 技能导入）。好感度采用官方统一规则 10 级分层 + 双线结构（基准线 base + 动态线 dynamics），增速按真实当前档位约束。

### 3.3 记忆（memory）

palm/domain/memory/ 提供分层记忆：core_memory（核心记忆）、archived_memory（归档记忆）、vector_memory（向量记忆）、token_budget（token 预算）、memory_writer（记忆写入）、weights/（记忆权重）。记忆只存事实不存语气（全局污染检测）。

### 3.4 规划（planning）

palm/domain/planning/：planner.py + schemas.py，规划引擎的领域模型。

### 3.5 自主进化（evolution）

palm/domain/evolution/：proactive（主动推送）、idle_orchestrator（闲置编排）、offline_digest（离线摘要/每日简报）、habit_engine（习惯引擎）、fallback_engine（兜底引擎）、background_tasks（后台任务）。palm/services/evolution/：registry、loader、observer、gate、slot_store、skill_registry、_injection、_io、schemas——进化系统的服务化注册与观察者模式。

### 3.6 语音（audio）

四引擎统一门面：GSV（实时播音员）、CosyVoice2（音色设计师）、GPT-SoVITS（tts_sovits 自包含运行时）、STT（语音识别）。全部经统一 facade 暴露；Qwen3-TTS 作为可选本地合成通道（.env 配置 QWEN_TTS_API_URL/AUTO_LAUNCH/MODEL_DIR/QUANTIZE）。

### 3.7 GUI 自动化（gui）

palm/adapters/gui/automation_orchestrator.py 为对外单一入口 automate(software_id, intent)。内部链：Atlas 静态认知（gui_atlas）、转移规律（gui_transitions）、坐标记忆（gui_coord_memory，EMA samples<2 不可信）、执行器 L0-L3 四级容错 + LM 兜底；辅助模式 = Win 辅助功能语义（assistive_mode set/is/ensure_off，须先 CoInitializeEx(STA) 且在 uiautomation import 前）。执行器档位：档1 UIA / 档2 OCR / 档3 LLM 兜底 / 档4 VLC，档3/4 fail-closed。

### 3.8 游戏化（game）

palm/domain/roleplay/game_service.py：星砂货币、道具、经验、好感度联动。award_chat_xp（聊天经验）、award_plan_xp（规划经验）、has_item/unlock_item/purchase_item（道具）。等级 10 阶 × 100 级全局用户级（0 阶每级 1000 Exp，后续每级 = 基础值 × 阶数），每日任务（聊天 1/10 次、触发自动规划等），特殊对局来源（五子棋 vs 角色按分数难度）。

### 3.9 存储与安全（storage + crypto + safety）

- storage 适配器（palm/adapters/storage/pool.py）：文件池 store_file/read_file_content/delete_file/get_store/load_app_settings/find_config_file。
- crypto 适配器（palm/adapters/crypto/）：keystore（指纹采集 boot）、operations（encrypt_data/decrypt_data），指纹采集失败仅置禁用不阻断装配。
- safety：文件级保险库 vault（palm/_core/redundancy/vault.py）+ 回收站 recycle.py，删除拦截兜底防御；权限引擎（palm/_core/permission.py）所有敏感能力须经用户授权；裁决内核 guardrail 5 档。

### 3.10 调度与后台（scheduler + ops）

palm/services/ops/：engine（调度引擎）、cron.py、mode_resolver（模式解析）、game_detector（游戏对局检测）、_settings、store、token_ledger、token_usage。支持定时任务、每日简报、闲置自主推测。

### 3.11 心智核心（mentalcore）

独立 Python 库：Boss（心智魔方，纯聊天不碰工具）+ Worker（外骨骼，只干活无性格）异步双链；`||EXO||{goal,context}||END||` 协议；18 条控制码（五域，单值/单字段颗粒度）；Reflex-Cortex 双模 + IntentRouter 四意图；5 个外骨骼小魔方（工具/沙箱/计划/通信/记忆）+ 安全三拆分；GSV TTS 全链路约 2.3 秒。

---

## 第四章 目录结构总览（当前工作区）

```
C:/Users/24459/Desktop/P.A.L.M/
├── .env / .env.example        # 环境配置（服务端口/语音/STT/模型）
├── .gitignore / .gitattributes
├── .workbuddy/                # 工作区助手记忆与项目数据
├── archive/                   # 归档（不入库）：mentalcore_frontend_20260820、
│                              #   workshop_mentalcore_20260819、保留_不可恢复_20260818
├── docs/                      # 历史文档（已过期，仅存档）
├── frontend/                  # 前端（12 html + ui 共享基础）
├── mental_core_demo/          # 心智核心演示
├── mentalcore/                # 心智核心库（源码 + 基准测试 + 报告）
├── mentalcore_data/           # 心智核心运行数据
├── palm/                      # 核心自洽 Python 库（终极架构）
│   ├── _core/                 # 基础设施：容器/配置/裁决/网卡/事件/权限/冗余/...
│   ├── adapters/              # 适配器：crypto/display/gui/io/model/storage
│   ├── bootstrap/             # 装配层：app.py（唯一注册点）
│   ├── domain/                # 领域层：evolution/memory/planning/roleplay
│   ├── ports/                 # 契约层：15 个 Port ABC
│   └── services/              # 服务层：agent/chat/evolution/ops
├── P.A.L.M_砖块/              # 旧砖块体系残留（仅"网卡"目录）
├── --selftest/                # 自测
└── nul                        # 历史遗留空文件
```

### 4.1 palm/_core 基础设施逐文件说明

- container.py：服务容器（Container + ServiceHandle.capability），业务经 `container.get(名).capability(键)`，缺失归一 None。
- config.py：配置加载。
- emotion.py：情绪模型（五因子，E_enc 仅 v≥0）。
- eventbus.py：事件总线。
- gateway.py：网关（承接旧 registry 迁移，dual/tools/world_model_cache 等 17 文件收敛至此）。
- guardrail/：裁决内核 engine.py + rules.py，5 档，AI 档无回调 fail-closed deny。
- housekeeping.py：后台保洁。
- interop.py：互操作。
- logging.py：日志。
- net/：网卡门面，唯一出网出口，fail-closed。
- paths.py：路径解析。
- permission.py：权限引擎（敏感能力须授权）。
- redundancy/：recycle.py（回收站）+ vault.py（文件级保险库）。
- schemas/：chat.py 等 schema。
- security.py：安全工具。
- token_estimate.py：token 估算。
- tooling.py：工具基础设施。
- transport.py：传输层（控制码/事件/协议）。
- watchdog.py：看门狗。

### 4.2 15 个 Port 契约

ports/ports/ 下共 15 个 Port ABC：agent_port、audio_port、crypto_port、device_port、display_port、guard_port、gui_port、memory_port、model_port、ops_port、persist_port、storage_port、sys_port、tool_port、ui_port。所有模块依赖方向：ports ← domain/services/adapters ← bootstrap；依赖单向，越层即 lint 报错。

---

## 第五章 运行方式

### 5.1 环境准备

- Python 3.11（系统）/ 3.13（隔离）。
- 依赖安装：历史脚本 dev.py/dev.bat 支持"依赖幂等安装 + dev 实时日志"（dev.bat 注释用 rem 而非 ::，避免批处理解析踩坑；换行须 CRLF，LF 会被 cmd 误当命令执行）。
- 语音引擎独立 venv：venv_cosyvoice（CosyVoice）、venv_gsv（GPT-SoVITS）、venv_runtime（主运行时）。

### 5.2 启动

后端 FastAPI 监听 127.0.0.1:8005（.env 默认 8000，实际部署 8005），前端 Vite 5173。装配入口 `palm.bootstrap.app.build_app()` 幂等注册 14 服务。桌面壳 pywebview 加载前端。

### 5.3 配置

.env.example 记录的关键配置：HOST/PORT、CORS_ALLOW_ORIGINS、QWEN_TTS_API_URL/AUTO_LAUNCH/MODEL_DIR/MODEL/QUANTIZE/VOICES_DIR、STT_ENABLED/AUTO_LAUNCH/API_URL/SAMPLE_RATE/VAD/ASR/KWS 模型路径等。语音与 STT 均为可选，未配置时优雅降级。

---

## 第六章 与"曾经归档内容"的关系

备份目录 D:/PALM_backup_20260818 是 2026-08-18 归档的项目快照，包含：

- git_broken_20260818/：早期 git 仓库（.git 目录，因对象损坏称 broken，reflog 84 条完整保留，是本系列发展路径章节的一手素材）。
- Data/：运行数据与旧砖块素材（76 项），含 brick_inventory.json（24 砖清单）、bricks/、characters/、skills/、tools/、对话记录/、配置文件/、adjudicator/（裁决）、agent_artifacts/、agent_habits/、agent_memory/、gui_atlas/、gui_coord_memory/、gui_metrics/、gui_routes/、gui_transitions/、observations/、permissions.json、game_state.json、schedules.json、settings.json、storage_pool/、swaps/、threat_data.json、CosyVoice_src/、cosyvoice_voices/、stt_models/、qwen_tts_voicedesign/、wheels/ 等。
- venv_cosyvoice/、venv_gsv/、venv_runtime/：三个隔离虚拟环境。
- 4 个备份日志（backup_cosy/gsv/runtime/data.log）。

当前工作区是归档后的"终极架构"演进结果：旧砖块（24 砖/主板/总线）已归档至 archive/，功能收敛进 palm/_core/ 与 palm 库分层；mentalcore 前端与控制台已归档（archive/mentalcore_frontend_20260820），对外仅 MentalCoreSlotPort 四方法。

---

## 第七章 质量与工程规范

项目执行严格的代码底线（用户级铁律，贯穿全部代码）：

1. 最小修改原则：只改需求直接指向的代码。
2. 不修改测试文件。
3. 单一职责：函数 ≤ 50 行、文件 ≤ 500 行、一个函数只做一件事。
4. 业务意图命名：布尔值 is/has/should 开头、函数动词 + 业务名词、禁泛词变量名。
5. 注释仅写 WHY，不写是什么；全程中文（标识符保留英文）。
6. 生成后自查清单与重复辅助函数合并。

历史 commit 显示这些规范被显式落地："重构：全面落实代码合规五条底线（函数≤50行/文件≤500行/单一职责）"。

## 第八章 文档系列导览

本文档是系列第 0 篇（总览），完整系列共 7 篇：

- 00 项目总览与产品说明（本篇）
- 01 发展路径与版本演进史（基于 84 条 git 提交重建）
- 02 AI 与个人贡献分析（分阶段/分模块贡献矩阵）
- 03 系统架构白皮书（终极架构：ports/domain/services/adapters/bootstrap + _core）
- 04 模块深度解析（复刻级：逐模块实现细节与数据流）
- 05 心智核心与外骨骼深度解析（mentalcore）
- 06 从零复刻指南（分步操作手册）

下一篇进入发展路径与版本演进史。



# P.A.L.M 项目总览与产品说明（续篇：数据目录/前端/测试/FAQ）

> 本篇为《P.A.L.M 项目总览与产品说明》的续篇，承接第一篇。本篇覆盖：运行数据目录逐项详解、前端页面清单、测试与基准体系、常见问题解答、项目健康度与已知边界。所有信息来自真实代码与运行数据。

---

## 第九章 运行数据目录详解（对应备份 Data/ 与工作区 mentalcore_data/）

### 9.1 归档 Data/ 目录逐项说明

备份中 Data/ 目录共 76 项，是项目运行期产生的全部数据与诊断素材，按用途分七类：

**（一）核心状态文件（JSON）**
- brick_inventory.json：24 砖清单（旧主板架构时代），每条含 name/title/description/bus_type/capabilities/routes/dir。bus_type 为"主板总线隐喻"：cpu（agent）、pcie（automation/display/models/parse）、ram（usage/affinity/game/monitor）、sata（conversations/memory）、chip（storage/crypto）、board（safety/self_evolution/scheduler/chat/settings/file/evolution/roleplay）。这是理解"旧砖块-总线认知"的第一手材料。
- permissions.json：权限引擎持久化（敏感能力授权记录）。
- game_state.json：游戏状态（星砂、等级、道具、好感度）。
- schedules.json：定时任务调度。
- settings.json：应用设置（与 app_settings 联动）。
- pool.json 及 .tmp：存储池状态（含 cleanup_bak 备份）。
- threat_data.json：安全威胁数据。
- agent_search_result.txt：Agent 搜索结果落盘。

**（二）记忆与行为数据**
- agent_memory/、agent_habits/（习惯）、agent_artifacts/（产物）、observations/（观察）、agent_traces.jsonl（运行轨迹）。
- 对话记录/：真实对话语料（缝合引擎的语料来源）。
- 配置文件/：应用配置。

**（三）GUI 自动化数据**
- gui_atlas/：静态认知（Atlas）。
- gui_transitions/：转移规律。
- gui_coord_memory/：坐标记忆（EMA）。
- gui_metrics/：执行指标。
- gui_routes/：路由。

**（四）语音与音频**
- CosyVoice_src/：CosyVoice 源码（vendored）。
- cosyvoice_voices/：音色。
- stt_models/：STT 模型（vad/kws/asr 子目录）。
- qwen_tts_voicedesign/：Qwen3-TTS VoiceDesign 模型（本地方案 B）。
- stt_ref_audio.wav、gsv_test_out.wav、gsv_verify.wav、tts_reply_audio.ogg：测试音频产物。
- gen_mengyao_voice.py + gen_mengyao_full.log：梦瑶音色生成脚本与日志。
- asr_verify.py、cosy_smoke_test.py：语音链路验证脚本。

**（五）诊断与临时脚本（下划线前缀，非生产代码）**
- _cmp_soundcard.py、_diag_audio.py、_diag_bf16.py、_diag_bf16b.py、_diag_cpu.py、_diag_text.py、_extract_cu128.py、_move_disabled.py、_ruamel_fix.bak、_whisper_src.bak、_matcha_src.bak、_crypto_bak、_cleanup_bak_*：Blackwell sm_120 兼容性诊断与备份。

**（六）旧体系目录**
- bricks/：旧砖块源码。
- skills/：技能（含 Markdown 人格 Skill）。
- tools/：旧工具集。
- characters/：角色卡（含梦瑶）。
- adjudicator/：裁决器。
- swaps/、storage_pool/：存储交换与池。
- wheels/：本地 wheel 包。
- diag/：诊断输出。

**（七）日志与运行产物**
- cosy_install_torch.log / cosy_install_torch_local.log：torch cu128 安装日志。
- cosy_download_model.log + cosy_download_model.py：模型下载。
- tts_sovits_runtime.log(.err)：GSV 运行时日志。
- gsv_pid.txt：GSV 进程号。

### 9.2 心智核心数据（工作区 mentalcore_data/ 与 mentalcore/ 内嵌数据）

- mentalcore_data/：心智核心运行数据（live 模式加密落盘；mock 模式零落盘）。
- mentalcore/ 内 benchmark 数据：bench100_chroma/、bench100_data/、bench50_live_chroma/、bench50_live_data/、bench50_mock_chroma/、bench50_mock_data/、chat_100_chroma/、chat_100_data/、smoke_chroma/、smoke_data/、ui_smoke_chroma/、ui_smoke_data/：Chroma 向量库与对话数据快照，用于 50 轮/100 轮对话基准（mock 对照 live）。
- prompt缓存轨迹_20260820.csv/json/comp/win6：prompt 缓存轨迹探针数据（窗口 6 对比实验）。

### 9.3 数据安全约定

- live（persist=True）：记忆加密落盘（crypto_provider + secure_config）。
- mock（persist=False + sem=None）：只聊不记，不建 chroma 库，零落盘（测试/演示模式）。
- 存储收一块砖：quota（配额）/lifecycle（生命周期）/audit（审计）/health（健康）统一管理。

---

## 第十章 前端页面清单（12 HTML + ui 共享）

当前前端采用"每界面一文件"策略，共 12 个 HTML + ui/ 共享基础（历史 commit "a67fd78 前端改为每界面一文件（12 html + ui 共享基础）"、"8a69056 P4 前端拆分完成：shell.html + ui/ 组件 + 11 screens（原生 ES Modules，去主板隐喻界面）"）。

- shell.html：外壳（承载各 screen）。
- 对话界面：聊天主界面（思维链时间线 + 工具调用交错渲染、运行中实时计时、ask_user 交互）。
- 系统总览中枢：砖块调度与运行状态总览（commit "b99bda4 完善砖块调度与前端：新增系统总览中枢"）。
- 存储面板：存储使用情况（quota/lifecycle/audit/health）。
- 用量面板：Token 用量明细（provider 落库、估算量不入账、明细页不再空白）。
- 商城面板：星砂购买、道具（commit "65556501 前端商城面板与星砂购买打通好感度显示"）。
- 保险库面板：文件级保险库（删除拦截兜底）。
- 设置界面：应用设置（保存须防 Windows 文件锁竞争与 CORS 误报）。
- 其余 screen：历史 commit 提及的登录窗（CodebuddyLoginOverlay，已删）、部件（widget）面板、规划视图等。

前端与后端经 API 交互（端点经 PALM 桥接层封装 window.pywebview.api 调用链路）。桌面部件系统（时间类组件如 glass_clock）经桥接层取数。

---

## 第十一章 测试与基准体系

### 11.1 分层测试

- 单元测试：14 砖块鉴权/日志/异常/单元测试/路径硬编码全面修复后，单元测试 7/8（曾有 1 项未通过待排查）。
- 编译与冒烟测试：全砖块编译通过 + 冒烟测试通过。
- e2e 测试：全砖块 e2e 无业务 bug（权限引擎 Phase 0-4 完成）；e2e 端口 8012。
- 端点全量扫描：修复 5 处 HTTP 端点未捕获崩溃后，全量链路扫描 163 端点无 500（仅依赖缺失降级 503）。
- GUI 自动化测试隔离：GUI 存储落盘 Data/gui_*，测试须 patch _storage_cap 为 lambda:None。

### 11.2 基准与评测

- P6 评测闭环：真实模型端到端评测脚本（项目 HTTP API 驱动），评测切云端 tokenhub；评测客户端自动应答（ask_user 事件自动应答）。
- 心智核心基准：50 轮对照测试（mock vs live）、100 轮对话实测、chat_100、full_e2e、prompt 缓存轨迹探针（窗口对比）、基准报告_100次对话实测.md、基准报告_图表.html、50轮对照测试报告.md、全流程验收报告_20260820.md、生产就绪度评估_心智魔方.md、安全审计与红队报告_20260820.md。
- 方法论要求：算法级对照（共享合成语料 + 导入产线代码）、诚实对比、显式标注伪像、不包装数据；性能优化须真实定量 benchmark 验证。

### 11.3 自测入口

- 心智核心：`python -m mentalcore.selftest`（临时目录隔离）；外骨骼 `python -m mentalcore.exo.selftest`（4 测全过，mock 零落盘）。

---

## 第十二章 常见问题解答（FAQ）

**Q1：为什么 docs/ 目录文档不可信？**
因为项目演进极快，docs 已过期（如旧主板/砖块/总线文档与终极架构不符）。本系列全部基于当前代码与归档 git 历史从零重建。

**Q2：旧 24 砖体系与当前 14 服务什么关系？**
24 砖是"主板 + 砖块 + 总线"时代（bus_type：cpu/pcie/ram/sata/chip/board）的产物，经"终极架构"重构：放弃主板/砖块/总线认知，改服务容器（container.get(名).capability(键)），功能拆最小颗粒度入 palm/ 库（24 砖全拆），旧体系归档。当前装配 14 服务（storage/settings/crypto/models/gui/usage/usage_ledger/scheduler/conversations/game/affinity/roleplay/memory/evolution/agent）。

**Q3：双引擎（本地自研 + 委托 CodeBuddy）还在吗？**
已清理。历史曾实现"双系统架构（本地自研 + 委托 CodeBuddy）+ 登录窗 + Token 计量修复"，随后多轮 commit 移除 SDK 引擎相关代码与前端 UI（CodebuddyLoginOverlay 孤儿组件删除）。当前仅保留本地自研引擎（services/agent/dual/ 目录残留但不参与装配）。

**Q4：语音引擎如何选择？**
统一 facade 下四引擎：GSV（实时播音员）、CosyVoice2（音色设计师，instruct2 需基底参考音）、GPT-SoVITS（自包含完整 GSV，内置 runtime 与模型，启动即拉起，解包引擎改 7-Zip）、STT（语音识别）。Qwen3-TTS 为可选本地合成通道（VoiceDesign 模型文本造音色）。

**Q5：GUI 自动化安全边界？**
执行器四级容错（L0-L3 + LM），档位 1 UIA / 档2 OCR / 档3 LLM 兜底（NullLlmDecider）/ 档4 VLC；档3/4 fail-closed。辅助模式须先 CoInitializeEx(STA) 且 uiautomation import 前。

**Q6：为什么 git 历史只有 8 条？**
2026-08-18 仓库重建（f1b9acb/9e87f93 "仓库重建——全量源码基线"），早期 84 条提交的 reflog 保留在备份 D:/PALM_backup_20260818/git_broken_20260818/。

**Q7：本机删除文件为何要用特殊方式？**
本机 rm 被 safe-delete 守卫拦截；脚本删除用 os.remove；批量删除触发确认；生成文件用 Write 工具（bash 内 \n 会被 MSYS 转字面 /n）。

**Q8：RTX 5060 上跑本地模型注意什么？**
Blackwell sm_120 需 CUDA 12.8（torch cu128）；推理精度必须 bf16（torch.amp.autocast("cuda", dtype=bfloat16)）；音频绕 torchcodec 用裸 soundfile；onnx 强制 CPU；transformers 5.x KV-cache 掩码坍塌需 _patch_kv_cache_mask；wetext==0.0.4 钉版。

---

## 第十三章 项目健康度与已知边界

### 13.1 健康度

- 代码合规：函数 ≤ 50 行 / 文件 ≤ 500 行约束在全库执行（历史 commit 显式落地）。
- 依赖方向：ports ← domain/services/adapters ← bootstrap 单向，越层 lint 报错。
- 安全链：H1-H4 / M5 / M7 不变；裁决内核 fail-closed；网卡门面唯一出网出口。
- 容错：14 服务注册各自 try/except 降级（如 crypto 指纹采集失败仅置禁用）。

### 13.2 已知边界与遗留

- 单元测试 7/8（曾有一项未通过，未在本系列范围内修复）。
- GUI 自动化坐标记忆 EMA samples < 2 时不可信。
- 对话缝合引擎弱召回（top1 < 0.7）加情感/意图门控；无匹配时诚实 + 建议问 LLM。
- mentalcore 前端/控制台/launcher/cli 已归档（archive/mentalcore_frontend_20260820），对外仅 MentalCoreSlotPort 四方法（send_message/receive/control/get_model_info）。
- 旧砖块目录 P.A.L.M_砖块/ 仅残留"网卡"子目录，其余已归档。
- 根目录 nul 为空文件（历史遗留）。
- 备份目录中 git 仓库对象损坏（bad object refs/heads/main），仅 reflog 与部分对象可用；本系列发展路径章节基于 reflog 提交消息重建，个别提交的工作区内容无法恢复，已标注。

### 13.3 演进方向（来自路线图与近期 commit）

- P0-P6 七阶段路线图（P0 基础 / P1 架构 / P2 工具健壮性 / P3 反思自检 / P4 上下文压缩 / P5 结构化输出与轨迹 / P6 评测闭环）已执行，最终落地"终极架构"。
- agent 砖块对标 LangChain / OpenAI Agents / Claude Agent SDK 持续升级。
- 好感度砖块解耦重构（与角色扮演解绑）为下一阶段议题。
- 本地 Qwen2.5-TTS 方案 B 已部署（VoiceDesign 1.7B 4bit）。

---

## 第十四章 结语

P.A.L.M 从 2026 年 7 月底的一个克隆仓库起步，历经 84+ 次提交、两次大重构（砖块-总线体系 → 服务容器体系；旧前端 → 12 页原生 ES Modules），最终形成"palm/ 核心库 + mentalcore/ 心智核心 + 12 页前端 + 多语音引擎 + 游戏生态 + 自主进化"的完整桌面 AI 管家系统。本系列文档以 1:1 复刻为颗粒度，从代码与 git 历史出发重建全部认知。下一篇《发展路径与版本演进史》将以 84 条提交为骨架展开完整时间线。



# P.A.L.M 项目总览与产品说明（深度扩充一：运行数据/前端/配置逐项详解）

> 本部分为《P.A.L.M 项目总览与产品说明》的深度扩充，逐项展开备份 Data/ 目录、前端 12 页、配置项与运行时数据模型。所有内容来自真实文件（备份 Data/ 与当前工作区）。

---

## 扩充章 A：备份 Data/ 目录 76 项全量详解

归档备份 D:/PALM_backup_20260818/Data/ 共 76 项，是 2026-08-18 归档时点项目运行数据的完整快照。以下逐项说明（按首字母序展开实际内容）：

### A.1 诊断与临时脚本（下划线前缀，共 12 项）

1. **_cleanup_bak_20260801_152446 / _153136 / _153208 / _153431 / _153621**：2026-08-01 五次清理任务的备份目录。当日是"代码合规五条底线"重构日，这五个备份对应清理过程中的五个时间点（15:24、15:31、15:32、15:34、15:36），说明清理是分批进行的，每批清理前先备份。
2. **_cmp_soundcard.py**：声卡对比脚本——对比多块声卡/多音频设备的输出（语音引擎选型期产物）。
3. **_crypto_bak**：加密模块备份（crypto 重构前的旧实现）。
4. **_diag_audio.py / _diag_bf16.py / _diag_bf16b.py / _diag_cpu.py / _diag_text.py**：五份诊断脚本，分别诊断音频链路、BF16 精度（两个版本 b）、CPU 推理、文本链路。这些是 Blackwell（RTX 5060 sm_120）兼容性排障的产物——bf16 诊断两个版本说明排查经历了迭代。
5. **_extract_cu128.py**：CUDA 12.8 提取脚本——从安装包提取 cu128 版本 torch 组件（Blackwell 必需）。
6. **_matcha_src.bak / _ruamel_fix.bak / _whisper_src.bak**：三份源码备份——matcha（CosyVoice 文本前端依赖）、ruamel（yaml 库修复）、whisper（STT 候选引擎）。ruamel_fix 说明曾修复该库的兼容问题。
7. **_move_disabled.py**：移动禁用脚本（迁移未授权禁用模块用，对应"沙箱 run_isolation 已归档未授权禁用"）。

### A.2 语音引擎素材（CosyVoice 专项，共 11 项）

8. **CosyVoice_src/**：CosyVoice 源码（vendored 进 site-packages 的源码副本）。
9. **cosyvoice_voices/**：已合成/采集的音色文件（梦瑶音色的语音样本）。
10. **cosy_download_model.log + cosy_download_model.py**：模型下载脚本与日志（下载 CosyVoice 预训练模型）。
11. **cosy_install_torch.log / cosy_install_torch_local.log**：torch 安装日志两份——一份走网络安装、一份走本地源（本地 wheel），体现"安装卡住须主动诊断修复"的协作规范。
12. **cosy_smoke_test.py**：CosyVoice 冒烟测试脚本。
13. **gen_mengyao_voice.py + gen_mengyao_full.log**：梦瑶音色生成脚本与完整日志——用 CosyVoice 为"梦瑶"角色合成专属音色。
14. **stt_ref_audio.wav**：STT 参考音频。
15. **gsv_test_out.wav / gsv_verify.wav**：GSV 测试输出与验证音频。
16. **tts_reply_audio.ogg**：TTS 回复音频产物（ogg 格式，Web 播放友好）。

### A.3 STT 与本地模型（3 项）

17. **stt_models/**：STT 模型目录（vad/kws/asr 三个子目录——Silero VAD、关键词唤醒、Zipformer ASR）。
18. **qwen_tts_voicedesign/**：Qwen3-TTS-12Hz-1.7B-VoiceDesign 模型（本地方案 B，4bit NF4 量化）。

### A.4 核心状态 JSON（8 项）

19. **brick_inventory.json**：24 砖清单（旧体系），每条含 name/title/description/bus_type/capabilities/routes/dir。**这是理解"旧砖块-总线认知"的关键档案**。
20. **permissions.json**：权限引擎持久化——敏感能力授权记录（能力/授权状态/作用域）。
21. **game_state.json**：游戏状态——经验/连登/每日任务/道具/星砂货币/购买历史。
22. **schedules.json**：定时任务调度。
23. **settings.json**：应用设置全量（见扩充章 C）。
24. **pool.json + pool.json.*.tmp（5 个）**：存储池状态 + 临时文件（多进程写入痕迹：12584/19692/26968/27476 四个 pid 的 tmp）。
25. **pool.json.cleanup_bak**：池清理备份。
26. **threat_data.json**：安全威胁数据（裁决命中/攻击尝试记录）。

### A.5 记忆与行为数据（6 项）

27. **agent_memory/**：Agent 长期记忆。
28. **agent_habits/**：习惯引擎数据（用户习惯观察）。
29. **agent_artifacts/**：Agent 产物（生成的文件/报告）。
30. **observations/**：观察记录（进化引擎输入）。
31. **agent_traces.jsonl**：Agent 运行轨迹（每行一次执行：计划/工具/结果）。
32. **agent_search_result.txt**：Agent 搜索结果落盘。

### A.6 GUI 自动化数据（5 项）

33. **gui_atlas/**：Atlas 静态认知（界面元素静态地图）。
34. **gui_transitions/**：界面转移规律。
35. **gui_coord_memory/**：坐标记忆（EMA 平滑）。
36. **gui_metrics/**：执行指标（成功率/耗时）。
37. **gui_routes/**：GUI 路由表。

### A.7 角色与技能（4 项）

38. **characters/mengyao.json**：梦瑶角色卡（JSON 格式，社区规范）。
39. **skills/desktop-visual-operator**：桌面视觉操作技能（GUI 技能包）。
40. **skills/gui-atlas-planner**：GUI Atlas 规划技能。
41. **adjudicator/**：裁决器（旧裁决引擎数据）。

### A.8 旧体系目录（6 项）

42. **bricks/**：旧砖块源码（仅剩 _validation_virtual_brick、tts_sovits 两个子目录——其余已外迁）。
43. **tools/**：旧工具集。
44. **storage_pool/**：存储池。
45. **swaps/**：交换区。
46. **wheels/**：本地 wheel 包（torch cu128 等离线安装源）。
47. **diag/**：诊断输出目录。

### A.9 对话与配置（3 项）

48. **对话记录/**：7 个会话 JSON（0288a24a0f25.json 等十六进制 id）——真实对话语料（缝合引擎语料来源）。
49. **配置文件/**：应用配置。
50. **tts_sovits_runtime.log(.err)**：GSV 运行时日志与错误日志。
51. **gsv_pid.txt**：GSV 进程号。

> 以上按 76 项的实际构成展开。复刻时这些目录的**命名与布局**应保持一致（paths.py 依赖约定），内容按运行时重建。

---

## 扩充章 B：前端 12 页逐页详解

当前工作区 frontend/ 实际文件清单（2026-08-19 每界面一文件策略后）：

| 页面 | 文件名 | 职责 |
|---|---|---|
| 外壳 | index.html | 入口/外壳（shell） |
| 对话 | chat.html | 聊天主界面：SSE 流式、思维链时间线、工具调用实时计时、ask_user 应答 |
| 角色 | characters.html | 角色卡管理：列表/查看/导入（Markdown 技能）/删除（级联） |
| 文件 | files.html | 文件管理（存储池浏览） |
| 游戏 | game.html | 游戏生态：星砂/等级/道具/每日任务/五子棋对局 |
| MCP | mcp.html | MCP 能力管理（热插拔/插件发现） |
| 记忆 | memory.html | 记忆面板：核心记忆/向量检索/归档 |
| 监控 | monitor.html | 运行监控：服务状态/看门狗/裁决审计 |
| 总览 | overview.html | 系统总览中枢：14 服务/砖块调度 |
| 调度 | scheduler.html | 定时任务：每日简报/闲置推测/保洁 |
| 设置 | settings.html | 应用设置：模型/语音/STT/角色/游戏/外观 |
| 用量 | usage.html | Token 用量明细（provider 口径） |

共享基础 ui/：
- api.js：后端 API 封装（fetch + SSE）。
- base.css：基础样式。
- chart.js：图表（用量/监控可视化）。
- dom.js：DOM 工具。
- theme.css：主题（明/暗，settings.json theme 字段联动）。

**桥接层**：pywebview 桌面壳中 window.pywebview.api 封装后端调用；桌面部件（widget）时间组件（glass_clock 等）经桥接层取数（曾通过 PALM 桥接层定位 window.pywebview.api 调用链路排查数据获取 bug）。

---

## 扩充章 C：settings.json 配置项逐项详解（真实结构）

备份 settings.json 实录（api_key 已脱敏）：

| 字段 | 值（示例） | 说明 |
|---|---|---|
| apiUrl | http://localhost:8000 | 后端地址 |
| windowSize | "" | 窗口尺寸 |
| background | black | 背景 |
| maskBlur | 8 | 遮罩模糊 |
| fontSize | 16 | 字号 |
| agentWebSearch | true | Agent 联网搜索开关 |
| agentDeepThink | false | 深度思考开关 |
| agentCharacterId | "" | 当前角色 id（空=默认） |
| agentToolMode | native | 工具模式（原生 FC） |
| agentPlanningMode | always | 规划模式（始终） |
| agentAutoFilterTools | true | 工具自动过滤 |
| agentStorageAutoCleanup | false | 存储自动清理 |
| runMode | max | 运行模式（max/min/mock） |
| autonomyLevel | full | 自主等级（full/...） |
| idleMinutes | 15 | 闲置判定分钟数 |
| theme | light | 主题 |
| language | zh-CN | 语言 |
| runModeLocked | false | 运行模式锁定 |
| dailyTokenLimit | 5000000 | 每日 Token 限额 |
| monthlyTokenLimit | 50000000 | 每月 Token 限额 |
| flashModel | kimi-k2.5 | 快模型 |
| proModel | kimi-k2.5 | 专业模型 |
| model | kimi-k2.5 | 默认模型 |
| customProviders | [...] | 自定义供应商（tokenhub：base_url=https://tokenhub.tencentmaas.com/v1、mode=openai、models=[glm-5-turbo, minimax-m2.7, glm-5, qwen3.5-plus, kimi-k2.5, kimi-k2.7-code, mimo-v2.5-pro]） |

**复刻注意**：
1. 供应商支持多实例（customProviders 数组），模型列表随供应商声明。
2. tokenhub 为 OpenAI 兼容模式（mode=openai），端点 /v1。
3. 运行模式 runMode 与 mode_resolver 联动（max=全功能、mock=禁用 Agent 执行）。
4. autonomyLevel 与进化引擎 gate 联动（full=完全自主）。
5. 保存设置须处理 Windows 文件锁竞争（历史修复项）。

---

## 扩充章 D：game_state.json 结构详解（真实结构）

备份 game_state.json 实录：

| 字段 | 值（示例） | 说明 |
|---|---|---|
| total_exp | 2393 | 总经验 |
| streak_days | 1 | 连登天数 |
| last_checkin_date | "" | 上次签到日期 |
| last_reset_date | 2026-08-10 | 上次每日重置日期 |
| daily_chat_count | 56 | 当日聊天次数 |
| daily_plan_count | 0 | 当日规划次数 |
| daily_tasks_done | [chat_once, plan_once, chat_ten] | 已完成的每日任务 |
| daily_task_exp_earned | 2000 | 每日任务经验收益 |
| unlocked_items | [affinity_display] | 已解锁道具（affinity_display=好感度显示后门） |
| currency | 40 | 星砂货币余额 |
| currency_earned_total | 40 | 星砂累计获得 |
| daily_currency_earned | 40 | 当日星砂获得 |
| purchase_history | [] | 购买历史 |

**解读**：
- 每日任务：chat_once（聊 1 次）、plan_once（触发 1 次自动规划）、chat_ten（聊 10 次）。
- 道具"affinity_display"对应历史提交"道具显示后门"——解锁后界面显示好感度数值。
- 星砂货币：任务/对局获得，商城消费（购买道具）。
- last_reset_date 每日重置逻辑：跨天时清空 daily_* 计数并重算连登。



# P.A.L.M 项目总览与产品说明（深度扩充二：API/事件/工具/术语）

> 承接扩充章 A-D。本部分覆盖：后端 API 端点体系、事件类型全清单、工具集详解、环境变量全量、项目术语表。

---

## 扩充章 E：后端 API 端点体系

基于历史审计（163 端点全量扫描无 500）与路由证据，端点按领域组织（具体路径以源码为准，此处给出领域覆盖）：

### E.1 对话与 Agent（/api/chat 系）

- 对话流式：POST /api/chat（SSE 流式响应：text/thought/tool_call/ask_user/verdict 事件）。
- 工具列表：GET /api/tools；工具注册：POST /api/tools。
- ask 应答：POST /api/ask-response（携带 question_id）。
- 运行：POST /api/run（Agent 单次运行）。
- 事件流：GET /api/events（SSE 长连接）。
- 规划：POST /api/plan（规划引擎触发）。

### E.2 角色与好感度（/api/characters 系）

- 角色列表：GET /api/characters。
- 角色详情：GET /api/characters/{character_id}。
- 角色创建/更新：POST /api/characters。
- 角色导入（Markdown 技能）：POST /api/characters/import。
- 角色删除：DELETE /api/characters/{character_id}（级联删除好感度/记忆/游戏数据）。
- 好感度查询：GET /api/affinity；好感度更新：POST /api/affinity。
- 动态数据：GET /api/characters/{id}/dynamics（双线好感度/动态机制）。

### E.3 用量与限额（/api/usage 系）

- 用量明细：GET /api/usage（provider 口径，明细页不再空白）。
- 配额查询：GET /api/usage/quota（check_quota）。
- 记账：POST /api/usage/record（record_usage，估算量不入账）。

### E.4 存储与文件（/api/storage 系 /api/files）

- 文件列表/读取/写入/删除。
- 设置：GET/POST /api/settings（load_app_settings）。

### E.5 游戏（/api/game 系）

- 游戏状态：GET /api/game（game_state.json）。
- 商城：GET /api/game/shop；购买：POST /api/game/purchase。
- 每日任务：GET /api/game/tasks。
- 对局：POST /api/game/match（五子棋 vs 角色）。

### E.6 语音（/api/tts /api/stt 系）

- TTS 合成：POST /api/tts（facade 统一出口）。
- STT 状态：GET /api/stt/status（缺模型报缺失，不阻断启动）。
- STT 识别：POST /api/stt/recognize。
- 语音会话：POST /api/voice/session（语音对话链路）。

### E.7 系统与监控（/api/system 系）

- 系统状态：GET /api/system（服务状态/看门狗）。
- 保险库：GET/POST /api/vault（文件级保险库管理）。
- 调度：GET/POST /api/scheduler（定时任务）。
- 进化：GET /api/evolution（进化状态）。
- 存储健康：GET /api/storage/health（quota/lifecycle/audit/health）。
- 记忆：GET/POST /api/memory（记忆面板）。

### E.8 双引擎与 MCP（历史/扩展）

- /api/dual-run、/api/dual-status、/api/dual-intervene（双引擎遗留，已清理但可能残留路由）。
- /api/mcp（MCP 能力管理，热插拔）。

> 复刻注意：163 端点全绿是质量基线；所有端点须捕获异常（不裸崩 500），依赖缺失降级 503。

---

## 扩充章 F：事件类型全清单（eventbus 实录）

事件总线（_core/eventbus.py）声明的事件类型（§14.3 集中常量）：

| 事件 | 语义 |
|---|---|
| entity.deleted | 实体删除（跨砖级联删除触发点） |
| affinity.settled | 好感度结算完成 |
| tool.registered / tool.unregistered | 工具注册/注销 |
| voice.session_start / voice.session_end | 语音会话开始/结束 |
| voice.transcript | ASR 最终文本 |
| voice.partial | ASR 中间结果 |
| voice.interruption | 打断信号 |
| voice.vad_state | VAD 状态变化 |
| voice.reply_ready | 对话完成（负载含 text 回复 + voice_text 原始语音文本）——语音回复链路接线点 |
| voice.speaker | 声纹识别结果（speaker/similarity/is_match）——按说话人切换角色与个性化 |
| voice.tts_audio_chunk | 逐句并行合成音频块（seq/text/audio）——边生成边合成播放 |

**总线机制**：
- emit(event_type, payload)：同步分发，单个订阅方异常不影响其余（降级隔离）。
- subscribe(event_type, handler)：返回取消函数；handler 可为同步或 async（async 用 asyncio.run 执行）。
- 订阅表 + 事件审计（最近 N 条）供健康报告展示。
- 设计隐喻：南桥（事件总线，广播、不要结果）vs 北桥（能力总线 get_facade，点对点、要结果）。

**SSE 事件（前端可见）**：text / thought / tool_call / ask_user / verdict（与前文 14.1 一致）。

---

## 扩充章 G：工具集详解（services/agent/tools/ 实录 9 文件）

| 文件 | 工具类别 | 代表工具 | 安全要求 |
|---|---|---|---|
| ask_tool.py | 提问 | ask_user（向用户提问获取信息/确认） | 事件 id 应答闭环 |
| file_tools.py | 文件 | 读写/列目录/查找/文档结构化（doc2struct） | 删除走 vault |
| life_tools.py | 生活 | 生活类工具（备忘/提醒等） | — |
| life_domestic_prod_tools.py | 生活/家庭 | 家庭生产工具（购物/家务清单等） | — |
| sandbox_tools.py | 代码沙箱 | run_code（隔离执行） | code_guard + subprocess 隔离 + 守卫询问 |
| scheduler_tools.py | 调度 | 定时任务工具（设 cron/查任务） | 与 ops/engine 联动 |
| web_tools.py | 网络 | WebSearch / ChineseDictTool / HTTP 抓取 | 必须过裁决引擎 + net 门面 |
| window_api.py | 窗口桥接 | pywebview 窗口 API 封装 | 桥接层 |
| window_tools.py | 窗口工具 | 窗口控制 | — |

**工具注册机制**：
- ToolRegistry（tool_base.py）：运行时注册/注销，agent 服务暴露 register_tool/unregister_tool 能力。
- 工具元数据：名称/描述/参数 schema/执行函数/能力标记。
- 匹配：tool_matcher 按意图匹配；autoFilterTools 开关控制自动过滤（settings.json agentAutoFilterTools）。
- 校验自愈：参数 schema 缺参补默认、错型纠正（P2 健壮性）。
- 调用链：匹配 → 校验 → 裁决（guardrail）→ 授权（permission）→ 事件下发 → 执行 → 回注。

---

## 扩充章 H：环境变量全量（.env.example 实录）

| 变量 | 默认 | 说明 |
|---|---|---|
| HOST | 127.0.0.1 | 监听地址 |
| PORT | 8000（部署 8005） | 服务端口 |
| CORS_ALLOW_ORIGINS | localhost:5173 等 | 跨域来源 |
| QWEN_TTS_API_URL | http://127.0.0.1:19300 | 本地 TTS 服务 |
| QWEN_TTS_AUTO_LAUNCH | true | 自动拉起 serve.py |
| QWEN_TTS_MODEL_DIR | Data/qwen_tts_voicedesign | 模型目录 |
| QWEN_TTS_MODEL | VoiceDesign | 模型标识（VoiceDesign/CustomVoice/Base） |
| QWEN_TTS_QUANTIZE | 4bit | 量化（4bit/8bit/off） |
| QWEN_TTS_VOICES_DIR | （空） | 参考音频目录 |
| STT_ENABLED | false | STT 开关 |
| STT_AUTO_LAUNCH | true | 自动拉起 |
| STT_API_URL | http://127.0.0.1:19500 | STT 服务 |
| STT_SAMPLE_RATE | 16000 | 采样率（16kHz 单声道） |
| STT_VAD_MODEL / STT_ASR_MODEL / STT_KWS_MODEL | Data/stt_models/... | 模型路径 |
| STT_KWS_KEYWORDS | .../keywords.txt | 唤醒词 |
| STT_VENV_PYTHON | （空） | STT venv Python 路径 |
| MENTALCORE_API_KEY | （空） | 心智核心模型端点密钥 |

---

## 扩充章 I：项目术语表

| 术语 | 含义 |
|---|---|
| 砖块（Brick） | 旧架构模块单位（已归档） |
| 主板/总线/芯片 | 旧架构硬件隐喻（已归档） |
| Port | 终极架构契约层（15 个 ABC） |
| 服务 | container 注册名（storage/settings/... 14 个） |
| capability | 服务能力键（capability("store_file")） |
| 容器（container） | 依赖注入容器（get/register/names） |
| 门面（facade） | 能力收敛出口（net 门面/统一 facade） |
| 裁决（guardrail） | 5 档安全裁决 |
| 心智魔方（Boss） | mentalcore 聊天核心 |
| 外骨骼（Worker） | mentalcore 干活核心 |
| EXO 协议 | Boss→Worker 委派协议（||EXO|| 标记） |
| 缝合引擎 | 检索式对话兜底（零联网） |
| 双线好感度 | 基准线 + 动态线 |
| 星砂 | 游戏货币 |
| 保险库（vault） | 删除拦截兜底 |
| 网卡 | 唯一出网出口（fail-closed） |
| 南桥/北桥 | 事件总线/能力总线隐喻 |
| 裁决事件 | 主动动作裁决记录 |
| 轨迹（trace） | Agent 运行记录 |
| 账本（ledger） | Token 真实用量记录 |
| 运行模式 | max/min/mock（mode_resolver） |
| 自主等级 | full 等（进化 gate） |



# P.A.L.M 项目总览与产品说明（深度扩充三：归档快照与运行环境深度解析）

> 承接扩充章 A-I。本部分深度解析归档备份的整体结构（git 仓库/venv/日志），以及项目运行环境（虚拟环境/模型/依赖）的完整形态。

---

## 扩充章 J：归档备份 D:/PALM_backup_20260818 整体结构深度解析

### J.1 顶层结构

归档备份顶层共 8 项：4 个备份日志 + Data/ + git_broken_20260818/ + 3 个 venv（venv_cosyvoice/venv_gsv/venv_runtime）。

### J.2 git_broken_20260818/ 深度解析（旧 git 仓库 .git 目录）

这是项目早期（07-31 克隆起）的 git 仓库元数据目录，因对象损坏（refs/heads/main 指向的对象缺失）称"broken"：

| 文件/目录 | 内容 |
|---|---|
| COMMIT_EDITMSG | 最后一次提交消息编辑记录（08-18 18:03 入仓提交） |
| config | 仓库配置（origin = github.com:Dawn23410/12345.git） |
| description | 仓库描述 |
| FETCH_HEAD | 最近 fetch 记录（08-14 21:51） |
| HEAD | 指向 refs/heads/main |
| index | 索引文件（1.3MB，最后一次入仓的完整文件清单快照） |
| packed-refs | 引用打包：main=97e43978、origin/main=b1aff980 |
| lfs/ | Git LFS 目录（大文件存储） |
| logs/HEAD | **87 条 reflog——完整提交历史（本文档系列的时间线素材）** |
| logs/refs/heads/main | main 分支 reflog（84 条） |
| objects/ | 对象库（部分对象在损坏中缺失） |
| refs/ | 引用目录 |

**复刻价值**：
1. reflog 87 条提供完整演进史（07-31 至 08-18）。
2. index（1.3MB）含最后一次入仓的完整路径清单——可重建"入仓前工作区结构"。
3. packed-refs 记录 main 与 origin/main 的分叉——origin/main 落后于本地 main（b1aff980 vs 97e43978），说明本地长期领先远端（骨架本地提交不 push 的惯例证据）。

### J.3 三个虚拟环境深度解析

| venv | 用途 | 关键内容（推断） |
|---|---|---|
| venv_runtime | 主运行时 | FastAPI/uvicorn/pydantic/pyyaml 等后端依赖 + palm 库依赖 |
| venv_cosyvoice | CosyVoice 语音 | torch cu128（Blackwell 配方）+ vendored cosyvoice/matcha + wetext==0.0.4 + soundfile |
| venv_gsv | GPT-SoVITS | GSV 自包含运行时（模型 + runtime，启动即拉起） |

**隔离原则**：语音引擎的依赖（torch 全家桶、onnx、音频库）与主运行时隔离——避免 torch 版本冲突污染主应用；语音引擎可独立升级/重建。

### J.4 四个备份日志解读

| 日志 | 时间 | 内容 |
|---|---|---|
| backup_runtime.log | 08-18 17:31 | 主运行时 venv 备份 |
| backup_gsv.log | 08-18 17:46 | GSV venv 备份 |
| backup_cosy.log | 08-18 17:57 | CosyVoice venv 备份 |
| backup_data.log | 08-18 17:22 | Data 数据备份 |

备份顺序：Data（17:22）→ runtime（17:31）→ gsv（17:46）→ cosy（17:57），与 git 全量入仓（17:18）交错进行——说明归档是一次系统性的快照动作（数据先行、环境随后）。

---

## 扩充章 K：运行环境完整形态

### K.1 依赖分层

| 层 | 依赖 | 说明 |
|---|---|---|
| 基础 | fastapi/uvicorn/pydantic/pyyaml/httpx | 后端框架与工具 |
| 模型 | openai 兼容客户端（tokenhub） | 云端 LLM 接入 |
| 语音（独立 venv） | torch cu128/onnx/soundfile/wetext/cosyvoice/matcha | Blackwell 配方 |
| 向量 | chromadb（live）/onnxruntime（bge INT8） | 记忆/检索 |
| GUI | uiautomation/pywin32 | Windows 辅助功能 |
| 前端 | 无构建依赖（原生 ES Modules） | 12 页原生 |

### K.2 端口约定

| 端口 | 服务 |
|---|---|
| 8000/8005 | FastAPI 后端（8005 部署） |
| 5173 | Vite 前端开发 |
| 8012 | e2e 测试 |
| 19300 | Qwen3-TTS 本地服务 |
| 19500 | STT 本地服务 |
| 11434 | Ollama（bge-m3 嵌入，本地向量） |

### K.3 模型矩阵

| 用途 | 模型 | 位置 |
|---|---|---|
| 主对话 | kimi-k2.5 等（settings.json 实测） | 云端 tokenhub |
| 快速模型 | kimi-k2.5（flashModel） | 云端 tokenhub |
| 供应商模型池 | glm-5-turbo/minimax-m2.7/glm-5/qwen3.5-plus/kimi-k2.5/kimi-k2.7-code/mimo-v2.5-pro | tokenhub（OpenAI 兼容） |
| 心智核心 | GLM-4.5-Flash-nothink 等非推理模型 | NoneLinear/自定义端点 |
| 本地 TTS | Qwen3-TTS-12Hz-1.7B-VoiceDesign | Data/qwen_tts_voicedesign |
| 语音合成 | CosyVoice2/GPT-SoVITS | venv_cosyvoice/venv_gsv |
| 嵌入 | bge-small-zh（INT8 ONNX）/bge-m3（Ollama） | 本地 |
| ASR | Silero VAD + Zipformer ASR | Data/stt_models |

---

## 扩充章 L：完整功能清单（逐能力展开）

### L.1 对话体验

- 流式输出（SSE text 事件）。
- 思维链时间线（thought 事件渲染）。
- 工具调用实时计时与输入展示。
- ask_user 问答（id 应答闭环）。
- 上下文压缩（长对话摘要化）。
- 反思自检（回答成立性）。

### L.2 角色扮演

- 角色卡管理（社区规范对齐）。
- Markdown 人格技能导入（梦瑶等）。
- 开场白 first_mes。
- 双线好感度（基准/动态）+ 10 级分层 + 档位增速。
- 角色动态机制（互动改变表现）。
- 语气污染防护（关闭角色无残留）。

### L.3 记忆

- 分层记忆（核心/向量/归档）。
- 只存事实（污染检测）。
- 双幂律衰减 + 去噪归一。
- 语义检索（bge INT8，弱召回门控）。
- Token 预算裁剪。

### L.4 游戏化

- 星砂货币 + 商城 + 道具。
- 全局等级（10 阶 × 100 级）。
- 每日任务（chat_once/plan_once/chat_ten）。
- 特殊对局（五子棋）。
- 经验结算回连（聊天/规划 done 钩子）。

### L.5 自主进化

- 闲置自主推测。
- 每日简报（定时）。
- 习惯引擎。
- 主动推送（经裁决）。
- 跨砖级联删除。

### L.6 语音

- 四引擎统一门面（GSV/CosyVoice2/GPT-SoVITS/STT）。
- 语音对话链路（ASR→LLM→TTS）。
- 声纹识别（按说话人切换角色）。
- 边生成边合成（tts_audio_chunk 事件）。
- Qwen3-TTS 本地合成（VoiceDesign 文本造音色）。

### L.7 GUI 自动化

- automate(软件, 意图) 单一入口。
- L0-L3 四级容错执行器。
- Atlas 静态认知 + 转移规律 + 坐标记忆（EMA）。
- 世界模型（GUI 状态认知）。

### L.8 安全

- 权限引擎（敏感能力须授权）。
- 裁决 5 档（死线/严格/宽松/AI 兜底/白名单）。
- 网卡门面（唯一出口，fail-closed）。
- 文件保险库（删除拦截可恢复）。
- 看门狗 + 审计。

### L.9 运维

- 系统总览中枢（14 服务状态）。
- 存储面板（quota/lifecycle/audit/health）。
- 用量面板（Token 真实账本）。
- 调度面板（定时任务）。
- 监控面板（看门狗/裁决审计）。

### L.10 心智核心

- 六面聊天（人格/记忆/情感/织语/律动/储存）。
- 18 条五位控制码。
- Boss/Worker 双链外骨骼。
- EXO 委派协议。
- 5 小魔方 + 安全三拆分。
- mock/live 双模式（零落盘/加密落盘）。



# P.A.L.M 项目总览与产品说明（深度扩充四：安全隐私/性能指标/扩展路线图）

> 承接扩充章 J-L。本部分覆盖：数据安全与隐私模型、性能指标汇总、扩展路线图、与同类产品对比。

---

## 扩充章 M：数据安全与隐私模型

### M.1 数据分类与处理

| 数据 | 存储位置 | 保护 |
|---|---|---|
| 对话记录 | Data/对话记录/ | 明文（JSON），本机 |
| 长期记忆 | Data/agent_memory/ + 向量库 | 语义检索（本机）；mentalcore live 加密 |
| 角色卡 | Data/characters/ | 明文（JSON） |
| 游戏状态 | Data/game_state.json | 明文 |
| 权限记录 | Data/permissions.json | 明文 |
| 密钥/敏感配置 | secure_config | 加密（指纹绑定） |
| mentalcore 记忆 | mentalcore_data/ | SM4-CBC+HMAC-SM3 加密（live） |
| API Key | .env / settings.json customProviders | 本机明文（.env gitignore） |

### M.2 隐私原则

1. **本地优先**：核心数据全部本机；仅模型推理走云端（tokenhub 代理）。
2. **运行期零联网**：缝合引擎/心智核心 mock 模式零出网。
3. **出网单一出口**：一切外网请求经 net 门面（可审计/可阻断）。
4. **删除可恢复**：vault 拦截删除。
5. **授权记录**：敏感能力首用询问并持久化。

### M.3 威胁模型（红队视角）

| 威胁 | 防线 |
|---|---|
| prompt 注入 | guardrail 裁决 + 注入面修复 + 注入样例库 |
| 越权工具调用 | 权限引擎（须授权）+ 工具闸门 |
| 代码逃逸 | 沙箱 subprocess 隔离（fail-closed） |
| 数据外泄 | 网卡门面（唯一出口）+ 通信魔方审计 |
| 记忆污染 | 只存事实 + 污染检测 + 防污染清档 |
| 端点滥用 | token 配额（daily/monthly limit）+ 账本 |

---

## 扩充章 N：性能指标汇总

### N.1 对话链路

| 指标 | 值 | 条件 |
|---|---|---|
| 心智核心 mock 单轮 | 3.9ms 均值 | 离线回显 |
| 心智核心 live TTFB | 5.61s 中位 / 32.54s P95 | 公共端点（排队延迟） |
| 平均回复长度 | 159 字 | 100 轮实测 |
| 协议遵守率 | 95-100% | ||DATA||/||EXO|| 结构块 |
| GSV TTS 全链路 | 约 2.3 秒 | 语音回复 |

### N.2 质量指标

| 指标 | 值 |
|---|---|
| 端点扫描 | 163 端点无 500 |
| 单元测试 | 7/8（遗留 1 项） |
| mentalcore selftest | 全过 |
| exo selftest | 4 测全过 |
| 100 轮稳定性 | 1 次错误/100 轮（重试恢复） |

### N.3 资源占用（推断）

- 主运行时：轻量（FastAPI + 常驻服务）。
- 语音引擎：独立进程（GSV 启动即拉起）。
- 本地 TTS：4bit NF4 约 2GB 显存（4G 卡可跑）。
- 向量库：chroma 本机（mock 不建库）。

---

## 扩充章 O：扩展路线图

### O.1 规划中的演进（来自路线图/提交/记忆）

| 项 | 状态 | 说明 |
|---|---|---|
| 好感度解耦重构 | 规划中 | 好感度与角色扮演解绑独立 |
| agent 对标主流框架 | 进行中 | LangChain/OpenAI Agents/Claude Agent SDK |
| 游戏生态扩展 | 规划中 | 五子棋对局细化/每日任务扩展 |
| 外骨骼 Worker 扩展 | 规划中 | 更多小魔方/模型解耦 |
| GUI L0-L3 打磨 | 进行中 | 执行器容错 |
| 语音统一门面优化 | 进行中 | TTS 全链路 2.3s 目标 |

### O.2 可扩展架构支撑

1. **Port 契约**：新增能力 = 新增 Port ABC + 适配器实现 + 容器注册。
2. **服务容器**：14 服务可增删；业务经 capability 取用，零耦合。
3. **模型供应商**：customProviders 数组扩展。
4. **工具注册**：运行时 register_tool。
5. **技能导入**：Markdown 技能卡。
6. **插件发现**：MCP/热插拔（旧主板体系遗留能力）。
7. **外骨骼魔方**：Worker 小魔方可增。

---

## 扩充章 P：与同类产品对比（诚实对比）

| 维度 | P.A.L.M | 通用聊天助手 | 陪伴型 AI 产品 |
|---|---|---|---|
| 人格化 | 角色卡 + 双线好感度 + 动态机制 | 弱/固定 | 强（同档） |
| 记忆 | 分层 + 双幂律衰减 + 污染检测 | 一般（向量检索） | 一般 |
| 工具能力 | 100+ 工具 + GUI 自动化 + 沙箱 | 强（通用） | 弱 |
| 安全 | 裁决 5 档 + 权限 + 保险库 + fail-closed | 中 | 弱 |
| 本地化 | 本地优先 + 零联网模式 | 云端 | 云端 |
| 游戏化 | 星砂/等级/每日任务/对局 | 无 | 部分（好感度） |
| 自主进化 | 闲置推测/简报/习惯 | 无 | 无 |
| 语音 | 四引擎 + 声纹 + 本地 TTS | 基础 | 基础 |
| 心智核心 | 六面 + 控制码 + Boss/Worker | 无 | 无 |
| 复刻友好 | 本系列文档（1:1 复刻级） | 闭源 | 闭源 |

**定位结论**：P.A.L.M 在"人格化 + 本地化 + 工具化 + 游戏化"四维组合上具备差异化——它是"有性格、能干活、住在本机、会成长"的个人 AI 管家，而非通用聊天工具。

---

## 扩充章 Q：项目 DNA 总结

1. **自研优先**：原生 FC、Agent 框架、裁决引擎、记忆算法、心智核心全部自研——外部依赖仅限基础设施（FastAPI/LLM API/语音引擎）。
2. **安全即架构**：fail-closed 贯穿（裁决/网卡/沙箱）；删除可恢复；审计留痕。
3. **规范即底线**：函数≤50行/文件≤500行/单一职责/中文注释——代码质量硬约束。
4. **验收即证据**：任何能力落地伴随可复现基准（算法级对照、端点扫描、selftest）。
5. **演进即推翻**：双引擎回退、主板体系推翻、终极架构确立——敢于自我否定，快速迭代。
6. **归档即保障**：先归档不删；归档备份保证历史可追溯、可恢复。
7. **人格与能力分离**：Boss 只聊不干、Worker 只干不聊——陪伴与效率解耦。


# P.A.L.M 项目总览与产品说明（深度扩充五：FAQ 大全与部署手册）

> 承接扩充章 M-Q。本部分给出：部署操作手册（逐步）、常见问题全解、以及项目边界与限制的完整说明。

---

## 扩充章 R：部署操作手册（逐步）

### R.1 全新部署（从备份或源码）

**步骤一：环境准备**
1. 安装 Python 3.11+。
2. 克隆/复制源码（palm/ + mentalcore/ + frontend/）。
3. 复制 .env.example → .env，按需修改。

**步骤二：主运行时依赖**
```bash
python -m venv venv_runtime
venv_runtime/Scripts/pip install fastapi uvicorn pydantic pyyaml httpx
venv_runtime/Scripts/pip install -e palm   # palm 库
venv_runtime/Scripts/pip install -e mentalcore  # 心智核心
```

**步骤三：语音引擎（可选）**
- CosyVoice：独立 venv_cosyvoice，torch cu128（Blackwell），vendored 源码。
- GSV：独立 venv_gsv（自包含，启动即拉起）。
- Qwen3-TTS：.venv-qwen-tts + 模型（Data/qwen_tts_voicedesign）。
- STT：.venv-stt + 模型（Data/stt_models）。

**步骤四：数据目录**
- 创建 Data/ 及子目录（对话记录/记忆/角色/游戏/配置/审计/存储池）。
- 放置角色卡（characters/mengyao.json 等）。

**步骤五：启动**
```bash
python dev.py        # 后端 + 可选前端/语音
# 或：
venv_runtime/Scripts/python -m uvicorn palm_app:app --port 8005
# 前端：Vite dev（5173）或静态托管；pywebview 壳加载
```

**步骤六：验证**
1. 装配日志：14 服务注册成功（无降级异常）。
2. GET /api/system 返回服务状态。
3. POST /api/chat 对话流式。
4. 角色列表 GET /api/characters。
5. 用量页 GET /api/usage。

### R.2 升级部署（从旧版）

1. 归档备份（Data/venv/git → 备份目录）。
2. 同步新代码。
3. 数据迁移检查（结构兼容）。
4. 启动验证（端点扫描/自检）。

### R.3 备份与恢复

- 备份：Data/ + venv + git（归档目录，先归档不删）。
- 恢复：目录还原 + 依赖重装 + 启动验证。

---

## 扩充章 S：常见问题全解（FAQ 扩展）

### S.1 功能类

**Q：为什么我的对话没有角色语气？**
检查：角色开关（settings.json agentCharacterId 为空）；三处注入点是否剥离（关闭后残留是缺陷）。

**Q：好感度为什么涨得慢？**
吝啬制设计：日常 Δ 为小数步进（0.0x 级）；高等级档位增速放缓；质变轮才大幅变化。

**Q：星砂怎么获得？**
每日任务（chat_once/plan_once/chat_ten）+ 特殊对局（五子棋按分数难度）+ 固定任务。

**Q：记忆为什么不记得我说过的情绪？**
长期记忆只存事实不存语气（污染检测）；情绪以五因子向量附加（E_enc 仅 v≥0），但不作为主记忆内容。

**Q：GUI 自动化为什么不执行？**
检查执行器档位（L0 UIA 首选）；LLM 兜底未配置时 fail-closed 拒绝（档3/4）；辅助模式须 ensure_off。

### S.2 架构类

**Q：为什么不用主板架构了？**
复杂度失控（30 砖 + palm_sdk + 网关），契约缺失；终极架构（ports/container）更轻、更可校验。

**Q：palm_sdk 还能用吗？**
已退役归档（archive/palm_sdk_20260818）；功能收敛进 palm/_core/。

**Q：双引擎（CodeBuddy）还有吗？**
已清理（08-02 全量回退）；当前仅本地自研引擎。

**Q：新增一个服务怎么接？**
实现适配器/服务 → 在 bootstrap/app.py 注册（带 capabilities）→ 业务经 container.get(名).capability(键) 取用。

### S.3 安全类

**Q：AI 档裁决一定安全吗？**
AI 档无回调时 fail-closed deny（不默认放行）；ask 超时 30s 默认 deny。

**Q：删除的文件能找回吗？**
能：删除先入 vault（保险库），前端保险库面板可恢复。

**Q：离线能用吗？**
缝合引擎/心智核心 mock 可离线（零联网）；完整对话需云端模型。

### S.4 性能类

**Q：首字慢怎么办？**
先定位：本地链路（mock 对照）vs 端点排队（TTFB 指标）。端点排队 → 换模型/换端点/本地模型。

**Q：显存不够跑本地 TTS？**
Qwen3-TTS 4bit NF4 约 2GB；4G 卡可跑；或关闭本地 TTS 用云端/GSV。

---

## 扩充章 T：项目边界与限制（诚实披露）

### T.1 已知限制

1. 单元测试 7/8（遗留 1 项）。
2. GUI 部件数据获取 bug（glass_clock 等时间组件）曾长期存在。
3. 归档 git 仓库对象损坏（reflog 可用，工作区内容部分不可恢复）。
4. 前端无构建链（原生 ES Modules）——大型组件需手工管理依赖。
5. 语音引擎依赖较重（torch cu128、模型文件 GB 级）。
6. mock 模式功能受限（仅对话）。

### T.2 设计取舍

1. 本地优先 vs 云端能力：隐私换取便利（可配置）。
2. fail-closed vs 可用性：安全优先（宁拒勿放）。
3. 自研 vs 生态：核心自研（可控）vs 基础设施复用（FastAPI/LLM API）。
4. 游戏化复杂度：养成深度 vs 实现成本（骨架先行，细节后填）。

### T.3 演进承诺

1. 数据格式向后兼容（JSON 结构化）。
2. 归档先于删除（可恢复）。
3. 基准诚实（不包装数据）。
4. 文档与代码同步（评审驱动）。


# P.A.L.M 项目总览与产品说明（深度扩充六：使用场景与体验指南）

> 承接扩充章 R-T。本部分给出：典型使用场景全解（面向最终用户）、语音/GUI/游戏等特色能力的使用说明、以及多角色与多用户场景。

---

## 扩充章 U：典型使用场景全解（面向用户）

### U.1 日常陪伴场景

**场景：与梦瑶闲聊**
1. 打开对话页（chat.html）。
2. 确认角色为梦瑶（settings.agentCharacterId）。
3. 发送消息，流式回复 + 思维链展示。
4. 好感度随对话缓慢增长（双线：基准 + 动态）。
5. 关系质变（表白/道歉/纪念日）→ 大幅波动 → 档位变化。

**体验要点**：
- 开场白 first_mes（新会话首条）。
- 角色动态（语气/称呼随好感度变化）。
- 语气污染防护（长期记忆不脏）。

### U.2 工具助手场景

**场景：让 Agent 查资料并整理**
1. 输入"帮我搜索 XX 的最新消息并整理要点"。
2. 规划引擎：先计划（搜索→整理→输出）。
3. 工具调用：web_search（经裁决 + 网卡）。
4. 结果回注 → 反思闸门 → 结构化输出。
5. 完成 → 经验结算（award_plan_xp）。

**安全提示**：
- 联网工具会过裁决（未授权 ask_user）。
- 代码执行会过守卫（run_code 询问）。

### U.3 语音场景

**场景：语音对话**
1. 打开语音会话（voice.session）。
2. 说话 → STT（VAD 静音检测 → ASR 识别，16kHz）。
3. 文本进入对话链路 → LLM 回复。
4. TTS 合成（facade：GSV 播音员/CosyVoice2 音色设计/Qwen3-TTS 本地）。
5. 音频回放（边生成边合成 tts_audio_chunk）。

**体验要点**：
- 全链路约 2.3s（GSV）。
- 声纹识别（多用户：voice.speaker 切换角色）。
- 打断（voice.interruption）。

### U.4 GUI 自动化场景

**场景：自动化桌面操作**
1. 调用 automate(software_id, intent)。
2. L0 UIA 树操作（首选）。
3. UIA 不可用 → L2 OCR 定位。
4. LLM 兜底/VLC（档3/4，未配置 fail-closed）。
5. 坐标记忆（EMA）提升重复操作精度。

**支持**：桌面视觉操作技能（skills/desktop-visual-operator）、GUI Atlas 规划（skills/gui-atlas-planner）。

### U.5 游戏化场景

**场景：养成与对局**
1. 每日任务：聊天 1 次 / 10 次、触发规划。
2. 星砂获取：任务/对局。
3. 商城购买道具（affinity_display 显示好感度）。
4. 五子棋 vs 角色（分数难度给经验）。
5. 等级成长（10 阶 × 100 级）。

### U.6 进化场景

**场景：AI 主动服务**
1. 闲置 15 分钟 → 自主推测（准备可能的回复/建议）。
2. 每日定时 → 每日简报（当日摘要）。
3. 习惯学习 → 主动推送适配（如常用时间/话题）。
4. 主动动作经裁决审计（可关闭：autonomyLevel）。

---

## 扩充章 V：多角色与多用户场景

### V.1 多角色管理

- 角色卡导入：JSON / Markdown 技能 / 社区格式。
- 角色切换：settings.agentCharacterId 或对话页选择。
- 每角色独立好感度（affinity 按 character_id）。
- 角色删除级联清理（好感度/记忆/游戏数据）。

### V.2 多用户（声纹驱动）

- 声纹识别（voice.speaker）：speaker + similarity + is_match。
- 按说话人切换角色与个性化（记忆/偏好）。
- 多用户场景：家庭共用一套系统，每人各自角色关系。

### V.3 心智核心独立使用

- 纯 mentalcore：轻量陪伴（无工具）。
- 18 控制码管理（查/改好感度、角色卡、对话记录、语义检索）。
- mock/live 双模式（演示零落盘 / 生产加密）。

---

## 扩充章 W：系统管理体验

### W.1 系统总览中枢（overview.html）

- 14 服务状态卡（注册/降级）。
- 存储健康（quota/lifecycle/audit/health）。
- 调度任务列表。
- 进化状态（主动推送记录）。

### W.2 用量管理（usage.html）

- Token 明细（provider 口径，真实账本）。
- 每日/每月配额进度（dailyTokenLimit 500 万 / monthly 5000 万）。
- 超额拦截（check_quota）。

### W.3 保险库（vault）

- 已删文件列表（可恢复）。
- 彻底删除（purge 二次确认）。
- 删除拦截兜底（业务删除先入 vault）。

### W.4 设置（settings.html）

- 模型：flash/pro/default + 供应商管理（customProviders）。
- 语音：引擎选择/参数。
- STT：开关/模型路径。
- 角色：默认角色/好感度显示。
- 游戏：开关。
- 外观：主题/字号。

### W.5 监控（monitor.html）

- 看门狗健康。
- 裁决审计（最近事件）。
- 事件总线审计。
- 威胁数据（threat_data.json）。

---

## 扩充章 X：心智核心独立体验（面向开发者）

### X.1 快速接入

```python
from mentalcore.config import load_config
from mentalcore.core import build_core
from mentalcore.persona_card import default_persona

core = build_core(load_config(), default_persona())
packet, manifest, emotion = core.send_message("你好呀")
print(packet.body)      # 回复正文
print(packet.fields)    # 数据区（消费键已过滤）
```

### X.2 控制码操作

```python
core.control(30000)                          # 查好感度
core.control(30300, {"base": 5.0})           # 改好感度基准线
core.control(40000)                          # 查角色卡
core.control(40300, {"tone": "冷淡"})        # 改角色卡语气
core.control(21000, {"query": "猫", "top_k": 3})  # 语义检索
```

### X.3 外骨骼接入

```python
from mentalcore import build_core, build_exo, default_persona

boss = build_core(load_config(), default_persona())
exo = build_exo(config)
boss.exo_broker = exo.make_broker(boss)
# 对话中模型可自发 ||EXO|| 委派后台执行
```

### X.4 调试与验收

- selftest（离线断言）。
- exo.selftest（4 测）。
- bench_50 / bench_100（基准）。
- prompt_cache_probe（缓存轨迹）。

---

## 扩充章 Y：体验优化方向（用户视角反馈循环）

1. **首字延迟**：优先本地模型/私有端点（TTFB 波动来自公共端点排队）。
2. **好感度反馈**：道具后门（affinity_display）让用户感知养成进度。
3. **记忆可解释**：语义检索（21000）可查看"记得什么"。
4. **进化可控**：autonomyLevel 调节主动程度。
5. **安全透明**：裁决原因展示（verdict 事件 reason）。
6. **数据自主**：保险库恢复/导出（10200 导出对话）。

---

## 扩充章 Z：产品叙事（一句话版本）

P.A.L.M 是"住在本机、有性格、会干活、能成长"的个人 AI 管家：以梦瑶这样的角色陪你聊天（六面人格 + 双线好感度），以 100+ 工具为你干活（规划/反思/沙箱/自动化），以游戏化机制陪你养成（星砂/等级/对局），以自主进化主动服务（闲置推测/每日简报），以纵深安全保护数据（裁决/权限/保险库/fail-closed）。21 天 90+ 次提交、320+ 文件、终极架构 + 心智核心双库成型——本文档系列以 1:1 复刻颗粒度完整记录这一切。


# P.A.L.M 项目总览与产品说明（深度扩充七：前端页面详细设计与交互流程）

> 承接扩充章 U-Z。本部分详细展开前端 12 页的页面结构、交互流程、与后端契约。

---

## 扩充章 AA：对话页详细设计（chat.html）

### AA.1 页面结构

```
对话页
├── 头部：角色选择（agentCharacterId）/ 模式指示 / 用量指示
├── 消息列表
│   ├── 用户消息（右对齐）
│   ├── AI 消息（左对齐，流式追加）
│   ├── 思维链区块（thought 事件，折叠）
│   ├── 工具调用卡（tool_call：名称/参数/状态/计时）
│   └── 裁决提示（verdict：deny 原因展示）
├── 输入区：文本输入 + 发送
└── ask_user 弹窗（id 应答）
```

### AA.2 交互流程

```
1. 用户输入 → POST /api/chat
2. SSE 事件流接收：
   - text：追加到当前 AI 消息
   - thought：思维链折叠区块
   - tool_call：工具卡（计时器启动）
   - tool_result：工具卡结果更新
   - ask_user：弹窗（携带 id）
   - verdict：拦截原因提示
   - done：结算动画（经验/星砂）
3. ask_user 应答 → POST /api/ask-response {id, answer}
4. 完成后刷新用量指示
```

### AA.3 关键实现

```javascript
// SSE 接收
const es = new EventSource(`/api/events?conversation_id=${convId}`);
es.onmessage = (e) => {
  const evt = JSON.parse(e.data);
  switch (evt.type) {
    case "text": appendText(evt.payload.text); break;
    case "thought": appendThought(evt.payload.text); break;
    case "tool_call": addToolCard(evt.payload); break;
    case "ask_user": showAskDialog(evt.payload); break;
    case "done": onDone(evt.payload); break;
  }
};
```

---

## 扩充章 BB：系统总览页详细设计（overview.html）

### BB.1 页面结构

```
系统总览
├── 服务状态卡（14 个）：名称/状态（在线/降级）/能力数
├── 运行模式（max/min/mock）
├── 模型信息（当前模型/供应商）
├── 存储健康（quota/lifecycle/audit/health）
├── 调度任务列表
└── 进化状态（主动推送记录）
```

### BB.2 数据来源

```
GET /api/system → 服务状态 + 运行模式 + 模型信息
GET /api/storage/health → 存储健康
GET /api/scheduler → 任务列表
GET /api/evolution → 进化状态
```

---

## 扩充章 CC：商城页详细设计（game.html）

### CC.1 页面结构

```
商城页
├── 玩家状态卡：等级（10 阶 × 100 级）/ 经验进度 / 星砂余额 / 连登
├── 商品列表：道具卡（名称/价格/效果）
├── 每日任务：chat_once/plan_once/chat_ten（进度 + 奖励）
├── 对局入口：五子棋（难度选择）
└── 我的道具：已解锁列表
```

### CC.2 交互流程

```
1. GET /api/game → 状态
2. GET /api/game/shop → 商品
3. 购买：POST /api/game/purchase {item_id} → 星砂扣减 + 道具入库
4. 对局：POST /api/game/match {difficulty} → 五子棋
5. 每日任务进度自动刷新
```

---

## 扩充章 DD：保险库页详细设计

### DD.1 页面结构

```
保险库页
├── 已删文件列表（原路径/删除时间/大小）
├── 恢复按钮（restore）
└── 彻底删除按钮（purge，二次确认）
```

### DD.2 交互流程

```
1. GET /api/vault → 列表
2. 恢复：POST /api/vault/restore {id} → 文件回原路径
3. 彻底：DELETE /api/vault/{id} → 二次确认后删除
```

---

## 扩充章 EE：用量页详细设计（usage.html）

### EE.1 页面结构

```
用量页
├── 今日用量（prompt/completion/total）
├── 月度用量
├── 配额进度条（daily 500 万 / monthly 5000 万）
├── 明细表（时间/会话/模型/token 明细）
└── 图表（chart.js 趋势）
```

### EE.2 数据原则

- 只展示 provider 真实账本（估算量不显示）。
- 明细页不再空白（历史修复项）。

---

## 扩充章 FF：设置页详细设计（settings.html）

### FF.1 分组

```
模型：默认模型/flash/pro + 供应商管理（customProviders 增删改）
语音：引擎选择（GSV/CosyVoice2/Qwen3-TTS）+ 参数
STT：开关/模型路径
角色：默认角色/好感度显示开关
游戏：开关
外观：主题（light/dark）/字号/背景
高级：运行模式/自主等级/闲置分钟数/Token 限额
```

### FF.2 保存机制

- POST /api/settings（Windows 文件锁重试）。
- 错误分类（锁异常 ≠ CORS 误报）。

---

## 扩充章 GG：监控页详细设计（monitor.html）

```
监控页
├── 看门狗：子进程/服务健康
├── 裁决审计：最近裁决事件（事件/动作/原因）
├── 事件总线：最近事件
├── 威胁数据：threat_data.json（deny 记录）
└── 日志查看器
```

---

## 扩充章 HH：其他页面概览

| 页面 | 内容 |
|---|---|
| characters.html | 角色列表/创建/导入（Markdown 技能）/删除（级联） |
| files.html | 文件浏览（存储池）/上传/删除 |
| mcp.html | MCP 能力管理（插件发现/热插拔） |
| memory.html | 记忆面板（核心记忆/语义检索/归档） |
| scheduler.html | 定时任务管理（cron 编辑） |
| index.html | 外壳/入口 |

---

## 扩充章 II：桥接层与桌面壳

### II.1 pywebview 桥接

```javascript
// 桌面壳中调用后端
const result = await window.pywebview.api.getSystemStatus();
// 桌面部件取数
const time = await window.pywebview.api.getWidgetData("glass_clock");
```

### II.2 桌面部件（widget）

- 时间类组件（glass_clock 等）经桥接层取数。
- 历史 bug：时间组件无数据 → 通过 PALM 桥接层定位调用链路（window.pywebview.api 链路排查）。

### II.3 主题

- theme.css：light/dark（settings.theme）。
- 背景/遮罩模糊（background/maskBlur）。

---

## 扩充章 JJ：前端与后端契约总表

| 前端页 | 后端接口 | 数据 |
|---|---|---|
| chat | POST /api/chat + SSE /api/events | 对话事件流 |
| overview | GET /api/system + /api/storage/health + /api/scheduler + /api/evolution | 状态 |
| game | GET/POST /api/game* | 游戏 |
| usage | GET /api/usage | 用量 |
| vault | GET/POST/DELETE /api/vault* | 保险库 |
| settings | GET/POST /api/settings | 设置 |
| monitor | GET /api/monitor | 监控 |
| characters | GET/POST/DELETE /api/characters* | 角色 |
| memory | GET/POST /api/memory | 记忆 |
| files | GET/POST/DELETE /api/storage/file | 文件 |
| scheduler | GET/POST /api/scheduler | 调度 |
| mcp | GET /api/mcp | MCP |


# P.A.L.M 项目总览与产品说明（深度扩充八：安全隐私与数据治理深入）

> 承接扩充章 AA-JJ。本部分深入：数据分类与生命周期、隐私设计、数据治理流程、以及安全运维。

---

## 扩充章 KK：数据分类与生命周期

### KK.1 数据分类

| 类别 | 数据 | 敏感度 | 保护 |
|---|---|---|---|
| 核心 | 密钥/API Key | 高 | secure_config 加密 |
| 隐私 | 对话记录/记忆 | 高 | 本机 + mentalcore 加密 |
| 业务 | 角色/游戏/设置 | 中 | 本机 JSON |
| 运行 | 日志/轨迹/指标 | 低 | 本机 |
| 模型 | 语音/向量模型 | 低 | 本地存储 |

### KK.2 数据生命周期

```
创建（对话/记忆/游戏）
  → 使用（检索/注入/展示）
  → 衰减（记忆双幂律）
  → 归档（冷数据）
  → 删除（vault 可恢复 → purge 彻底）
  → 备份（归档快照）
```

### KK.3 数据出口

```
唯一出网：net 门面（模型 API/搜索）
控制：
  - 网卡注册（fail-closed）
  - 裁决（联网工具）
  - 审计（通信记录）
  - 配额（Token 限制）
```

---

## 扩充章 LL：隐私设计原则

### LL.1 隐私优先

1. **本地优先**：核心数据全部本机。
2. **零联网模式**：缝合/心智 mock 零出网。
3. **加密落盘**：mentalcore live 加密（SM4）。
4. **删除可恢复**：vault 拦截。
5. **最小收集**：只存必要数据。

### LL.2 用户控制

1. 权限引擎（敏感能力须授权）。
2. 保险库（恢复/彻底删除）。
3. 导出（10200 对话导出）。
4. 自主等级（进化主动程度）。
5. 运行模式（mock 隔离）。

### LL.3 透明性

1. 裁决原因展示（verdict reason）。
2. 审计记录可查（monitor）。
3. 注入留痕（manifest）。
4. 用量明细（provider 口径）。

---

## 扩充章 MM：数据治理流程

### MM.1 治理框架（存储收一块砖）

```
quota（配额）：容量/Token 限额
lifecycle（生命周期）：创建/使用/衰减/归档/删除
audit（审计）：敏感操作留痕
health（健康）：存储健康检查
```

### MM.2 定期治理

```
每日：日志轮转/临时清理
每周：归档冷数据/保险库检查
每月：备份/基准/审计
季度：红队/就绪度复评
```

### MM.3 数据恢复

```
1. 保险库恢复（删除后）
2. 归档恢复（历史快照）
3. 备份恢复（灾难）
4. 导出导入（迁移）
```

---

## 扩充章 NN：安全运维

### NN.1 安全基线

```
1. 裁决档位（STRICT 默认）
2. 网卡注册（唯一出口）
3. 权限引擎（须授权）
4. 保险库（删除可恢复）
5. 沙箱隔离（代码执行）
6. 加密（live 模式）
```

### NN.2 安全事件响应

```
检测（威胁数据/审计）→ 定位（轨迹/日志）
  → 处置（规则调整/降档/禁用）
  → 修复（补防护）
  → 复盘（审计更新）
```

### NN.3 红队测试（周期）

```
注入/越权/逃逸/泄漏/滥用
每项：预期防御 → 实测 → 结论 → 修复
```

---

## 扩充章 OO：数据安全总结

P.A.L.M 的数据安全是"纵深防御 + 用户控制 + 透明可审计"的三位一体：
- 纵深防御：加密/门面/裁决/保险库/沙箱。
- 用户控制：授权/恢复/导出/等级。
- 透明可审计：原因/记录/明细/注入留痕。

这套设计保证：数据在本机、敏感已加密、删除可恢复、出网有门禁、操作有审计——隐私与可用性取得平衡。


# P.A.L.M 项目总览与产品说明（深度扩充九：最终总结与知识库使用指南）

> 承接扩充章 KK-OO。本部分给出：知识库使用指南、项目完整图景、以及全系列的收官总结。

---

## 扩充章 PP：知识库使用指南

### PP.1 快速上手路径

```
新读者（想了解 P.A.L.M）：
  读 00（总览）→ 读 01（演进）→ 读 02（贡献）→ 完成认知

复刻者（想重建 P.A.L.M）：
  读 00 → 读 03（架构）+ 04（模块）+ 05（心智）
  → 按 06（复刻指南）施工 → 验收

维护者（想演进 P.A.L.M）：
  读 03（架构原则）+ 04（模块细节）
  → 按扩展指南新增能力 → 验收
```

### PP.2 查阅路径（按主题）

```
架构问题 → 03 篇（分层/容器/契约/安全）
实现问题 → 04 篇（逐模块/算法/陷阱）
心智问题 → 05 篇（六面/控制码/双链）
历史问题 → 01 篇（提交/阶段/规律）
协作问题 → 02 篇（分工/案例/方法论）
操作问题 → 06 篇（部署/运维/验收）
数据问题 → 00 篇（目录/格式/安全）
```

### PP.3 知识库的维护原则

1. 文档与代码同步（评审驱动）。
2. 重大变更先更新知识库。
3. 归档先于删除（历史可追溯）。
4. 基准诚实（不包装数据）。

---

## 扩充章 QQ：项目完整图景（最终版）

### QQ.1 能力全景

```
P.A.L.M 能力地图：
├── 对话与 Agent（规划/FC/ReAct/反思/压缩/轨迹）
├── 角色扮演（角色卡/技能导入/双线好感度/动态）
├── 记忆（分层/衰减/检索/预算/污染检测）
├── 游戏（星砂/等级/道具/每日任务/对局）
├── 进化（闲置推测/简报/习惯/推送/级联）
├── 语音（GSV/CosyVoice2/GPT-SoVITS/STT/声纹）
├── GUI（L0-L3 执行器/世界模型/OCR）
├── 缝合（检索式对话兜底/零联网）
├── 安全（裁决 5 档/权限/网卡/保险库/审计）
├── 运维（调度/计量/监控/保洁）
└── 心智（六面/控制码/Boss/Worker/EXO）
```

### QQ.2 数据全景

```
Data/（对话/记忆/角色/游戏/配置/审计/轨迹/存储池）
mentalcore_data/（心智加密数据）
archive/（归档历史）
备份（D:/PALM_backup_20260818 全量快照）
```

### QQ.3 技术全景

```
后端：FastAPI + palm 库（14 服务 + 15 Port）
心智：mentalcore（六面 + 双链）
前端：12 页原生 ES Modules
模型：tokenhub（DeepSeek/Kimi/GLM 等）
语音：四引擎 + 本地 TTS
存储：JSON + chroma + 加密
```

---

## 扩充章 RR：全系列收官总结

### RR.1 知识库的价值

本系列 7 篇 10 万+ 字文档，实现四个目标：

1. **理解**：让任何人理解 P.A.L.M 是什么、为什么这样设计。
2. **复刻**：让任何开发者 14 天内重建功能等价的系统。
3. **演进**：让维护者有据可依地扩展系统。
4. **传承**：让 P.A.L.M 的知识永不丢失。

### RR.2 知识库的边界

1. 部分推断（贡献判定/隐含决策）已显式标注。
2. API 路径以源码为准（本系列为规划参考）。
3. 单测遗留 1 项未修复（已披露）。
4. 归档 git 对象损坏（reflog 可用）。

### RR.3 未来更新

- 架构变更 → 更新 03/04。
- 功能新增 → 更新 00/04。
- 心智演进 → 更新 05。
- 复刻反馈 → 更新 06。

---

## 扩充章 SS：最终结语

P.A.L.M——Personal AI Life Manager——是一个真实存在、可复刻、已验证的桌面 AI 管家系统：

- 它于 2026-07-31 克隆起步，21 天 90+ 次提交成型。
- 它以终极架构（ports/container）+ 心智核心（六面/双链）为骨架。
- 它以"一人一 AI"协作模式高效构建。
- 它以纵深安全守护用户数据。
- 它以本系列 10 万+ 字文档完整沉淀。

**无论你是什么角色——学习者、复刻者、维护者——本知识库都是你认识 P.A.L.M 的完整入口。知识已沉淀，复刻随时可行，传承由此开始。**



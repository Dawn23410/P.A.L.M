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



# P.A.L.M 砖块与芯片总览

> 自动扫描生成。覆盖主板当前加载的全部活跃砖、已禁用（N/O）砖与归档历史砖。

## 一、插槽类型统计

| 插槽类型 | 含义 | 砖块数 | 砖块名 |
|---|---|---|---|
| cpu | 中央处理器（计算/智能核心） | 1 | Agent 框架 |
| pcie | 高速扩展槽（I/O 与加速卡） | 5 | GUI 自动化、Ollama 向导代理、显示层、模型供应商、解析与结构化 |
| ram | 内存（运行时状态/缓存） | 5 | Token 用量、好感度引擎、对话缝合引擎、游戏生态、运行监控 |
| sata | 持久存储（数据落盘） | 2 | 会话记录、记忆引擎 |
| board | 板载逻辑（系统级服务） | 8 | 兜底防御、受控自我进化、定时任务引擎、对话、应用设置、文件处理、自主进化引擎、角色扮演引擎 |
| chip | 独立芯片（可插拔加密/存储组件） | 2 | 存储芯片+管理芯片、本机加解密 |

**共 6 种插槽类型**，活跃砖 23 块（不含系统主板）。

## 二、砖块明细（按插槽归类）

### 插槽：cpu（中央处理器（计算/智能核心））

#### Agent 框架  ·  `agent`

- **用途**：可换记忆 × 可扩工具 × 裁决引擎护航的 Agent 框架。默认开启自主规划引擎（先制定计划、分步执行、失败自动重规划），支持 ReAct 循环、内置工具集、运行时工具注册。
- **核心能力（capabilities）**：`agent_tools`, `register_tool`, `unregister_tool`, `agent_api`, `run_proactive_stream`, `push_bubble`, `memory_path`, `on_entity_deleted`
- **主要接口（11 个）**：
  - `/affinity`
  - `/ask-response`
  - `/characters`
  - `/characters/import`
  - `/characters/{character_id}`
  - `/dual-intervene`
  - `/dual-run`
  - `/dual-status`
  - `/events`
  - `/run`
  - `/tools`

### 插槽：pcie（高速扩展槽（I/O 与加速卡））

#### GUI 自动化  ·  `automation`

- **用途**：对外单一入口 automate，对内聚合桌面 GUI 感知/推理/执行能力。
- **核心能力（capabilities）**：无独立 capability，经 HTTP API 提供服务
- **主要接口**：无独立 HTTP 路由（能力经 capability 暴露）

#### Ollama 向导代理  ·  `ollama`

- **用途**：本机 Ollama 的全部引导能力：/guide 规格与安装检测、/health 运行检测、/catalog 模型目录（国内镜像+魔搭双来源）、/download 后台分片断点续传下载与进度轮询、/upload 拖拽 GGUF、/deploy 部署（Modelfile+高级参数）、/pull 与 /import-gguf 兼容旧路径。前端「引导」向导仅据此收集用户输入。
- **核心能力（capabilities）**：无独立 capability，经 HTTP API 提供服务
- **主要接口（13 个）**：
  - `/catalog`
  - `/deploy`
  - `/download`
  - `/download/active/{model_key}`
  - `/download/{job_id}`
  - `/download/{job_id}/cancel`
  - `/guide`
  - `/health`
  - `/import-gguf`
  - `/library`
  - `/pull`
  - `/pull-stream`
  - `/upload`

#### 显示层  ·  `display`

- **用途**：桌面壁纸与悬浮组件统一渲染层，基于 PyWebView + WebView2
- **核心能力（capabilities）**：`set_host`, `get_host`
- **主要接口（9 个）**：
  - `/layouts`
  - `/layouts/{name}`
  - `/settings`
  - `/wallpaper`
  - `/widgets`
  - `/widgets/{widget_id}/click-through`
  - `/widgets/{widget_id}/disable`
  - `/widgets/{widget_id}/enable`
  - `/widgets/{widget_id}/reload`

#### 模型供应商  ·  `models`

- **用途**：模型发现（/api/models/discover）与流式生成后端（provider 三协议），经 capabilities 暴露 create_stream / 文件能力供 chat 砖取用。
- **核心能力（capabilities）**：`create_stream`, `is_model_file_capable`, `file_handling_mode`, `model_supports_files`
- **主要接口（1 个）**：
  - `/models/discover`

#### 解析与结构化  ·  `parse`

- **用途**：识别文件类型并分发到文档/图片解析脚本，输出统一结构化数据（含图片 OCR）
- **核心能力（capabilities）**：无独立 capability，经 HTTP API 提供服务
- **主要接口（2 个）**：
  - `/{job_id}`
  - `/{job_id}/result`

### 插槽：ram（内存（运行时状态/缓存））

#### Token 用量  ·  `usage`

- **用途**：Token 用量明细台账、配额读取与超额拦截（数据落盘，依赖 settings 砖读配额）。
- **核心能力（capabilities）**：`check_quota`, `record_usage`
- **主要接口（1 个）**：
  - `/token-usage`

#### 好感度引擎  ·  `affinity`

- **用途**：双线好感度（base·dynamics·bond）/ 动态叠加 / 存储与结算，独立于角色扮演砖，供记忆与对话结算消费。
- **核心能力（capabilities）**：`affinity_api`, `on_entity_deleted`
- **主要接口**：无独立 HTTP 路由（能力经 capability 暴露）

#### 对话缝合引擎  ·  `stitching`

- **用途**：角色对话的语义检索 + 人格回调缝合；默认 mock 模式（零模型零下载），真实权重就位自动升级语义检索。
- **核心能力（capabilities）**：`stitch_api`
- **主要接口**：无独立 HTTP 路由（能力经 capability 暴露）

#### 游戏生态  ·  `game`

- **用途**：游戏性生态：经验系统（10阶×100级全局用户级、每日任务、好感度/累登系数、特殊任务）+ 星砂货币体系（登录/任务/游戏获取，商城购买道具消费）。
- **核心能力（capabilities）**：`award_chat_xp`, `award_plan_xp`, `has_item`, `unlock_item`, `purchase_item`
- **主要接口（8 个）**：
  - `/award`
  - `/checkin`
  - `/items`
  - `/purchase`
  - `/shop`
  - `/state`
  - `/status`
  - `/unlock-item`

#### 运行监控  ·  `monitor`

- **用途**：游戏进程检测与 Max/Eco 模式解析，经 capabilities 供 agent 读取，不直连 import。
- **核心能力（capabilities）**：`is_game_running`, `resolve_effective_mode`, `get_run_mode_config`
- **主要接口（2 个）**：
  - `/effective-mode`
  - `/game-running`

### 插槽：sata（持久存储（数据落盘））

#### 会话记录  ·  `conversations`

- **用途**：会话聊天记录落盘与恢复（/api/conversations，固定文件名 upsert 到「对话记录」分类）；底层经 storage 砖存储原语加密落盘。
- **核心能力（capabilities）**：无独立 capability，经 HTTP API 提供服务
- **主要接口（2 个）**：
  - `/conversations`
  - `/conversations/{conv_id}`

#### 记忆引擎  ·  `memory`

- **用途**：长期归档 / 核心记忆 / 向量语义检索 / Token 预算 / 短长期上下文压缩。
- **核心能力（capabilities）**：`memory_api`
- **主要接口**：无独立 HTTP 路由（能力经 capability 暴露）

### 插槽：board（板载逻辑（系统级服务））

#### 兜底防御  ·  `safety`

- **用途**：文件级保险库（AI 删除前自动归档副本，可检索恢复）+ 系统还原点状态汇总，构成系统级回滚与文件级找回的双层兜底。
- **核心能力（capabilities）**：无独立 capability，经 HTTP API 提供服务
- **主要接口（4 个）**：
  - `/status`
  - `/vault`
  - `/vault/clear`
  - `/vault/restore`

#### 受控自我进化  ·  `self_evolution`

- **用途**：AI 受控自注册工具 / 技能凝聚 / 行为观测自动提议：提案经静态校验 + 人审后生效。
- **核心能力（capabilities）**：`self_evo_tools`, `self_evo_skills`, `self_evo_observe`
- **主要接口（24 个）**：
  - `/audit`
  - `/observe`
  - `/patterns`
  - `/propose`
  - `/propose-skill`
  - `/scan-and-propose`
  - `/skills`
  - `/skills/audit`
  - `/skills/{name}/approve`
  - `/skills/{name}/delete`
  - `/skills/{name}/disable`
  - `/slots`
  - `/slots/close`
  - `/slots/open`
  - `/swaps`
  - `/swaps/{swap_id}`
  - `/swaps/{swap_id}/activate`
  - `/swaps/{swap_id}/approve`
  - `/swaps/{swap_id}/deactivate`
  - `/swaps/{swap_id}/dry-run`
  - `/tools`
  - `/tools/{tool_id}/approve`
  - `/tools/{tool_id}/delete`
  - `/tools/{tool_id}/disable`

#### 定时任务引擎  ·  `scheduler`

- **用途**：定时触发与主动推送：持久化任务、周期触发、经 agent 生成并 SSE 推送。
- **核心能力（capabilities）**：`create_job`, `list_jobs`, `delete_job`, `on_entity_deleted`
- **主要接口（3 个）**：
  - `/jobs`
  - `/jobs/{job_id}`
  - `/jobs/{job_id}/toggle`

#### 对话  ·  `chat`

- **用途**：流式对话入口（/api/chat、/api/chat/file-support）；经 models 砖 create_stream 取流、usage 砖做配额与记账。
- **核心能力（capabilities）**：无独立 capability，经 HTTP API 提供服务
- **主要接口（2 个）**：
  - `/chat`
  - `/chat/file-support`

#### 应用设置  ·  `settings`

- **用途**：应用设置的持久化与读取（外观、Token 限额等），独立落盘并复用加密能力。
- **核心能力（capabilities）**：`load_app_settings`
- **主要接口（1 个）**：
  - `/settings`

#### 文件处理  ·  `file`

- **用途**：接收上传文件并经应用层鉴权提供访问（移除无鉴权静态目录）
- **核心能力（capabilities）**：`read_upload`
- **主要接口（2 个）**：
  - `/upload`
  - `/{file_id}/content`

#### 自主进化引擎  ·  `evolution`

- **用途**：后台任务调度 / 闲置习惯推测 / 每日偏好简报 / 习惯学习 / 本地兜底（eco 模式）。
- **核心能力（capabilities）**：`evolution_api`
- **主要接口**：无独立 HTTP 路由（能力经 capability 暴露）

#### 角色扮演引擎  ·  `roleplay`

- **用途**：人设卡片 / 渲染 / 语气污染守卫（好感度已拆出为独立 affinity 砖）。
- **核心能力（capabilities）**：`roleplay_api`, `on_entity_deleted`
- **主要接口**：无独立 HTTP 路由（能力经 capability 暴露）

### 插槽：chip（独立芯片（可插拔加密/存储组件））

#### 存储芯片+管理芯片  ·  `storage`

- **用途**：主板自带存储组件：介质层（块读写/加密/压缩/索引）+ 管理芯片（配额/冷热分层/审计/冗余保险库/健康监测）
- **核心能力（capabilities）**：`encrypt_all_plaintext`, `decrypt_all_encrypted`, `load_app_settings`, `get_store`, `store_file`, `read_file_content`, `find_config_file`, `delete_file`, `index_existing_file`, `vault`, `recycle_bin`, `send_to_recycle_bin`, `archive_before_delete`, `restore_from_vault`, `list_vault`, `get_vault_stats`, `resolve_vault_root`, `delete_vault_entry`, `clear_vault`, `get_storage_quota`, `reserve_bytes`, `set_category_quota`, `set_global_quota`, `apply_cleanup_policy`, `set_tier_policy`, `set_category_tier`, `archive_file_to_vault`, `list_storage_events`, `storage_health`
- **主要接口（16 个）**：
  - `/breakdown`
  - `/categories`
  - `/categories/{name}`
  - `/categories/{name}/cleanup`
  - `/categories/{name}/quota`
  - `/categories/{name}/tier`
  - `/encryption`
  - `/events`
  - `/files`
  - `/files/{file_id}`
  - `/files/{file_id}/archive`
  - `/files/{file_id}/content`
  - `/health`
  - `/quota`
  - `/stats`
  - `/tiers/{tier}`

#### 本机加解密  ·  `crypto`

- **用途**：SM4 国密加解密，密钥绑定本机硬件指纹；凭恢复密钥可离线恢复。
- **核心能力（capabilities）**：`encrypt_bytes`, `decrypt_bytes`, `is_enabled`
- **主要接口（9 个）**：
  - `/decrypt`
  - `/decrypt-text`
  - `/encrypt`
  - `/encrypt-text`
  - `/encryption`
  - `/recovery-checksum`
  - `/recovery-key`
  - `/recovery-key/import`
  - `/status`

### 系统主板（非插槽，装配核心）

#### 主板

- **用途**：递归发现并加载所有砖块、装配路由、按插槽（总线）类型管理芯片生命周期与端点；提供健康检查 `/health`。
- **核心能力**：砖块发现/注册/路由装配、总线控制器管理。

## 三、芯片专表（bus_type = chip）

> 芯片为可随意插拔/整合的独立组件：丢入 `P.A.L.M_砖块/` 即自动注册，跨砖经 capabilities 与 `/api` 双通道协作。

#### 存储芯片+管理芯片  ·  类型：chip（独立芯片）

- **干啥用**：主板自带存储组件：介质层（块读写/加密/压缩/索引）+ 管理芯片（配额/冷热分层/审计/冗余保险库/健康监测）
- **功能（capabilities）**：`encrypt_all_plaintext`, `decrypt_all_encrypted`, `load_app_settings`, `get_store`, `store_file`, `read_file_content`, `find_config_file`, `delete_file`, `index_existing_file`, `vault`, `recycle_bin`, `send_to_recycle_bin`, `archive_before_delete`, `restore_from_vault`, `list_vault`, `get_vault_stats`, `resolve_vault_root`, `delete_vault_entry`, `clear_vault`, `get_storage_quota`, `reserve_bytes`, `set_category_quota`, `set_global_quota`, `apply_cleanup_policy`, `set_tier_policy`, `set_category_tier`, `archive_file_to_vault`, `list_storage_events`, `storage_health`
- **接口**：`/breakdown`、`/categories`、`/categories/{name}`、`/categories/{name}/cleanup`、`/categories/{name}/quota`、`/categories/{name}/tier`、`/encryption`、`/events`、`/files`、`/files/{file_id}`、`/files/{file_id}/archive`、`/files/{file_id}/content`、`/health`、`/quota`、`/stats`、`/tiers/{tier}`

#### 本机加解密  ·  类型：chip（独立芯片）

- **干啥用**：SM4 国密加解密，密钥绑定本机硬件指纹；凭恢复密钥可离线恢复。
- **功能（capabilities）**：`encrypt_bytes`, `decrypt_bytes`, `is_enabled`
- **接口**：`/decrypt`、`/decrypt-text`、`/encrypt`、`/encrypt-text`、`/encryption`、`/recovery-checksum`、`/recovery-key`、`/recovery-key/import`、`/status`

## 四、已禁用（N/O，暂不入主板）砖

按用户授权状态标记，已从主板发现范围移出（src 禁用或归档），正本保留于 `archive/未授权禁用/`。

- **声卡（音频板块）** · 插槽：pcie — 语音识别、语音合成(CosyVoice)、语音合成(GPT-SoVITS)、声纹识别 4 块子砖 + 声卡分组自身。原因：用户未授权，整体退出主板。
- **网卡** · 插槽：pcie — 网络出网出口（由 palm_sdk.net 门面承载）。原因：用户未授权，已归档。
- **沙箱执行** · 插槽：sata — 代码隔离执行 / 蜜罐 / 保险库 / 还原点。原因：用户未授权，已归档。

## 五、已归档（历史 / 非当前架构）砖

- **裁决引擎** · 插槽：board — 安全规则引擎（已拆分，消费者改直连护栏 palm_sdk.guardrail）。位置：`archive/裁决引擎_20260817`。
- **离线模式** · 插槽：— — 离线开关（禁用网卡），已下线。位置：`archive/offline_20260817`。
- **QwenTTS** · 插槽：— — 早期语音合成，已移除。位置：`archive/removed_qwentts_20260815`。

---

_生成方式：扫描 `P.A.L.M_砖块/` 下所有含 `src/__init__.py` 的砖，解析 `BrickManifest` 与 `capabilities`，并提取路由装饰器中的真实端点；缺失字段以正则兜底。_

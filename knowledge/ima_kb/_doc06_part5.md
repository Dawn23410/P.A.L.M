# P.A.L.M 从零复刻指南（深度扩充二：扩展路线图与附录）

> 承接扩充章 F-J。本部分给出：复刻后的扩展路线图、附录（术语索引/文件索引/时间线速查）。

---

## 扩充章 K：复刻后扩展路线图

### K.1 短期（复刻后 1-2 周）

| 项 | 说明 |
|---|---|
| 好感度解耦 | 好感度与角色扮演解绑（独立领域/独立服务） |
| 单元测试补全 | 遗留 1 项修复至 8/8 |
| GUI 部件修复 | glass_clock 等时间组件数据链路（桥接层） |
| 语音门面打磨 | 四引擎统一 facade 参数/降级路径 |
| 基准 CI 化 | 端点扫描/bench 接入每次提交 |

### K.2 中期（1-2 月）

| 项 | 说明 |
|---|---|
| agent 对标主流 | LangChain/OpenAI Agents/Claude Agent SDK 能力对比与补齐 |
| 游戏生态扩展 | 五子棋难度曲线/每日任务扩展/成就系统 |
| 外骨骼 Worker 扩展 | 更多小魔方（如浏览器魔方）/模型解耦（独立 provider） |
| 记忆层增强 | 向量检索精度提升（bge-m3 全量）/遗忘曲线参数化 |
| 多用户支持 | 声纹识别驱动的多用户个性化（voice.speaker 已就绪） |

### K.3 长期（3-6 月）

| 项 | 说明 |
|---|---|
| 移动端/多端同步 | 数据加密同步（云端备份可选） |
| 语音全本地化 | 本地 LLM（Qwen 系列）+ 本地 TTS 全链路离线 |
| 插件市场 | MCP/技能卡市场 |
| 社区生态 | 角色卡/技能包分享 |

---

## 扩充章 L：附录 A——术语索引

| 术语 | 篇目 | 定义 |
|---|---|---|
| 终极架构 | 03 | ports/domain/services/adapters/bootstrap + _core 分层 |
| 服务容器 | 03 | container.get(名).capability(键)，缺失归一 None |
| Port 契约 | 03 | 15 个 ABC 定义能力契约 |
| 裁决 5 档 | 04 | 死线/严格/宽松/AI 兜底/白名单 |
| fail-closed | 04 | 未配置即拒绝（裁决/网卡/沙箱） |
| 双线好感度 | 04 | 基准线 base + 动态线 dynamics |
| 双幂律衰减 | 04 | 时间+访问双幂律衰减的记忆权重 |
| 缝合引擎 | 04 | 检索式对话兜底（零联网） |
| 心智魔方 Boss | 05 | 纯聊天不碰工具 |
| 外骨骼 Worker | 05 | 只干活无性格 |
| EXO 协议 | 05 | ||EXO|| 委派标记 |
| 五位控制码 | 05 | D1-D5 结构化控制码 |
| 安全三拆分 | 05 | 工具闸门/沙箱隔离/通信审计 |
| 吝啬制 | 05 | 好感度日常小数步进 |
| 星砂 | 00 | 游戏货币 |
| 保险库 vault | 04 | 删除拦截可恢复 |
| 网卡门面 | 03 | 唯一出网出口 |
| mock/live | 05 | 零落盘/加密落盘双模式 |
| 每界面一文件 | 00 | 前端 12 页策略 |
| 先归档不删 | 01 | 归档治理原则 |

---

## 扩充章 M：附录 B——文件索引（复刻对照）

### M.1 palm/ 核心文件索引

| 路径 | 职责 | 篇目 |
|---|---|---|
| palm/bootstrap/app.py | 装配 14 服务 | 03 |
| palm/_core/container.py | 服务容器 | 03 |
| palm/_core/guardrail/engine.py | 裁决 5 档 | 03 |
| palm/_core/net/__init__.py | 网卡门面 | 03 |
| palm/_core/eventbus.py | 事件总线 | 03 |
| palm/_core/permission.py | 权限引擎 | 04 |
| palm/_core/redundancy/vault.py | 文件保险库 | 04 |
| palm/ports/ports/*.py | 15 Port ABC | 03 |
| palm/services/agent/core.py | Agent 核心 | 04 |
| palm/services/chat/chat_service.py | 会话服务 | 04 |
| palm/domain/roleplay/*.py | 角色/好感度/游戏 | 04 |
| palm/domain/memory/*.py | 记忆层 | 04 |
| palm/services/ops/*.py | 调度/计量 | 04 |
| palm/adapters/storage/pool.py | 存储池 | 04 |
| palm/adapters/gui/automation_orchestrator.py | GUI 自动化 | 04 |

### M.2 mentalcore/ 核心文件索引

| 路径 | 职责 | 篇目 |
|---|---|---|
| mentalcore/core.py | MentalCore 核心 | 05 |
| mentalcore/transport.py | 五位控制码 | 05 |
| mentalcore/persona_card.py | 角色卡 | 05 |
| mentalcore/faces/*.py | 六面 | 05 |
| mentalcore/middleware/inject.py | 动态注入 | 05 |
| mentalcore/middleware/split.py | 回复拆分 | 05 |
| mentalcore/exo/coordinator.py | 双 Agent 协调 | 05 |
| mentalcore/exo/core.py | WorkCore | 05 |
| mentalcore/exo/protocol.py | Worker 协议 | 05 |
| mentalcore/exo/cubes/*.py | 7 小魔方 | 05 |

---

## 扩充章 N：附录 C——时间线速查卡

```
07-31 克隆 → 回归原生 FC
08-01 合规五条底线 / 双系统架构
08-02 双引擎回退 / 权限引擎 / P2-P6
08-03 双线好感度 / 商城 / 保险库 / GSV 自包含
08-04 自主进化 / 神砖拆三 / dev 脚本
08-05 自我进化全链路 + AI 兜底裁决
08-06 主板架构 P1-P6
08-07 qwen_tts + display 砖
08-09 语音子系统
08-10 存储 M0-M5 / 双 Agent / 情绪五因子 / 基准
08-11 归档治理 + GUI 世界模型
08-12 GUI 执行器 + UIA + OCR
08-13 GUI 推理中枢 + Web 自动化
08-14 缝合引擎封砖 / 运行时层 / 终极主板
08-16 30 砖拆分 / palm_sdk / 网关 / 163 端点全绿
08-18 入仓 + ports 契约层 / 终极架构落地 / SDK 退役
08-19 前端 12 页 / C 盘大清理
08-20 mentalcore 心智魔方 + 外骨骼入库（终态）
```

---

## 扩充章 O：附录 D——验收总表（复刻完成判定）

| 域 | 验收项 | 基线 |
|---|---|---|
| 架构 | 分层/依赖单向/容器/契约 | lint + 契约测试 |
| 对话 | 全链路（工具/规划/反思/压缩） | e2e 无 bug |
| 角色 | 双线好感度/动态/开场白/技能导入 | 功能测试 |
| 记忆 | 分层/只存事实/衰减 | 基准对照 |
| 游戏 | 星砂/等级/每日/对局 | 功能测试 |
| 进化 | 闲置/简报/推送/裁决 | 功能测试 |
| 语音 | 四引擎 facade/降级 | 冒烟 |
| GUI | automate/L0-L3/fail-closed | 功能测试 |
| 安全 | 裁决/权限/网卡/保险库 | 审计 + 红队 |
| 计量 | 真实账本/配额 | 数据核对 |
| mentalcore | 18 控制码/EXO/selftest | 全过 |
| 前端 | 12 页/SSE/ask_user | e2e |
| 质量 | 端点扫描/单测 | 全绿/8-8 |

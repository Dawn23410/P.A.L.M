# P.A.L.M 从零复刻指南（深度扩充十二：完整时间规划与最终清单）

> 承接扩充章 CCC-FFF。本部分给出：复刻完整时间规划（细化到任务）、最终交付清单、以及复刻全流程总结。

---

## 扩充章 GGG：复刻完整时间规划（细化）

### GGG.1 第 1 天：环境与骨架

```
上午：
  1. 安装 Python 3.11+ / Node 18+
  2. 创建目录骨架（palm/mentalcore/frontend/Data/archive/docs）
  3. 创建 venv_runtime
  4. 安装基础依赖（fastapi/uvicorn/pydantic/pyyaml/httpx）
下午：
  5. 复制 .env.example → .env
  6. 创建 Data/ 子目录（对话记录/记忆/角色/游戏/配置/审计/存储池）
  7. 放置示例角色卡（mengyao.json）
  8. 验证：python 可导入 fastapi
里程碑：环境就绪
```

### GGG.2 第 2-3 天：基础设施（_core）

```
第 2 天：
  1. paths.py（路径解析）
  2. config.py（配置加载）
  3. logging.py（日志）
  4. container.py（服务容器）
  5. eventbus.py（事件总线）
第 3 天：
  6. transport.py（传输/控制码）
  7. guardrail/（engine + rules）
  8. net/（网卡门面）
  9. permission.py（权限引擎）
  10. redundancy/（vault + recycle）
里程碑：基础设施可用（单元测试过）
```

### GGG.3 第 4 天：契约层（ports）

```
  1. 15 个 Port ABC（agent/audio/crypto/device/display/guard/gui/memory/model/ops/persist/storage/sys/tool/ui）
  2. 总出口（聚合导入）
  3. 契约验证脚本（可独立 import + ABC 强制）
里程碑：15 Port 契约全过
```

### GGG.4 第 5 天：适配器层

```
  1. storage/pool.py（文件池 6 接口）
  2. io/app_settings.py（设置）
  3. crypto/（keystore + operations）
  4. model/（provider + model_router）
  5. gui/automation_orchestrator.py（入口骨架）
里程碑：适配器可读写（存储/设置/加密冒烟）
```

### GGG.5 第 6-7 天：领域层

```
第 6 天：
  1. roleplay/（character/persona/affinity/affection/dynamics/pollution/state/xp/game/import）
第 7 天：
  2. memory/（core/archived/vector/writer/budget/weights）
  3. planning/（planner/schemas）
  4. evolution/（proactive/idle/digest/habit/fallback/background）
里程碑：领域对象可创建（角色/记忆/计划/进化状态）
```

### GGG.6 第 8-9 天：服务层 + 装配

```
第 8 天：
  1. ops/（engine/cron/mode/token_usage/token_ledger）
  2. chat/（chat_service/conversation_store/hub/engine）
第 9 天：
  3. agent/（core + mixins + native + plan + react + tools + persona + gate + trace）
  4. evolution/（registry/observer/gate/...）
  5. bootstrap/app.py（14 服务装配）
里程碑：build_app() 幂等装配 14 服务
```

### GGG.7 第 10 天：网关 + 对话联调

```
  1. FastAPI 路由（chat/characters/affinity/usage/events/...）
  2. SSE 事件流
  3. mock 模型对话联调（文本流/工具/ask_user）
  4. 端点冒烟
里程碑：对话全链路（mock）跑通
```

### GGG.8 第 11 天：mentalcore

```
  1. pip install -e mentalcore
  2. 配置 .env（API_KEY）
  3. selftest 全过
  4. 六面 + 双中间件
  5. 18 控制码
  6. build_exo + make_broker
  7. exo.selftest 4 测全过
里程碑：心智核心就绪
```

### GGG.9 第 12 天：前端

```
  1. ui/ 共享基础（api.js/base.css/chart.js/dom.js/theme.css）
  2. 对话页（SSE 流式 + ask_user）
  3. 系统总览/用量/设置
  4. 游戏/保险库/监控
  5. 其余页面
里程碑：12 页加载 + 对话可视化完整
```

### GGG.10 第 13-14 天：验收与发布

```
第 13 天：
  1. 端点扫描（163 无 500）
  2. 单元测试（8/8）
  3. e2e（8012）
  4. 安全验收（裁决/权限/网卡/保险库/红队）
第 14 天：
  5. 基准（bench_50/100）
  6. 归档备份
  7. 验收记录（全过）
  8. 发布
里程碑：复刻完成
```

---

## 扩充章 HHH：最终交付清单（复刻版）

| 交付物 | 说明 | 验收 |
|---|---|---|
| 源码 | palm + mentalcore + frontend | 目录核对 |
| 配置 | .env + settings.json | 启动成功 |
| 测试 | 端点/单测/e2e/selftest | 全过 |
| 基准 | bench 报告 | 达标 |
| 安全 | 审计 + 红队 | 全过 |
| 文档 | 部署/运维/使用 | 完整 |
| 备份 | 归档快照 | 可恢复 |
| 验收记录 | 全量清单 | 全过 |

---

## 扩充章 III：复刻全流程总结

```
1. 理解（读 00/01/02：为什么）
2. 设计（读 03/04/05：怎么做）
3. 施工（按本篇：14 天）
4. 验收（全量清单）
5. 发布（归档 + 文档）
6. 演进（路线图）
```

**复刻的本质**：不是抄代码，而是重建"架构 + 功能 + 安全 + 心智"的完整系统——本系列 10 万+ 字文档让这一切有据可依。

---

## 扩充章 JJJ：最终宣言（复刻篇终章）

P.A.L.M 的知识已完整沉淀。本系列 7 篇文档是它的"完整复刻说明书"：

- 是什么（00）、如何走来（01）、谁构建（02）。
- 如何组织（03）、如何实现（04）、如何思考（05）。
- 如何重建（06）。

凭本系列，任何开发者（或 AI）可在 14 天内重建功能等价的 P.A.L.M，并在此基础上继续演进。

**复刻完成，即传承开始——P.A.L.M 永不丢失。**

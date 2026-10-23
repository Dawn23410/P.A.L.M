# P.A.L.M 从零复刻指南（深度扩充：模板集/验收用例/文件清单）

> 承接《从零复刻指南》正文。本部分提供：关键代码模板（可直接改写）、分模块验收用例（可执行清单）、完整文件清单（对照表）、复刻顺序甘特视图。

---

## 扩充章 A：关键代码模板集

### A.1 服务注册模板（bootstrap 内）

```python
def _register(name, impl, capabilities=None):
    container.register(name, impl, capabilities)
    _READY[name] = impl

# 适配器层（先注册，供上层消费）
try:
    from palm.adapters.storage import pool as _storage_pool
    _register("storage", _storage_pool, {
        "store_file": getattr(_storage_pool, "store_file", None),
        "read_file_content": getattr(_storage_pool, "read_file_content", None),
        "delete_file": getattr(_storage_pool, "delete_file", None),
    })
except Exception as exc:  # 底座缺失降级
    print(f"[bootstrap] storage 注册失败（降级）: {exc}")
```

**要点**：每个服务 try/except 降级；capabilities 用 getattr 容错（实现缺方法时注册 None）。

### A.2 业务取用模板（业务模块内）

```python
from palm._core.container import container

def store_something(key, data):
    handle = container.get("storage")
    if handle is None:          # 缺失归一：判空降级
        return None
    store = handle.capability("store_file")
    if store is None:           # 能力缺失：判空降级
        return None
    return store(key, data)
```

### A.3 裁决接入模板（工具执行链）

```python
def execute_with_safety(tool_name, ctx):
    cap = get_guardrail_capability()   # guardrail 门面
    decision = cap("tool_call", ctx)   # 5 档裁决
    if decision.action == "deny":
        return {"blocked": True, "reason": decision.reason}
    if decision.action == "ask":
        # 发 ask_user 事件（带 id），超时 30s 默认 deny
        answer = question_hub.ask(decision.ask_message, timeout_ms=30_000)
        if not answer: return {"blocked": True, "reason": "ask timeout"}
    # 执行 + 事件下发 + 结果回注
```

### A.4 网卡出网模板（唯一出口）

```python
from palm._core.net import get_network_executor

def fetch_page(url):
    execute = get_network_executor()      # 无网卡注册返回 None
    if execute is None:
        raise NetworkForbidden()          # fail-closed
    return execute("GET", url, timeout=10)
```

### A.5 双线好感度结算模板

```python
def settle_affinity(character_id, interaction_quality, current_tier):
    # 档位增速约束：按真实当前档位
    rate = tier_rate(current_tier)        # 高等级增速放缓
    base_delta = interaction_quality * rate
    dyn_delta = interaction_quality * DYNAMICS_COEF
    store.update(character_id, base=+base_delta, dynamics=+dyn_delta)
    # 动态线回归：会话结束向基准线回归
```

### A.6 EXO 委派模板（Boss → Worker）

```python
# Boss 侧（MentalCore.exo_broker）
def on_exo_marker(goal, context):
    thread = threading.Thread(target=worker_run, args=(goal, context))
    thread.daemon = True
    thread.start()          # 后台拉起，不阻塞 Boss 回复

# Worker 侧完成回传
def worker_done(result):
    boss.receive({"exo_result": result}, "外骨骼完成")
```

---

## 扩充章 B：分模块验收用例（可执行清单）

### B.1 容器与装配

| # | 用例 | 预期 |
|---|---|---|
| 1 | build_app() 两次调用 | 幂等（不重复注册） |
| 2 | container.get("storage") | 非 None（正常装配） |
| 3 | container.get("不存在") | None |
| 4 | handle.capability("store_file") | 可调用 |
| 5 | 依赖缺失模拟 | 打印降级，其余服务正常 |

### B.2 对话链路

| # | 用例 | 预期 |
|---|---|---|
| 6 | 发消息 → 流式响应 | text 事件序列 |
| 7 | 角色开启 → 开场白 first_mes | 会话首条为开场白 |
| 8 | 角色关闭 → 无角色语气 | 三处注入点均剥离 |
| 9 | 工具调用 | tool_call 事件前置 + 结果回注 |
| 10 | ask_user 触发 | 事件带 id，应答后继续 |
| 11 | 长对话 50 轮 | 上下文压缩生效（token 受控） |

### B.3 安全

| # | 用例 | 预期 |
|---|---|---|
| 12 | 未授权敏感操作 | ask 询问，拒绝则 deny |
| 13 | 裁决 AI 档无回调 | fail-closed deny |
| 14 | 无网卡出网 | NetworkForbidden |
| 15 | 删除文件 | 先入 vault 可恢复 |
| 16 | 联网工具 | 必须过裁决（无绕过） |

### B.4 计量

| # | 用例 | 预期 |
|---|---|---|
| 17 | 对话完成 | provider 真实量入账本 |
| 18 | 估算量 | 不入账、不显示 |
| 19 | 超配额 | check_quota 拦截 |

### B.5 游戏与好感度

| # | 用例 | 预期 |
|---|---|---|
| 20 | 聊天完成 | award_chat_xp 经验增加 |
| 21 | 规划完成 | award_plan_xp 经验增加 |
| 22 | 星砂购买道具 | 货币扣减 + 道具入库 |
| 23 | 好感度档位增速 | 高等级增速放缓 |
| 24 | 每日任务跨天 | 计数重置 + 连登更新 |

### B.6 进化

| # | 用例 | 预期 |
|---|---|---|
| 25 | 闲置超时 | 触发闲置推测 |
| 26 | 定时到点 | 每日简报生成 |
| 27 | 主动推送 | 经裁决事件审计 |

### B.7 mentalcore

| # | 用例 | 预期 |
|---|---|---|
| 28 | selftest | 全过 |
| 29 | exo.selftest | 4 测全过 |
| 30 | 18 控制码 | 全部可用 |
| 31 | mock 模式 | 零落盘 |
| 32 | EXO 委派 | Worker 执行 + 回传 Boss |

### B.8 GUI

| # | 用例 | 预期 |
|---|---|---|
| 33 | automate(软件, 意图) | L0 UIA 执行 |
| 34 | UIA 不可用 | L2 OCR 降级 |
| 35 | LLM 兜底未配置 | fail-closed 拒绝 |
| 36 | 辅助模式 | ensure_off 后正常 |

---

## 扩充章 C：完整文件清单对照（复刻核对）

### C.1 palm/_core/（20 模块）

config.py、container.py、emotion.py、eventbus.py、gateway.py、guardrail/（engine.py+rules.py）、housekeeping.py、interop.py、logging.py、net/、paths.py、permission.py、redundancy/（recycle.py+vault.py）、schemas/（chat.py）、security.py、token_estimate.py、tooling.py、transport.py、watchdog.py + __init__.py/__pycache__。

### C.2 palm/ports/ports/（15 ABC）

agent_port、audio_port、crypto_port、device_port、display_port、guard_port、gui_port、memory_port、model_port、ops_port、persist_port、storage_port、sys_port、tool_port、ui_port + __init__.py。

### C.3 palm/adapters/（6 组）

storage/（pool.py）、io/（app_settings.py）、crypto/（keystore.py+operations.py）、model/（provider.py+model_router.py）、gui/（automation_orchestrator.py）、display/。

### C.4 palm/domain/（4 子域）

roleplay/（11 文件）、memory/（9 文件）、planning/（2 文件）、evolution/（6 文件）。

### C.5 palm/services/（4 组）

agent/（22+ 文件）、chat/（8 文件）、evolution/（9 文件）、ops/（9 文件）。

### C.6 palm/bootstrap/

app.py（140 行）。

### C.7 mentalcore/mentalcore/

config.py、core.py、crypto_provider.py、exo/（23 文件）、faces/（7 文件）、llm.py、logging_setup.py、middleware/（2 文件）、netcard.py、persona_card.py、secure_config.py、selftest.py、semantic_memory.py、transport.py + 顶层 mentalcore/（pyproject.toml、README.md、LICENSE、tests/）。

### C.8 frontend/

12 html + ui/（5 文件）。

---

## 扩充章 D：复刻顺序甘特视图（依赖驱动）

```
第 1-2 天  环境/骨架/_core 基础设施（paths→config→container→guardrail→net）
第 3 天    ports 15 ABC + 契约验证
第 4 天    适配器（storage/crypto/models/io）
第 5-6 天  领域层（roleplay/memory/planning/evolution）
第 7-8 天  服务层（chat/agent/ops/evolution）+ 装配层 + FastAPI 网关
第 9 天    对话全链路联调（mock 模型）
第 10 天   mentalcore（魔方 + 外骨骼 + 控制码 + selftest）
第 11 天   前端 12 页 + SSE + ask_user
第 12 天   游戏/进化/语音（可选依赖）接入
第 13 天   安全审计 + 端点扫描 + 基准
第 14 天   验收清单全过 → 复刻完成
```

---

## 扩充章 E：复刻常见失败模式与对策

| 失败模式 | 症状 | 对策 |
|---|---|---|
| 越层依赖 | import 循环/lint 报错 | 严格依赖单向，domain 不碰 services |
| 容器缺失未判空 | AttributeError: NoneType | capability 调用前判空 |
| 空 thought 崩溃 | 规划引擎 NoneType | 事件归一化（空值转 None） |
| thinking 400 | Kimi 续轮失败 | 携带 reasoning_content |
| ask_user 死锁 | 流程卡住 | id + 即时推送 |
| 文件锁 | 设置保存失败误报 CORS | 重试 + 错误分类 |
| LF 换行 | bat 误执行 | CRLF |
| mock 落盘 | 测试污染 | persist=False + sem=None |
| 裁决旁路 | 联网未过裁决 | 网卡门面强制 |
| 删除不可逆 | 数据丢失 | vault 拦截 |

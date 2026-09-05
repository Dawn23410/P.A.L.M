# P.A.L.M 从零复刻指南（深度扩充三：完整模板/目录树/依赖清单）

> 承接扩充章 F-O。本部分给出：可直接改写的完整代码模板（容器/裁决/网卡/装配）、复刻目标目录树、依赖清单、以及复刻检查表（最终版）。

---

## 扩充章 P：完整代码模板（可直接改写）

### P.1 容器最小实现（container.py 全量模板）

```python
"""库内服务容器：bootstrap 装配的唯一出口。"""
from typing import Any, Callable


class ServiceHandle:
    """服务句柄：能力经 capability(键) 取用，缺失归一 None。"""

    def __init__(self, name: str, impl: Any,
                 capabilities: dict[str, Callable] | None = None):
        self._name = name
        self._impl = impl
        self._capabilities = capabilities or {}

    @property
    def name(self) -> str:
        return self._name

    @property
    def impl(self) -> Any:
        return self._impl

    @property
    def capabilities(self) -> dict:
        """显式注册的能力 + 实现对象的方法属性（方法名即能力键）。"""
        merged = dict(self._capabilities)
        for attr in dir(self._impl):
            if attr.startswith("_"):
                continue
            value = getattr(self._impl, attr)
            if callable(value):
                merged.setdefault(attr, value)
        return merged

    def capability(self, name: str):
        if name in self._capabilities:
            return self._capabilities[name]
        return getattr(self._impl, name, None)


class Container:
    """按名注册/取用服务的轻量容器。"""

    def __init__(self):
        self._services: dict[str, ServiceHandle] = {}

    def register(self, name, impl, capabilities=None) -> ServiceHandle:
        handle = ServiceHandle(name, impl, capabilities)
        self._services[name] = handle
        return handle

    def get(self, name: str) -> ServiceHandle | None:
        return self._services.get(name)

    def all(self) -> list[ServiceHandle]:
        return list(self._services.values())

    def names(self) -> list[str]:
        return sorted(self._services)


container = Container()
registry = container  # 兼容别名
```

### P.2 裁决引擎最小模板（guardrail 5 档）

```python
class Profile(str, Enum):
    HARDLINE = "hardline"    # 默认拒绝；warn 升级 deny
    STRICT = "strict"        # 默认询问
    LOOSE = "loose"          # 默认提醒
    AI = "ai"                # AI 回调（未配置 fail-closed）
    WHITELIST = "whitelist"  # 默认拒绝；仅 allow 放行


@dataclass
class Decision:
    action: str             # allow/deny/ask/warn
    reason: str = ""
    ask_message: str = ""
    ask_timeout_ms: int = 30_000
    ask_on_timeout: str = "deny"


def adjudicate(event_type, ctx, profile, rules) -> Decision:
    for rule in sorted(rules, key=lambda r: -r.priority):
        if rule.event_type == event_type and all(cond(ctx) for cond in rule.conditions):
            return rule_action_to_decision(rule)
    # 无命中 → Profile 兜底
    if profile == Profile.HARDLINE: return Decision("deny", "hardline default")
    if profile == Profile.STRICT: return Decision("ask", "strict default")
    if profile == Profile.LOOSE: return Decision("warn", "loose default")
    if profile == Profile.AI:
        if ai_callback is None: return Decision("deny", "ai fail-closed")
        return ai_callback(event_type, ctx)
    return Decision("deny", "whitelist default")
```

### P.3 网卡门面最小模板（net）

```python
class NetworkForbidden(RuntimeError): ...

_executor = None

def register_card(executor):
    global _executor
    _executor = executor

def get_network_executor():
    return _executor

def network_request(method, url, **kw):
    if _executor is None:
        raise NetworkForbidden("未挂载网卡：外网请求被拒绝（fail-closed）")
    if is_loopback(url):
        pass  # 回环放行（本地模型服务）
    return _executor(method, url, **kw)
```

### P.4 装配模板（bootstrap/app.py 骨架）

```python
def build_app():
    if container.names():
        return ContainerProxy(container)   # 幂等

    # 适配器层（try/except 降级注册）
    try:
        from palm.adapters.storage import pool as sp
        _register("storage", sp, {
            "store_file": getattr(sp, "store_file", None),
            "read_file_content": getattr(sp, "read_file_content", None),
            "delete_file": getattr(sp, "delete_file", None),
        })
    except Exception as exc:
        print(f"[bootstrap] storage 注册失败（降级）: {exc}")
    # ... settings/crypto/models/gui 同理

    # 服务层
    _register("usage", token_usage, {"check_quota": token_usage.check_quota})
    _register("usage_ledger", token_ledger)
    _register("scheduler", engine)
    _register("conversations", conversation_store)
    _register("game", game_service, {"award_chat_xp": ..., "purchase_item": ...})
    _register("affinity", affinity_engine)
    _register("roleplay", character, {"roleplay_api": character})
    _register("memory", memory_writer, {"memory_api": memory_writer})
    _register("evolution", evolution_registry, {"evolution_api": ...})
    _register("agent", agent_core)
    return ContainerProxy(container)
```

---

## 扩充章 Q：复刻目标目录树（完整）

```
P.A.L.M/
├── palm/
│   ├── __init__.py
│   ├── _core/
│   │   ├── __init__.py
│   │   ├── config.py / container.py / emotion.py / eventbus.py / gateway.py
│   │   ├── guardrail/（engine.py + rules.py）
│   │   ├── housekeeping.py / interop.py / logging.py
│   │   ├── net/（__init__.py）
│   │   ├── paths.py / permission.py
│   │   ├── redundancy/（recycle.py + vault.py）
│   │   ├── schemas/（chat.py）
│   │   ├── security.py / token_estimate.py / tooling.py / transport.py / watchdog.py
│   ├── adapters/
│   │   ├── storage/（pool.py）
│   │   ├── io/（app_settings.py）
│   │   ├── crypto/（keystore.py + operations.py）
│   │   ├── model/（provider.py + model_router.py）
│   │   ├── gui/（automation_orchestrator.py）
│   │   └── display/
│   ├── bootstrap/（app.py）
│   ├── domain/
│   │   ├── roleplay/（character/persona/affinity_engine/affinity_store/affection/
│   │   │             dynamics_engine/pollution_guard/game_service/xp/state/import_skill）
│   │   ├── memory/（core_memory/archived_memory/vector_memory/memory_writer/
│   │   │           token_budget/weights/base/memory）
│   │   ├── planning/（planner.py + schemas.py）
│   │   └── evolution/（proactive/idle_orchestrator/offline_digest/habit_engine/
│   │                   fallback_engine/background_tasks）
│   ├── ports/
│   │   └── ports/（15 个 *_port.py）
│   └── services/
│       ├── agent/（22+ 文件 + tools/ 9 文件）
│       ├── chat/（8 文件）
│       ├── evolution/（9 文件）
│       └── ops/（9 文件）
├── mentalcore/
│   ├── pyproject.toml / README.md / LICENSE
│   ├── mentalcore/
│   │   ├── config.py / core.py / crypto_provider.py / llm.py / logging_setup.py
│   │   ├── netcard.py / persona_card.py / secure_config.py / selftest.py
│   │   ├── semantic_memory.py / transport.py
│   │   ├── faces/（base/emotion/memory/persona/rhythm/storage/weave）
│   │   ├── middleware/（inject.py + split.py）
│   │   └── exo/（23 文件 + cubes/ 7 文件）
│   └── tests/
├── frontend/
│   ├── index.html / chat.html / characters.html / files.html / game.html
│   ├── mcp.html / memory.html / monitor.html / overview.html / scheduler.html
│   ├── settings.html / usage.html
│   └── ui/（api.js/base.css/chart.js/dom.js/theme.css）
├── Data/（运行数据：对话记录/记忆/角色/游戏/配置/审计/存储池）
├── archive/（归档，gitignore）
├── docs/
├── .env / .env.example
└── dev.py / dev.bat
```

---

## 扩充章 R：依赖清单（最小集）

| 依赖 | 用途 | 必需 |
|---|---|---|
| fastapi + uvicorn | HTTP 服务 | 是 |
| pydantic | schema 校验 | 是 |
| pyyaml | guardrail 规则 | 是 |
| httpx | 网卡执行器/模型客户端 | 是 |
| openai（兼容） | 模型流式 | 是 |
| chromadb | 向量记忆（live） | 否 |
| onnxruntime | bge INT8 检索 | 否 |
| uiautomation/pywin32 | GUI 自动化 | 否 |
| torch cu128 | CosyVoice（独立 venv） | 否 |
| soundfile | 音频 | 否 |
| ollama | bge-m3 嵌入 | 否 |

---

## 扩充章 S：复刻检查表（最终版，30 项）

**架构（1-6）**：
1. 分层目录齐全（ports/domain/services/adapters/bootstrap/_core）。
2. 15 Port ABC 可独立 import。
3. container 注册/取用/缺失归一。
4. build_app 幂等装配 14 服务。
5. 依赖单向（lint 校验）。
6. 业务零注册零全局状态。

**功能（7-18）**：
7. 对话流式（text/thought/tool_call/ask_user/verdict 事件）。
8. 工具链（匹配→校验自愈→裁决→授权→执行→回注）。
9. 规划引擎（计划→执行→失败重规划）。
10. 反思闸门（回答成立性）。
11. 上下文压缩（摘要化）。
12. 角色卡 + 开场白 + 技能导入。
13. 双线好感度 + 档位增速。
14. 游戏（星砂/等级/每日/对局）。
15. 记忆分层 + 只存事实 + 衰减。
16. 进化（闲置/简报/习惯/推送 + 裁决）。
17. 语音四引擎 facade + 降级。
18. GUI automate + L0-L3 + fail-closed。

**安全（19-24）**：
19. 裁决 5 档 + AI 档 fail-closed。
20. 权限引擎（须授权）。
21. 网卡门面（唯一出口）。
22. 保险库（删除可恢复）。
23. ask_user 闭环（id + 即时推送）。
24. 计量（provider 真实账本）。

**mentalcore（25-28）**：
25. 六面 + 双中间件。
26. 18 控制码。
27. Boss/Worker + EXO 协议 + 5 小魔方。
28. selftest/exo.selftest 全过。

**质量（29-30）**：
29. 端点扫描无 500；单元测试 8/8；e2e 无 bug。
30. 前端 12 页 + SSE + ask_user 完整。

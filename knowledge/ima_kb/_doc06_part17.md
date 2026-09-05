
# P.A.L.M 从零复刻指南（99% 补全章：宿主层复刻与真实代码引用）

> 本章为复刻篇补全：修正依赖管理表述、补入宿主层复刻指引、并给出"以真实源码为准"的复刻引用表。

---

## 补全章 A：依赖管理修正（无冻结清单）

### A.1 事实

当前工作区**无 requirements.txt**（仅 mentalcore/pyproject.toml 为唯一声明源）。依赖以 venv + pip 命令安装为主。

### A.2 复刻安装修正

```
venv_runtime（主运行时）：
  pip install fastapi uvicorn[standard] pydantic pyyaml httpx
  pip install openai            # OpenAI 兼容客户端
  pip install -e palm           # palm 库（无 pyproject 则复制源码 + 手动安装依赖）
  pip install -e mentalcore     # 心智核心（pyproject.toml 声明）

venv_cosyvoice（CosyVoice，可选）：
  pip install torch --index-url https://download.pytorch.org/whl/cu128
  pip install soundfile wetext==0.0.4
  # vendored cosyvoice/matcha 源码进 site-packages

venv_gsv（GPT-SoVITS，可选）：
  # 自包含 runtime + 模型（7-Zip 解包）

.venv-qwen-tts / .venv-stt（可选）：
  # serve.py 自动拉起 / STT 独立子进程
```

**注意**：版本以"能通过验收"为准（无锁定约束）；palm 库依赖以源码 import 实际所需为准。

---

## 补全章 B：宿主层复刻指引（UiPort 契约驱动）

### B.1 宿主层职责

```
backend/app/（复刻者自行实现）：
  1. FastAPI 应用（uvicorn :8005）
  2. 路由：按 UiPort.endpoints() 契约（各 screen 声明其依赖端点）
  3. CORS 中间件（localhost:5173/8000 等）
  4. SSE 事件流（/api/events：text/thought/tool_call/ask_user/verdict）
  5. pywebview 桥接（window.pywebview.api 封装）
  6. 装配：from palm.bootstrap.app import build_app
```

### B.2 端点实现示例（按 UiPort 契约）

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from palm.bootstrap.app import build_app
from palm._core.container import container

app = FastAPI()
build_app()   # 幂等装配 14 服务

app.add_middleware(CORSMiddleware,
                   allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])

@app.get("/api/system")
def system():
    return {"services": [h.name for h in container.all()]}

@app.post("/api/chat")
async def chat(req: dict):
    # 经容器取 chat/agent 服务 → 流式事件（SSE）
    ...
```

### B.3 端点验收基线

- 宿主层端点须捕获异常（不裸崩 500），依赖缺失降级 503。
- 历史 163 端点为旧体系实录，复刻宿主层以"功能可用"为准（UiPort 契约覆盖）。

---

## 补全章 C：真实代码引用表（复刻者按此核对）

| 复刻项 | 真实位置 | 关键内容 |
|---|---|---|
| 15 Port | palm/ports/ports/*.py | 55 个抽象方法（见 03 篇补全章 A） |
| 裁决规则模型 | palm/_core/guardrail/rules.py | ConditionOp 15 算子/Condition/AskConfig/Rule |
| 工具基座 | palm/_core/tooling.py | ToolSpec/contextvars/重试参数/execute_tool_with_safety |
| 工具注册 | palm/services/agent/tool_base.py | register_builtin_tools 7 组工具 |
| Agent 请求 | palm/services/agent/schemas.py | AgentRunRequest/AgentEvent |
| 完成闸门 | palm/services/agent/completion_gate.py | register_rule + 3 内置规则 |
| 经验等级 | palm/domain/roleplay/xp.py | STAGE_COUNT=10/LEVELS_PER_STAGE=100/BASE_EXP=1000/chat_xp 公式 |
| 每日任务 | palm/domain/roleplay/xp.py | DAILY_TASKS 4 项含 login/REWARD=1000/CAP=2000 |
| 商城 | palm/domain/roleplay/game_service.py | SHOP_CATALOG affinity_display=200 星砂 |
| 好感度引擎 | palm/domain/roleplay/affinity_engine.py | base -50~100/dynamics -50~50/bond 无上限/YAML 规则 |
| 记忆写入 | palm/domain/memory/memory_writer.py | detect_event（重要性≥3）/perform_fallback（5 轮）/strip_roleplay_tone |
| 角色卡 | palm/domain/roleplay/character.py | VoiceProfile 声音四维/SceneBrief/研究结论 |
| 对话服务 | palm/services/chat/chat_service.py | 容器取模型/voice.transcript 订阅/逐句 TTS |
| 六面 | mentalcore/mentalcore/faces/*.py | produce_module 真实逻辑（见 05 篇补全章 A） |
| 意图路由 | mentalcore/mentalcore/exo/intent_router.py | 关键词规则（零 LLM） |
| 轨迹 | mentalcore/mentalcore/exo/trace_store.py | 7 类型/2000 字截断/线程安全 |
| 专业记忆 | mentalcore/mentalcore/exo/professional_memory.py | sqlite 明文/3 kind/内存态 |
| 前端契约 | frontend/ui/api.js | BASE 注入/10s 超时/错误归一 |

---

## 补全章 D：复刻篇补全结论

复刻篇（06）补入：
1. 依赖管理修正（无冻结清单，venv+pip）。
2. 宿主层复刻指引（UiPort 契约驱动，含实现示例）。
3. 真实代码引用表（18 项，复刻者逐项核对）。

复刻篇达到 99% 完整度（唯一客观限制：backend/app 宿主层源码不可恢复，需按契约自实现）。

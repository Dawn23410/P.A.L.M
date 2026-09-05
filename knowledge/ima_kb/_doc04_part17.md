
# P.A.L.M 模块深度解析（99% 补全章：真实 schema/数值/机制实录）

> 本章为模块篇补全，把此前"推断/规划"级描述替换为**真实源码**：AgentRunRequest 完整字段、xp 数值、商城目录、记忆写入机制、角色卡字段、好感度引擎真实范围、对话服务机制。

---

## 补全章 A：Agent 请求与事件（services/agent/schemas.py 实录）

### A.1 AgentRunRequest（真实字段）

```python
class AgentRunRequest(BaseModel):
    conversation_id: str                                    # 会话 id
    message: str                                            # 用户消息
    model: str                                              # 模型标识
    memory_type: Literal["buffer"] = "buffer"               # 记忆层类型（仅 buffer，summary 已移除）
    max_iterations: int = Field(default=10, ge=1, le=50)    # 最大迭代步数（防无限循环）
    use_planning: bool = True                               # 自主规划引擎开关（默认开启）
    max_plan_steps: int = Field(default=8, ge=1, le=20)     # 计划最大步数
    provider: Any = None                                    # 自定义供应商（Ollama 等），不传用 Mock 回显
    character_id: str = ""                                  # 内置角色 id（优先于 persona_text）
    persona_text: str = ""                                  # 直接人设文本（无 character_id 时生效）
    tool_mode: Literal["native", "react"] | None = None     # native=原生 FC / react=文本 ReAct 兜底；
                                                            # 缺省用全局默认（native）；Anthropic 强制 react
    structured_output: dict | None = None                   # P5 结构化输出：JSON Schema；要求模型以单个
                                                            # ```json 代码块输出，收尾抽取校验后写入 done
    allowed_tools: list[str] | None = None                  # 工具白名单（基准测试/高风险场景）
```

### A.2 AgentEvent（SSE 流事件类型）

```python
type: Literal[
    "thought",        # Agent 思考过程
    "tool_call",      # 调用工具
    "tool_result",    # 工具执行结果
    "plan",           # 自主规划：完整计划（plan 字段为步骤列表）
    "plan_step",      # 计划单步状态更新（plan_step 字段为单步）
    ...               # 其余（text/ask_user/verdict/done/structured_output 等，以源码为准）
]
```

### A.3 完成闸门（completion_gate.py 实录）

- 可注册规则机制：`register_rule()` 添加自定义完成判定规则（不再硬编码工具名）。
- 内置默认规则（自动注册，向后兼容）：
  - `_rule_read_file_first_line`：read_file + "第一行"+"字符数" → 返回"第一行=...；字符数=..."。
  - `_rule_web_fetch_title`：web_fetch + "标题" → 返回"页面标题=..."。
  - `_rule_read_file_confirmed`：read_file + "confirmed=" → 返回"confirmed=..."。
- 用途：识别确定性工具结果，避免 Agent 已满足目标后继续空转。

---

## 补全章 B：经验与等级（domain/roleplay/xp.py 真实数值）

### B.1 常量（源码实录）

```python
STAGE_COUNT = 10           # 阶数（0~9）
LEVELS_PER_STAGE = 100     # 每阶级数（0~99）
BASE_EXP_PER_LEVEL = 1000  # 0 阶每级基础经验
# 各阶满容量 = 100 级 × 每级所需 = 100 × 1000 × (n+1)
```

### B.2 核心函数（源码实录）

```python
def exp_per_level(stage: int) -> int:
    # 每级所需 = BASE_EXP_PER_LEVEL × (stage + 1)，钳制到 [0, STAGE_COUNT-1]

def stage_capacity(stage: int) -> int:
    # 单阶总容量 = LEVELS_PER_STAGE × exp_per_level(stage)

def derive_level(total_exp: int) -> LevelInfo:
    # 逐阶扣减容量 → 得出 stage/level/exp_in_stage/exp_to_next/progress/total_level_index

def affinity_coefficient(base: float, dynamics: float = 0.0) -> float:
    # base_coef = 1.0 + max(0, base) / 100 × 0.7
    # dyn_coef  = max(0, dynamics) / 50 × 0.1

def streak_coefficient(streak: int) -> float:
    # 连登加成系数

def chat_xp(token_count: int, affinity: float, streak: int, dynamics: float = 0.0) -> int:
    # xp = round(token_count / 5000 × 好感度系数 × 累登系数)
```

### B.3 每日任务（源码实录）

```python
DAILY_TASKS = ["login", "chat_once", "chat_ten", "plan_once"]   # 4 项（含每日登录！）
DAILY_TASK_LABELS = {...}        # 中文标签
DAILY_TASK_REWARD = 1000         # 单任务经验
DAILY_TASK_EXP_CAP = 2000        # 每日任务经验上限
LOGIN_CURRENCY_BASE = 10         # 每日登录基础星砂
```

> **修正**：此前文档写每日任务 3 项（chat_once/plan_once/chat_ten）——**实际是 4 项，含 login（每日登录）**。星砂来源含"每日登录 +10"。

### B.4 商城目录（game_service.py 实录）

```python
SHOP_CATALOG = {
    "affinity_display": {
        "name": "好感度显示",
        "price": 200,                    # 200 星砂
        "desc": "解锁好感度数值与关系阶段的显示（默认对所有前台隐藏）。",
        "category": "强化",              # 强化=永久解锁（非一次性消耗道具）
    },
}
KNOWN_ITEMS = set(SHOP_CATALOG.keys())
```

> **修正**：好感度显示道具价格为 **200 星砂**（此前文档未给出价格）；分类为"强化"（永久解锁）。

---

## 补全章 C：好感度引擎（affinity_engine.py 实录）

### C.1 真实范围与行为

```python
# 两条线（2026-08-03 锁定设计）：
# base（地基）：信任/熟悉度，变化极慢，范围 -50~100，档位匹配饱和于 saturation
# dynamics（温度计）：当下心情，变化快，范围 -50~50，自然回归 0
# bond（羁绊值）：无上限，承接 base 溢出与超额增益，纯装饰/叙事
```

### C.2 机制要点（源码实录）

- **引擎只认 RuleSet 数据结构，零硬编码档位/名称/系数**——规则文件用 YAML（pyyaml 优先，不可用回退 `_minimal_yaml`），目录 `affection_rules/`。
- 升降由**模型每轮回复末尾 JSON 决定**（`resolve_from_model`），前端数值全隐藏。
- 角色可选：`affinity_enabled=False` 时调用方短路，不进入引擎结算。
- **久别疏离**：base 乘温柔幂律冷却因子（复用记忆层衰减形状），比"被冒犯"温柔 10 倍。
- Stage 结构：`lower_bound/name/greeting/tone/max_up/max_down`。

> **修正**：此前文档写好感度"10 级分层"——实际档位由 YAML 规则文件定义（Stage 结构含 lower_bound/max_up/max_down），引擎零硬编码；具体档位数量以 affection_rules 规则文件为准。

---

## 补全章 D：记忆写入（memory_writer.py 实录）

### D.1 MemoryWriter 机制

```python
class MemoryWriter:
    def __init__(self, archived: ArchivedMemory, fallback_interval: int = 5):
        self._fallback_interval = fallback_interval   # 兜底写入间隔（5 轮）
        self._rounds_since_write = 0

    def detect_event(self, content: str) -> list[ArchivedItem]:
        # 重要性评分（_score_importance）≥ 3 才写入
        # 入库前剥离角色语气（_strip_roleplay_tone 经 roleplay API）
        # 长期记忆只存事实，避免用户/模型语气残留污染记忆

    def perform_fallback(self) -> bool:
        # 每 5 轮强制触发一次兜底写入（rounds_since_write >= 5）
```

### D.2 语气剥离

```python
def _strip_roleplay_tone(text: str) -> str:
    api = get_roleplay_api()            # 经 palm._core.interop 取 roleplay 能力
    if api is not None:
        return api.strip_roleplay_tone(text)
    return text                          # roleplay 缺失时原样返回（降级安全）
```

> **补全**：记忆写入有**事件触发（detect_event，重要性≥3）+ 兜底（perform_fallback，每 5 轮）**双通道；语气剥离经 interop 的 roleplay API（`strip_roleplay_tone`）。

---

## 补全章 E：角色卡（character.py 实录）

### E.1 高质量人设必备要素（研究结论，源码 docstring）

- 性格支柱 + 内在矛盾（3-5 条，矛盾制造张力，避免扁平）。
- 声音四维（VoiceProfile）。
- 示例对话（让模型对齐语气）。
- 缺点与脆弱面（角色必须会犯错、会示弱）。
- 话痨程度滑块（0-100，控制主动输出量）。
- 场景简报（SceneBrief）。
- 目标、价值观、行为准则、安全边界。

### E.2 VoiceProfile（声音四维）

```python
@dataclass
class VoiceProfile:
    vocabulary_range: str = ""    # 用词区间：简白/书面/诗化/俚语…
    sentence_rhythm: str = ""     # 句式节奏：短促利落/绵长铺陈/碎片化
    never_say: list[str] = ...    # 绝不会说出口的话
    ticks: list[str] = ...        # 口头禅/标志性小动作
```

### E.3 SceneBrief（场景简报）

```python
@dataclass
class SceneBrief:
    where: str = ""               # 场景地点
    when: str = ""                # 时间
    what_just_happened: str = ""  # 刚刚发生了什么
    # ...（角色此刻想要什么等，以源码为准）
```

---

## 补全章 F：对话服务机制（chat_service.py 实录）

### F.1 设计要点（源码 docstring + 实现）

- UI 作为中枢调用本模块；自身不持有模型协议——**经服务容器取模型适配器 create_stream 取流、经用量服务做配额拦截与流末记账**，模块间仅经容器交互。
- 语音输入接线：语音识别最终文本发布到 `voice.transcript`，本模块订阅后走同一对话链路；LLM 流式正文**逐句并行合成语音**发布到事件总线。
- `ChatError`：对话链路业务错误（配额/模型缺失/附件模式不符等）。
- `_models_capability(name)`：运行时经服务容器取模型适配器能力（懒加载，避免导入期依赖）。

### F.2 订阅/发布（源码实录）

```python
from palm._core.eventbus import (emit, subscribe,
    VOICE_TRANSCRIPT, VOICE_TTS_CHUNK, VOICE_REPLY_READY)
# 订阅：voice.transcript → 进入对话链路
# 发布：voice.tts_audio_chunk（逐句并行合成）/ voice.reply_ready（对话完成）
```

---

## 补全章 G：依赖管理事实（重要修正）

**源码证据**：当前工作区**无 requirements.txt**（仅 mentalcore/pyproject.toml）。

**结论**：
1. 依赖**非冻结清单管理**——安装以 pip 命令指定为主（venv 各自安装）。
2. 语音引擎依赖（torch cu128 等）在独立 venv 中管理（venv_cosyvoice/venv_gsv），主运行时依赖（fastapi/uvicorn/pydantic/pyyaml/httpx 等）在 venv_runtime。
3. 复刻时依赖版本以"能跑通验收"为准，无版本锁定约束（mentalcore pyproject.toml 为唯一声明源）。

**本章补全结论**：04 篇此前按"推断/规划"描述的内容（任务数/商城价格/好感度档位/记忆写入/角色卡字段/工具层位置/依赖管理）已全部替换为真实源码，模块篇缺口清零。

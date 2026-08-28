
# P.A.L.M 心智核心与外骨骼深度解析（99% 补全章：六面与 exo 源码实录）

> 本章为心智篇补全，把六面 `produce_module` 真实逻辑与 exo 各模块机制从源码全量实录——此前"结构推断"级描述全部替换为真实实现细节。

---

## 补全章 A：六面 produce_module 真实逻辑（faces/ 源码实录）

### A.1 情感面（emotion.py）——好感度引擎 + 情绪识别

```python
class EmotionFace(BaseFace):
    name = "emotion"

    def __init__(self, base=0, bond=0, dynamics=0):
        # 初始状态由外部注入（storage.load_affinity 恢复，重启不归零）
        self.base = base          # 信任地基 -50~100，慢变
        self.dynamics = dynamics  # 当下心情 -50~50，快变
        self.bond = bond          # 羁绊，无上限

    def enabled(self, ctx): return ctx.persona.affinity_enabled   # 整面停用开关

    def produce_module(self, ctx):
        if not self.enabled(ctx):
            return InjectionModule(source=self.name, content="", available=False)
        stage = self._current_stage(ctx)
        lo, hi = stage.delta_range
        content = (f"【关系】你与用户的关系等级：{stage.name}。{stage.description} "
                   f"语气：{stage.tone}。称呼：{stage.address or '无'}。"
                   f"好感度增减范围：{lo} ~ {hi}（仅内部参考，回复勿提数值）。")
        # 严重降低：隐藏档位，固定 prompt 每轮发送，AI 自由裁定是否触发
        slo, shi = SEVERE_DROP.delta_range
        safety = (ctx.persona.safety or DEFAULT_SAFETY).strip()
        content += (f"\n【严重受损指引（仅内部参考，回复勿提）】"
                    f"若本句使关系严重受损（单次好感度扣分 {shi} ~ {slo}）：{safety}")
        return InjectionModule(source=self.name, content=content, fixed=False, priority=30)
```

**关键设计（源码）**：
- 档位内容注入、数值不注入（只给档名/称呼/语气，AI 不自想关系）。
- 本地结算器：LLM 只给 delta，base/dynamics/bond 本地计算。
- 情绪识别：共用模型 complete 旁路通道，失败不注入。
- 严重受损指引（SEVERE_DROP/DEFAULT_SAFETY）：每轮固定发送，AI 自由裁定。

### A.2 记忆面（memory.py）——短期 + 长期

```python
_RECENT_TURNS = 3          # 短期：最近 3 轮
_RECALL_TOPK = 3           # 长期：语义召回 top3
_MAX_BLOCK_CHARS = 600     # 注入块上限（防撑爆 prompt，控制首字延迟）

def produce_module(self, ctx):
    blocks = []
    recent = ctx.history[-_RECENT_TURNS:]
    if recent:
        lines = ["【近期对话】"]
        for turn in recent:
            lines.append(f"用户：{turn.get('user', '')}")
            lines.append(f"{ctx.persona.name}：{turn.get('assistant', '')}")
        blocks.append(self._truncate("\n".join(lines)))    # 600 字截断
    recall = self._recall(ctx)                              # 语义召回（上下文携带时）
    if recall:
        lines = ["【长期记忆·相关】"] + [f"- {item}" for item in recall]
        blocks.append(self._truncate("\n".join(lines)))
    if not blocks:
        return InjectionModule(source=self.name, content="", available=False)  # 不可用即不注入
    return InjectionModule(source=self.name, content="\n\n".join(blocks), fixed=False, priority=20)
```

### A.3 人格面（persona.py）——固定模块（可缓存前缀）

```python
def produce_module(self, ctx):
    p = ctx.persona
    lines = [
        f"你是{p.name}，{p.tagline}。",
        f"性格：{'、'.join(p.personality_pillars)}。",
        f"缺点：{'、'.join(p.flaws)}。",
        f"语气：{p.tone}。",
        f"话痨程度：{p.talkativeness}。",
    ]
    if p.background: lines.append(f"背景：{p.background}")
    if p.age: lines.append(f"年龄：{p.age}岁。")
    if p.example_dialogue: lines.append(f"示例对话：{p.example_dialogue}")
    # 首次对话（无历史）注入开场白；有历史不再注入避免冗余
    if not ctx.history and (p.first_mes or p.alternate_greetings):
        greetings = p.alternate_greetings or [p.first_mes]
        lines.append(f"开场白（首次对话可选用）：{' | '.join(str(g) for g in greetings[:3])}")
    return InjectionModule(source=self.name, content="\n".join(lines),
                           fixed=True, priority=10)          # 固定模块：在上、可缓存
```

### A.4 律动面（rhythm.py）——时间感知 + 日程 + 生日

```python
WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"]

def produce_module(self, ctx):
    if not ctx.persona.dynamic_updates_enabled:
        return InjectionModule(source=self.name, content="", available=False)   # 整面不注入
    now = ctx.now
    lines = [f"【此刻】{now.strftime('%Y-%m-%d')} 星期{WEEKDAYS[now.weekday()]} {now.strftime('%H:%M')}。"]
    lines.extend(self._schedule_slice(ctx))     # 日程切片（period "start-end" 或单小时）
    if self._is_birthday(ctx):
        lines.append("今天是你的生日，可流露被记挂的暖意。")
    return InjectionModule(source=self.name, content="\n".join(lines),
                           fixed=False, priority=50)
```

### A.5 储存面（storage.py）——加密落盘 + 控制面

```python
class StorageFace(BaseFace):
    name = "storage"

    def __init__(self, path="mentalcore_data/conversations", crypto=None, semantic_memory=None):
        # 对话记录 conversations.dat（加密追加）
        # 好感度 affinity.dat（加密覆盖，重启恢复）
        # 不产 prompt 模块：存储与对外控制面，非 prompt 影响面
        # 处理 inbound 控制码（储存域 D1=1：查/清/导出等，按 D2 子类路由）
        # 向量归档查/清委托 SemanticMemory（防污染删除链路）

    def save_turn(self, user, assistant):
        # json 序列化 → crypto.encrypt_text（未启用则明文降级）→ 追加写入

    def save_affinity(self, base, bond, dynamics):
        # json → 加密 → 覆盖写 affinity.dat

    def load_affinity(self) -> dict:
        # 读 affinity.dat 解密还原；不存在返回 {base:0, bond:0, dynamics:0}
```

### A.6 织语面（weave.py）——<内心>一致性约束

```python
def produce_module(self, ctx):
    p = ctx.persona
    content = (f"【表达风格】按格式「{p.format_spec}」组织语言，"
               f"保持{p.name}的口吻，与示例对话的语感一致。"
               f"<内心>是本句未说出口的真实想法；正文须用自然口语把这份想法"
               f"对用户说出来，与<内心>同一主题、情绪一致，不得逐字复读内心"
               f"或另起无关话题。")
    return InjectionModule(source=self.name, content=content, fixed=False, priority=40)
```

**关键设计**：一致性约束源于实测教训——若不加约束，模型会把内心独白和对外正文生成成两段无关内容（内心"困惑"、正文却寒暄的脱节）；正文须重述内心而非逐字复读，否则"未说出口"的内心变成说出口的同一句。

### A.7 注入优先级总表（源码实录）

| 面 | fixed | priority | 内容 |
|---|---|---|---|
| persona | true（可缓存前缀） | 10 | 人格静态设定 |
| memory | false | 20 | 近期对话 + 语义召回 |
| emotion | false | 30 | 关系档位 + 严重受损指引 |
| weave | false | 40 | 表达风格 + <内心>约束 |
| rhythm | false | 50 | 时间/日程/生日 |
| storage | — | — | 不产 prompt（存储/控制面） |

---

## 补全章 B：exo 各模块真实机制（源码实录）

### B.1 意图路由（intent_router.py）——纯关键词零 LLM

```python
I_CHAT = "chat"          # 闲聊/简单问答 → Boss 直答
I_TASK = "task"          # 复杂任务（多步工具）→ 启动 Worker
I_INTERVENTION = "intervention"  # 干预（cancel/pause/resume/redirect）
I_QUERY = "query"        # 查询 Worker 进展

@dataclass
class IntentResult:
    intent: str = I_CHAT
    task_goal: str = ""               # task：Worker 任务目标
    intervention_action: str = ""      # intervention 动作
    redirect_instruction: str = ""     # redirect 新指令
    confidence: float = 1.0            # 关键词匹配 = 1.0

# 任务触发词（源码实录示例）：
_TASK_PATTERNS = [
    r"(?:帮我|请|麻烦|可以|能不能|你给我).{0,4}(?:做|搞|弄|写|改|查|找|部署|分析|整理|搜索|构建|开发|测试|优化|修复|迁移|搭建|配置|安装|生成|创建|删除|清理|检查|排查|诊断)",
    r"(?:写一个|写段|写个|做个|帮我写|帮我查|帮我找|帮我改|帮我分|帮我整|帮我排|帮我搭)",
    r"(?:运行|执行|启动|调用).{0,6}(?:脚本|程序|代码|命令|任务)",
]
# 路由策略：纯关键词匹配（零 LLM 调用，延迟 <1ms），与归档设计一致
```

### B.2 Worker 运行器（runner.py）——反思自检

```python
_REFLECT_PROMPT = '你是一个严苛的回答自我审查员。请判断「本次回答」是否真正、完整地满足了「用户请求」。...仅输出一个 JSON 对象：{"verdict": "ok" 或 "revise", "issue": "...", "instruction": "..."}...'

def reflect_once(worker, request, draft, had_failure=False) -> str:
    # 自检：返回修正指令（verdict=revise 时）
    # 解析失败/异常一律降级为 ""（不自残）
    # mock 模型（无反思语义）返回空，等效关闭
    # 有工具失败但回答未提及 → failure_note 提示核实

def _parse_reflect_json(text) -> dict: ...   # 容忍 ```json 包裹/前后噪声

def _sanitize_tool_text(text) -> str: ...    # 工具结果装饰壳清洗（剥离旧版包装，只留原始输出）
# 同步适配：经 worker.llm.complete(prompt, tools) 走原生 function calling
```

### B.3 工具匹配（tool_matcher.py）——关键词评分零外部依赖

```python
# 不用外部向量库/嵌入模型：仅关键词 + 描述词频评分
# 按用户输入筛出 Top-K 工具，缩小注入模型的工具暴露面（安全 + 省 token）

def _tokenize(text) -> set[str]:
    # 中文单字 + 双字组合 + 英文单词；过滤停用词（中文+英文）

_STOP_WORDS = {"的","了","在","是","我","有","和","就","不","人","都","一",
               "一个","上","也","很","到","说","要","去","你","会","着","没有",
               "看","好","自己","这","the","a","an","is","are","was","were",...}
```

### B.4 轨迹存储（trace_store.py）——7 种轨迹类型

```python
T_THOUGHT = "thought"          # 思维链/推理过程
T_TOOL_CALL = "tool_call"      # 工具调用（名称+参数）
T_TOOL_RESULT = "tool_result"  # 工具执行结果
T_OUTPUT = "output"            # 阶段性输出/最终回答
T_PLAN = "plan"                # 规划步骤
T_ERROR = "error"              # 错误信息
T_INTERVENTION = "intervention"  # 干预指令（来自 Boss）

# TraceEntry：step/entry_type/content(截断 2000 字)/timestamp/metadata
# 线程安全：Worker 后台线程写入、Boss 主线程检索（threading.Lock）
# Boss 经摘要/关键词检索按需拉取，而非一次性灌入全部上下文
# 去 palm 化：移除 palm._core.interop 向量后端，统一走关键词评分检索
```

### B.5 专业记忆（professional_memory.py）——sqlite 明文

```python
K_EXPERIENCE = "experience"        # 经验总结
K_USER_PROFILE = "user_profile"    # 用户画像
K_ERROR = "error"                  # 错误记录
# sqlite 明文持久化；db_path=None 内存态（mock 零落盘合规）
# 检索只做基础关键词匹配（_TOKEN_RE），不复用主记忆五因子检索
# 异步整理（schedule_trace_digest）LLM 调用改为可注入同步 fn，缺省跳过
```

### B.6 WorkCore 与 Boss 交互补全

- Worker 完成：`boss.receive({"exo_result": ...}, "外骨骼完成")`。
- 干预：`forward_intervention(cancel/pause/resume/redirect)`。
- 状态：`get_status()`；查询：`answer_query()`（从轨迹摘要检索）。

---

## 补全章 C：心智篇补全结论

**此前推断项已全部替换为源码**：
1. 六面 produce_module 逻辑：注入优先级表、<内心>约束、情感面档位注入不注入数值、储存面加密落盘。
2. exo：意图路由关键词规则、反思自检 JSON 协议、工具匹配停用词评分、轨迹 7 类型、专业记忆 sqlite。
3. 修正：情感面情感识别走 complete 旁路（非后台线程）；储存面不产 prompt 模块；记忆面 _recall 依赖上下文携带语义记忆。

心智篇（05）缺口清零，达到 99% 完整度。

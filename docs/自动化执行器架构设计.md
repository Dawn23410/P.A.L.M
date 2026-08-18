# GUI 自动化执行器：架构设计说明书

> 版本：v2.0（2026-08-13）
> 范围：`backend/app/tools/gui/` 自动化执行器砖块及相关世界模型缓存层
> 文档定位：报告/设计文档风格，含功能支持、架构组成与可参考的外部基准测试文献

---

## 摘要

自动化执行器是 P.A.L.M 主 Agent 直接操控桌面与浏览器应用程序的"手"，承担"实时感知 → 规划 → 批量执行 → 验证 → 收尾"的完整闭环。它把 LLM 的"理解力"与原生键鼠的"执行力"解耦：LLM 只在规划阶段介入一次，执行阶段由四级容错执行器独立完成；执行后由验证子系统回写世界模型缓存，使下一次相同任务无需再调 LLM——这是执行器"越用越准、越用越快"的核心机制。

本文档按"功能支持 → 架构组成 → 创新点 → 外部基准测试参考"的顺序展开，最后给出可执行的设计决策与扩展点清单。

---

## 1. 功能支持

执行器在工具层面向主 Agent / 专业 Agent 暴露的核心能力如下，全部通过统一的 `run_automation` 工具调用接口暴露。

### 1.1 动作原语

| 动作 | 输入字段 | 行为 |
|---|---|---|
| `click` | `name` / `automation_id` / `control_type` | UIA 定向查找控件，真实键鼠点击；定向失败自动回退 OCR |
| `type` | `text` | 模拟键盘逐字输入（中文/英文/符号均可） |
| `press` | `key` 或虚拟键码 | 单键按下抬起 |
| `hotkey` | `keys` 列表 | 组合键，自动归一化大小写（`Ctrl+S` → `ctrl+s`） |
| `wait` | `timeout`（秒，上限 10） | 同步等待界面切换 |
| `check` | `automation_id` | 通过 UIA TogglePattern 读取开关状态（0=关/1=开） |
| `verify` | `name` / `automation_id` | 廉价 UIA 存在性校验，~10ms/控件，不触发 OCR |
| `close` | `target` 窗口 | 关闭按钮 → Alt+F4 → 保存对话框（不保存），逐步降级并诚实返回 |

### 1.2 上下文能力

- **目标窗口解析**：按 `target` 字符串模糊匹配窗口标题，匹配失败回退到缓存中同软件最近操作的窗口（同 `software_id`），最后回退到前台窗口
- **控件身份多重条件**：`name`（子串）、`automation_id`（精确）、`control_type`（类型过滤）三者可任意组合
- **预期控件校验**：`click` 可带 `expect` 列表，命中即视为成功，省一轮 LLM `describe_window` 复查调用
- **状态先验短路**：`check` 配合 `stop_if=1` 实现"已开不重开"，避免重复操作
- **多软件坐标记忆**：跨会话保存归一化包围盒，重开窗/重启进程后仍可直接命中

### 1.3 鲁棒性能力

- **四级容错**（见 §2.4）：L0 直点缓存 → L1 控件未变直点 → L2 重定位 → L3 OCR 兜底
- **后台预取**：当前步执行时后台线程预定位下一步，`prefetch_hits` 指标记录
- **状态机**：`Idle → Executing → Paused → Cancelled → Idle`，可由 `pause` / `resume` / `cancel` 远程控制
- **鼠标中断检测**：检测到用户主动移动鼠标 > 50px 自动中断（屏蔽执行器自身移动）
- **超时兜底**：单次 `run` 默认 60s 上限，`wait` 单步 10s 上限
- **Electron 应用特化**：检测到 Electron/Chromium 进程时直接走 OCR 路径，禁用一切 UIA 遍历（避免 ntdll 崩溃）

### 1.4 学习与可观测性能力

- **跨会话坐标记忆**：归一化坐标 + O(1) 命中测试，`coord_memory_hits` 指标记录
- **转移规律层**：点击后廉价 UIA 树抽取控件集合记入转移层，下次 LLM 可查"点 X 后通常出现 Y"
- **指标落盘**：每次 run 写入 `Data/gui_metrics/YYYY-MM-DD.jsonl`，会话聚合写入 `_session.json`
- **架构健康度核心指标**：L0 直点命中率（`l0_rate`）——值越高代表界面稳定、缓存策略有效

---

## 2. 架构组成

### 2.1 模块位置与依赖

执行器砖块在仓库中的物理位置如下：

```
backend/app/tools/gui/
├── executor.py                # 核心执行器（AutomationExecutor + RunAutomationTool）
├── executor_locator.py        # 定向查找 + 开关读取 + 关窗
├── automation_orchestrator.py # 推理中枢入口（execute_gui_intent）
├── metrics.py                 # 指标记录器
├── world_model.py             # UIA 树 + OCR 双通道感知
├── atlas_tool.py              # describe_window / get_cognitive_map
├── ocr_engine.py              # OCR 引擎三级自适应
├── desktop_control.py         # 基础键鼠封装
├── web_automator.py           # 浏览器 DOM 通道（web 类软件路由）
└── world_model_cache/
    ├── reasoning_hub.py       # 三级推断（路径记忆 / 语义推断 / LLM 兜底）
    ├── path_memory.py         # 成功路线持久化
    ├── coord_memory.py        # 跨会话坐标记忆
    ├── transition_model.py    # 动作→界面控件集合统计
    ├── registry.py            # 软件注册表
    ├── schema.py              # 能力标签词库
    └── distiller.py           # 经验沉淀
```

### 2.2 数据流总览

```
                   主 Agent / 专业 Agent
                          │
                  execute_gui_intent(software_id, intent)
                          │
                          ▼
              ┌──────────────────────┐
              │   reasoning_hub      │  推理中枢：路径记忆 / 语义推断 / LLM 兜底
              │   infer_route()      │  → 返回 {source, needs_llm, steps, confidence}
              └──────────┬───────────┘
                         │ steps
                         ▼
              ┌──────────────────────┐
              │  AutomationExecutor  │  执行器核心
              │   .run(steps)        │  → 状态机 / 鼠标中断 / 预取
              └──────────┬───────────┘
                         │ 每步
                         ▼
   ┌─────────────────────────────────────────────┐
   │ _execute_step()                             │
   │  ├─ 1. _resolve_target(step)  目标窗口解析 │
   │  ├─ 2. _coord_memory_lookup() 跨会话记忆   │
   │  ├─ 3. _consume_prefetch()    后台预取     │
   │  ├─ 4. find_control_direct()  定向查找     │
   │  ├─ 5. _locate_ocr()           L3 兜底     │
   │  ├─ 6. _act_click/type/press  真实键鼠     │
   │  └─ 7. _verify_after_click()  预期校验     │
   └─────────────────────────────────────────────┘
                         │ 落盘
                         ▼
       Data/gui_metrics/ + Data/gui_path_memory/
```

### 2.3 推理中枢三级推断

`reasoning_hub.infer_route()` 是整个执行器决策的入口，实现三级推断：

1. **路径记忆命中**（`memory`）：在 `path_memory` 中按 `software_id + intent_signature` 查询历史成功路线，零 LLM 调用
2. **语义关键词推断**（`inferred`）：从 `schema` 词库把意图翻译为能力标签，与 Atlas 注册的控件匹配，零 LLM 调用
3. **LLM 兜底**（`llm_fallback`）：返回紧凑上下文，由上层调 LLM 规划一次后 `confirm_and_save` 落盘

置信度渐进校准：单次 LLM 落盘只给 0.12，越过 0.80 才进入 `trusted` 纯推理直执行；中途经历 `verify`（推理但事后校验）和 `weak`（仍走 LLM）。执行成功 +0.10，转移/坐标联动佐证 +0.08/+0.06——这是"越用越准越快"的形式化机制。

### 2.4 执行器四级容错

执行器核心 `_execute_step()` 按以下四级降级链定位控件：

| 级别 | 触发条件 | 行为 | 典型耗时 |
|---|---|---|---|
| **L0** | 窗口指纹未变 + 缓存坐标一致 | 直接点缓存坐标 | 10-30ms |
| **L1** | 窗口指纹变了但目标控件位置未变 | 直接点缓存坐标 | 10-30ms |
| **L2** | 位置变了但 UIA 树能找到 | 定向查找 + 更新缓存 | 28-60ms |
| **L3** | UIA 全变 | 全屏 OCR 找文字 + 增量学习 | 522-2900ms |

外加**跨会话记忆层**（记为 `LM`）——`coord_memory` 命中时直接 O(1) 命中测试跳过 UIA 遍历，~5ms。

定向查找使用 `Control(searchFromControl, SubName, AutomationId, searchDepth, searchInterval)` + `Exists()` 模式而非全树 `build_uia_tree`，这是规避 uiautomation fork 两个坑的关键：(1) `GetFirstChildControl` 不接受条件；(2) 属性键必须大写驼峰。

### 2.5 状态机与中断

```
       pause()            resume()            cancel()
Idle ─────────► Executing ─────────► Paused ─────────► Cancelled ───► Idle
                  │   │                  │
                  │   └──── cancel() ────┘
                  └── mouse_interrupt → Cancelled
```

每步执行前调用 `_guard_state()`：若 `Cancelled` 则立即返回 `False`；若 `Paused` 则 200ms 轮询等待恢复；若 `Executing` 则放行。

### 2.6 与世界模型缓存的协作

执行器并不孤立工作，它与四个世界模型缓存层正交协作：

- **Atlas**（`registry` + `distiller`）：软件的静态控件图，相当于"地图"
- **路径记忆**（`path_memory`）：成功执行过的步骤序列，相当于"经验"
- **转移规律**（`transition_model`）：动作 → 后续界面控件集合的统计，相当于"动态预测"
- **坐标记忆**（`coord_memory`）：归一化坐标缓存，相当于"肌肉记忆"

四层关系是 Atlas 提供"是什么"，路径记忆提供"怎么走"，转移规律提供"走完会变什么"，坐标记忆提供"上次在哪"——任意一层缺失执行器仍可工作（其他层静默降级），但联动度会降低。

### 2.7 web 自动化分支

`automation_orchestrator` 在收到 `execute_gui_intent(software_id, intent)` 时按 `software_id` 路由：

- 若 `software_id` 属于 `WEB_SOFTWARE_IDS`（浏览器类），调用 `WebAutomationExecutor` 走 DOM 通道，避免 Chromium 对 UIA 遍历的敏感
- 否则调用 `AutomationExecutor().run(steps, software_id=...)` 走桌面 UIA 通道

两套执行器共享相同的步骤协议（`action / name / automation_id / control_type`），保证 LLM 规划结果可路由。

---

## 3. 关键设计决策

### 3.1 规划与执行解耦

LLM 在 `run_automation` 入口处一次性产出完整步骤数组，执行阶段不再回调 LLM。这一解耦带来三个收益：

- **执行确定性**：步骤已知，每步耗时可控，避免 LLM 多步决策累积造成的不可预测延迟
- **并发友好**：步骤可被缓存、被复现、被离线复盘
- **学习闭环清晰**：执行成败可独立归因，confidence 可独立校准

代价是 LLM 需要理解步骤协议（通过 `desktop-visual-operator` Skill 教导），但这是用一次性教导换长期执行效率。

### 3.2 推理中枢作为快路径

`infer_route()` 把 LLM 调用推到"真正没有候选步骤"时——已有路线记忆或语义推断可命中的场景完全免 LLM。这是"越用越准越快"的实现机制：用户每完成一次任务，路径记忆的样本数 +1，置信度按固定增量提升，直到越过 0.80 后纯推理直执行。

### 3.3 UIA 优先 + OCR 兜底

正常路径（L0/L1/L2）完全不触碰 OCR，仅 L3 全变或 Atlas 建图才用。这一设计源于实测：设置窗口（UIA 219 节点）全量（UIA+OCR）耗时是仅 UIA 的 12 倍，内存是 452 倍，但获取的控件数量完全相同——OCR 引入跨窗口污染却无信息增量。

### 3.4 状态先验代替重复操作

`check + stop_if` 让 LLM 在写步骤时不必担心"如果已开怎么办"——先读状态再决策。这把"避免重复操作"的逻辑固化进执行器，不依赖 LLM 自觉遵守。

### 3.5 诚实的失败返回

`close_window` 在 Alt+F4 被保存对话框拦截时，诚实地尝试 `Alt+N`、复查窗口存活、返回布尔结果，不假成功；步骤失败时不假装"已完成"。这一原则贯穿执行器所有失败路径：宁可被 LLM 看到失败重试，也绝不掩盖。

---

## 4. 可参考的外部基准测试

执行器面向的是"真实 GUI 自动化"这一持续演进的研究领域。下列外部基准测试是设计执行器时的重要参考与对照基准——执行器当前以"内部任务 + 桌面视觉题库"作为验证入口，下表展示在更大公开测试集上对接的可能性与适用场景。

| 基准 | 领域 | 任务规模 | 关键特性 | 对执行器的对应能力 |
|---|---|---|---|---|
| **OSWorld** | 真实桌面 OS（Ubuntu/Windows） | 361 任务 | 真实应用（Chrome/VS Code/LibreOffice/Thunderbird），多步长链 | 4 级容错 / 状态先验 / OCR 兜底 |
| **OSWorld 2.0** | 长链路专业工作流 | 108 任务 / 7 领域 | 自托管 31 个网站 + 桌面应用，需跨工具信息协调 | 路径记忆 / 转移规律层 / 联动佐证 |
| **WebArena** | 真实电商/论坛/代码仓库 | 812 任务 | 6 个自托管站点，HTML/截图双模态 | Web 自动化分支 / DOM 通道 |
| **VisualAgentBench (VAB)** | GUI + 具身 + 视觉设计 | 5 数据集 | 视觉多模态，强调"视觉基础智能体" | OCR 引擎 / 视觉通道 |
| **Android-in-the-Wild (AITW)** | 移动端 Android | 715k episodes | 30k 指令 / 4 Android 版本 / 8 设备 | 坐标记忆（归一化）/ 跨设备迁移 |
| **WindowsWorld** | Windows 跨应用工作流 | 真实流程 | 流程中心视角（process-centric），L2-L3 分级 | 路径记忆 L2/L3 / 状态机 |
| **OSWorld-Human** | 效率维度补充 | 与 OSWorld 配套 | 度量规划/反思延迟占比，验证"少调 LLM"价值 | 推理中枢快路径 / 步骤协议 |
| **τ-bench** | 工具可靠性 | 多轮次 | 同一任务多轮跑，检验一致性 | 状态机 / 鼠标中断检测 |

### 4.1 与执行器设计的具体对照

- **OSWorld 的 latency 洞察**（"规划/反思调用占总延迟 75-94%"）直接支持"推理中枢快路径"的设计——把 LLM 调用从每次规划压到首次才调，效率提升量级与 OSWorld-Human 的方向一致 [$TRAE_REF](https://arxiv.org/html/2506.16042v1)
- **OSWorld 2.0 的"长链路 + 跨工具信息协调"**与执行器的"路径记忆 + 转移规律层"是同一问题的不同表述：都需要让 Agent 记住"走完上一步后下一步通常会怎样" [$TRAE_REF](https://snorkel.ai/leaderboard/os-world-2-0/)
- **WebArena 的 6 站点 DOM 任务**为执行器的 Web 自动化分支提供了现成的任务集；当前 WebArena Verified 提供可复现的任务定义 [$TRAE_REF](https://the-ai-alliance.github.io/cube-registry/webarena-verified/)
- **VisualAgentBench 的 VAB-WebArena-Lite**与 VAB-Mobile 适合验证 OCR 通道在弱 UIA 场景下的有效性 [$TRAE_REF](https://github.com/THUDM/VisualAgentBench/blob/main/README.md)
- **WindowsWorld 的"流程中心"视角**与执行器"开窗→操作→关窗"的洁癖教导是同一思路，强调完整流程而非单点操作 [$TRAE_REF](https://arxiv.org/html/2604.27776v1)
- **AITW 的跨设备归一化思路**为 `coord_memory` 的"窗口内归一化坐标"提供了先验——归一化后坐标可跨窗口尺寸、跨屏幕分辨率复用 [$TRAE_REF](https://arxiv.org/pdf/2312.08914v1)
- **VLAA-GUI 的"停止 / 恢复 / 搜索"三分支**与执行器的状态机 `Paused` / `Cancelled` 是同一控制模式，证明把"何时停止"显式建模的价值 [$TRAE_REF](https://ucsc-vlaa.github.io/VLAA-GUI/)

### 4.2 现有内部题库

执行器在 `backend/tools/agent_desktop_visual_bench_bank.yaml` 已有桌面视觉题库，任务严格限制工具白名单（仅 `hotkey` / `type_text` / `press_key` / `move_mouse` / `click_mouse` / `scroll_mouse` / `take_screenshot` / `screenshot_region`），题目直接对应 OSWorld / VisualAgentBench 风格的多步真实桌面任务。题库的结构与外部基准一致，可作为未来接入 OSWorld / WebArena 任务时的转换模板。

---

## 5. 指标与健康度

执行器通过 `metrics.py` 收集每次 run 的统计数据，落盘到 `Data/gui_metrics/YYYY-MM-DD.jsonl`。核心可观测指标：

| 指标 | 含义 | 健康阈值 |
|---|---|---|
| `l0_rate` | L0 直点占所有已定位点击的比例 | > 0.6 表示缓存策略有效 |
| `cache_hits` | 命中运行时坐标缓存的次数 | 与界面稳定性正相关 |
| `coord_memory_hits` | 命中跨会话坐标记忆的次数 | 随使用增长，越用越快 |
| `prefetch_hits` | 后台预取被消费的次数 | 反映执行流畅度 |
| `l3_rate` | L3 OCR 兜底占比 | 越低越好，> 0.2 需检查 UIA 覆盖 |
| `stop_if_fired` | 状态先验短路次数 | 反映 LLM 规划冗余度 |
| `mouse_interrupt` | 鼠标中断触发次数 | 反映人机协作密度 |
| `timeout_fired` | 总超时触发次数 | 反映 LLM 给的 wait 阻塞严重性 |

通过 `_session.json` 可实时查看本进程 + 今日累计的指标分布。

---

## 6. 扩展点与未决问题

- **OmniParser 集成**（调研结论已落库）：UIA 真空区（自绘控件 / 游戏 / Web canvas）可接入 OmniParser（YOLO 框选 + Florence-2 描述）作为视觉兜底，与 UIA 互补而非替代
- **置信度阈值动态化**：当前 HIGH=0.80 / MID=0.40 为硬编码常量；后续可按软件类别（系统设置 / 办公 / 浏览器）差异化
- **跨设备坐标记忆**：`coord_memory` 当前按 software_id 分桶，可扩展按窗口类/显示器类多维索引，支持 AITW 风格的跨设备任务
- **外部基准接入**：OSWorld / WebArena / VisualAgentBench 的任务定义可直接转换为 `agent_desktop_visual_bench_bank.yaml` 的格式，作为正式回归测试集

---

## 7. 参考资料

外部基准测试资料已在第 4 节通过内联引用给出。

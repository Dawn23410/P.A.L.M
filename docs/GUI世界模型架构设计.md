# GUI 世界模型架构设计说明书

> 版本：v1.0（2026-08-13）
> 范围：`backend/app/tools/gui/world_model.py` + `backend/app/tools/gui/world_model_cache/*` + `atlas_tool.py` 接入层
> 文档定位：报告/设计文档风格，含分层架构、双通道融合、缓存层正交协作、四阶段演进路径
> 与既有文档的关系：与 `docs/自动化执行器架构设计.md`（执行器砖块）并列；本文件聚焦「感知 + 记忆」侧

---

## 摘要

GUI 世界模型把"一个真实窗口"从模糊的截图转译为可计算的结构化数据。它由一条结构通道（UIA 控件树）与一条像素通道（窗口截图 OCR）融合而成，产出可见层级、三张清单、融合标注树三大产物。

围绕"瞬时世界模型"，P.A.L.M 又构建了四层**正交缓存**——静态地图（Atlas）、成功路线（Path Memory）、动作转移（Transition）、归一化坐标（Coord Memory）——分别回答"有什么 / 怎么走 / 走完会变什么 / 上次在哪"。四层缓存与执行器协作，闭环驱动"越用越准、越用越快"。

本文档按"功能支持 → 架构组成 → 双通道融合机制 → 四层缓存 → 创新点 → 演进路径"组织，附实测性能数据与可参考的外部研究文献。

---

## 1. 功能支持

### 1.1 实时感知能力

| 能力 | 入口 | 行为 |
|---|---|---|
| 单窗口完整世界模型 | `build_world_model(target)` | UIA 树 + OCR + 融合 + 落盘 JSON + 渲染 PNG + 结构化 SVG |
| 仅 UIA 结构 | `build_uia_tree(hwnd)` | 纯结构通道，不碰 OCR，几十毫秒 |
| 仅 OCR 文本盒 | `image_retrieval(screenshot_path)` | 全屏/窗口截图 OCR 文本+包围盒 |
| 实时控件定位 | `find_control(model, name, automation_id, control_type)` | 优先 OCR 佐证 + 启用 + 面积最小匹配 |
| 文档级重建 | `render_from_document(json_path)` | 不读任何像素，仅靠结构化 JSON 重建可视化图 |

### 1.2 规划输入能力

| 能力 | 入口 | 行为 |
|---|---|---|
| 获取软件静态地图 | `get_cognitive_map(software_id, level_id?, detail?)` | 返回层级与控件清单（不含动态值） |
| 罗列已建图软件 | `list_software(with_summary?)` | 返回 software_id 列表 + 控件总数 |
| 实时点击桥 | `click_element(name, automation_id, control_type, target, click?)` | 重新 build_world_model + 实时定位 + 真实点击 |
| 实时界面感知 | `describe_window(target, mode, ...)` | uia 模式（默认）/ full 模式（追加 OCR） |

### 1.3 推理中枢能力（路线推断）

| 能力 | 入口 | 行为 |
|---|---|---|
| 路径记忆命中 | `query_route(software_id, intent, ...)` | 同意图签名 Jaccard ≥ 0.5 + 样本数门限 |
| 语义关键词推断 | `_intent_to_capabilities(intent)` | 词库反向匹配（中文 1-gram/2-gram + 英文整词） |
| LLM 兜底 | `infer_route(...).needs_llm=True` | 返回紧凑上下文，待上层调 LLM 一次后落盘 |
| 置信度三档决策 | `_decide(confidence, stale)` | trusted ≥ 0.80 / verify ≥ 0.40 / weak < 0.40 |
| 跨层联动佐证 | `_assess_linkage(software_id, steps)` | 转移规律层 + 坐标记忆层双向校验 |
| 全局联动度审计 | `linkage_report(software_id)` | 四子系统覆盖 × 路线佐证率 |

### 1.4 缓存层自演化能力

- **Atlas 动态蒸馏**：每次 `build_world_model` 自动调用 `derive_and_merge`，按 `software_id` 增量合并新 level
- **置信度渐进累加**：执行成功 +0.10、转移/坐标联动佐证 +0.08/+0.06、单次 LLM 落盘只给基线 0.12
- **结构签名门控**：软件更新导致控件结构变化 → 路径记忆 stale 标志 + 0.4 降权
- **噪声过滤**：通用噪声控件类型与名称（标题栏/菜单栏/搜索框等）不计入预测
- **Fail-soft**：storage 砖未就绪时仅留进程内缓存，绝不抛异常

---

## 2. 架构组成

### 2.1 物理模块分布

```
backend/app/tools/gui/
├── world_model.py                  # 实时世界模型：UIA + OCR 融合 + 渲染
├── atlas_tool.py                   # 接入层：get_cognitive_map / list_software / click_element / describe_window
├── automation_orchestrator.py      # 推理中枢入口：execute_gui_intent
└── world_model_cache/
    ├── __init__.py                 # 导出 derive_and_merge / SoftwareRegistry
    ├── schema.py                   # 数据模型：software_id 派生 / 角色分类 / 能力词库
    ├── registry.py                 # SoftwareRegistry：进程内单例 + storage 砖落盘
    ├── distiller.py                # 瞬时世界模型 → Atlas 草稿
    ├── diff.py                     # 增量合并：按 identity 对比 + label 更新
    ├── integration.py              # 顶层：derive_and_merge = 蒸馏 + 合并 + LLM 兜底
    ├── path_memory.py              # 路线记忆 + 置信度校准常量
    ├── transition_model.py         # 动作→控件集合统计
    ├── coord_memory.py             # 归一化坐标 + 指数滑动平均
    └── reasoning_hub.py            # 三级推断 + 决策 + 联动度审计
```

### 2.2 数据流总览

```
                    describe_window (LLM 规划输入)
                            │
                            ▼
    ┌─────────────────────────────────────────────────┐
    │           build_world_model(target)             │
    │  ① 目标窗口解析（hwnd / 标题子串 / 前台）        │
    │  ② 截图（mode=window 仅目标 / mode=full 全屏）   │
    │  ③ build_uia_tree(hwnd)         结构通道       │
    │  ④ image_retrieval(screenshot)  像素通道       │
    │  ⑤ fuse(uia, ocr, hwnd, screen_rect)  融合     │
    │  ⑥ render_world_model + render_world_model_svg 落盘
    │  ⑦ derive_and_merge(model)  →  异步蒸馏进 Atlas │
    └─────────────────────────────────────────────────┘
                            │
                            ▼
            world_model JSON (meta + uia_tree + visible_layer)
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
   get_cognitive_map   click_element       describe_window
   (规划输入·结构)     (执行桥·实时)        (实时感知·控件清单)
        │                   │                   │
        ▼                   ▼                   ▼
   reasoning_hub      executor / run_automation   ...
   (三级推断)              │
   ① 路径记忆            ▼
   ② 语义推断         Path Memory 回写
   ③ LLM 兜底         (置信度渐进累加)
```

### 2.3 分层职责

| 层级 | 模块 | 职责 | 是否运行态 |
|---|---|---|---|
| **L1 实时世界模型** | `world_model.py` | 把一个窗口翻译成结构化 JSON（瞬时态） | 是（每次重新构建） |
| **L2 静态地图** | `world_model_cache/{schema,distiller,diff,registry,integration}.py` | 累积多次观察形成软件静态结构认知（Atlas） | 否（仅描述"有什么"） |
| **L3 成功路线** | `path_memory.py` | 累积"LLM 规划成功 + 执行成功"的经验步骤序列 | 否（仅描述"怎么走"） |
| **L4 动作转移** | `transition_model.py` | 累积"动作 label → 后续界面控件集合"的统计 | 否（仅描述"走完会变什么"） |
| **L5 归一化坐标** | `coord_memory.py` | 累积控件相对窗口的归一化包围盒（指数滑动平均） | 否（仅描述"上次在哪"） |
| **L6 推理中枢** | `reasoning_hub.py` | 把"意图 + 软件"翻译为"路线决策（trusted/verify/weak）" | 否（仅做决策） |

L1 是瞬时态的真实反映；L2-L5 是历史累积的认知；L6 是基于前两者的决策。L2-L5 严格正交——任何一层缺失，LLM 仍能工作（其他层静默降级），只是联动度降低。

### 2.4 推理中枢三级推断

`reasoning_hub.infer_route()` 是执行器与世界模型缓存的桥梁：

1. **路径记忆命中**（`source=memory`）：按 `software_id + intent_signature` 在 `path_memory` 中查询 Jaccard ≥ 0.5 的成功路线，零 LLM 调用
2. **语义关键词推断**（`source=inferred`）：从 `schema._WORD_TO_CAPABILITY` 词库把意图翻译为能力标签，与 Atlas 控件匹配，零 LLM 调用
3. **LLM 兜底**（`source=llm_fallback`）：返回紧凑上下文（已建图控件库 / 路线统计），调用方调 LLM 一次后 `confirm_and_save` 落盘

### 2.5 接入层与执行器的关系

- `atlas_tool` 的 4 个工具（`get_cognitive_map` / `list_software` / `click_element` / `describe_window`）面向 LLM，提供"规划输入 + 实时定位桥"两类能力
- `describe_window` 是"快路径感知"——UIA 模式默认 304ms，full 模式 3617ms（12 倍慢），仅在 UIA 不可用应用或 Atlas 建图时使用 full
- `click_element` 与 `find_control` 的核心区别：`click_element` 每次重新 `build_world_model` 后真实点击；`find_control` 接受外部已构建的 model 仅做解析
- `automation_orchestrator.execute_gui_intent(software_id, intent)` 把"路线推断 → 执行 → 回写"封装为一步闭环，外部注入 `llm_planner_fn` / `executor_runner` / `verify_fn` 即可测试

---

## 3. 双通道融合机制

### 3.1 两条通道的本质差异

| 通道 | 数据源 | 输出 | 优势 | 短板 |
|---|---|---|---|---|
| **结构通道（UIA）** | Windows UI Automation 原生控件树 | 控件类型 / 名称 / automation_id / 坐标 / 父子层级 | 机器可读、像素无关、快（~304ms） | 漏自绘控件 / 渲染文本 |
| **像素通道（OCR）** | 窗口截图经 OCR 引擎 | 文本 + 包围盒 | 反映"人眼真正看到" | 跨窗口污染、慢（OCR ~522ms） |

两条通道不是冗余，而是**互相校核**：UIA 告诉"应该有什么"，OCR 告诉"实际画出了什么"。

### 3.2 融合策略

`_match_ocr_to_uia(ocr_items, flat, tree_root, target_hwnd)` 实现双策略归属：

1. **语义归属（优先）**：归属链上至少一个节点名称命中 OCR 文本才算认领
2. **几何兜底（强化状态文本）**：无名称命中、但文本中心点经像素所有权测试确属目标窗口时，归属到最小可见包含节点

像素所有权测试 `_point_owned_by(hwnd, cx, cy)` 通过 `WindowFromPoint + IsChild` 判定文本真实归属——叠在目标之上且不透明的别窗文本永不误认领（"已连接，安全"这类状态描述文本最常见）。

### 3.3 三张清单与可见层级

融合产物是三张清单：

- `ocr_matched`：OCR 文本盒归属到具体 UIA 节点（带 `matched_via` 标记 `semantic` / `geometric`）
- `image_only`：OCR 见到但 UIA 未认领（UIA 漏掉的自绘元素 + 窗口外背景）
- `structure_only`：UIA 可见但无 OCR 文本（图标 / 图形 / 空容器）

外加一张二维包含树 `visible_layer`——以整屏为最外层，按面积升序把每个 OCR 文本盒挂到最小包含者之下，给出"屏幕上什么文字落在哪个区域里"的像素级佐证。

### 3.4 双通道鉴别力实证

`docs/世界模型评估报告.md` 2026-08-11 全屏版评估（Visual Studio，hwnd=2883864，2311×1416 近乎全屏）：

- OCR 序列化零损失：Recall = Precision = IoU = 1.000，中心偏差 0.0px
- 结构自洽：231 节点、26 被 OCR 确认、计数自洽、字段完整
- 双通道零异常：89/89 命中盒全部在窗口内，21 个 image_only 中 19 个正确归为背景，2 个窗口内异常均为桌面图标（像素所有权闸门正确判别）
- 几何兜底韧性：菜单项带加速键后缀「(F)」纯语义归属失败时自动回退几何，仍正确认领

---

## 4. 四层缓存与正交协作

四层缓存围绕"瞬时世界模型"分别累积不同维度的历史认知。它们严格正交——任何一层缺失不影响其他层工作，但联动度会降低。

### 4.1 Atlas 静态地图（L2）

**回答的问题**：这个软件有什么界面和控件？

- **数据模型**：按 `software_id` 聚合的多 `level` 结构（`level_id` 由"被选中的导航项"启发，无导航软件统一归 `default`）
- **节点 identity**：`{control_type}[{automation_id or #index}]` 路径拼接，跨会话稳定
- **角色分类**（`schema.classify_node`）：toggle / editor / status / list / nav / button / menu / tab / link / combobox / container / image / slider / control
- **动态占位**：开/关态、编辑文本、状态文本、列表内容只标 `{kind: variable, reason: ...}` 占位，**绝不存具体值**——这是 Atlas 的核心铁律
- **能力标签**（`schema.derive_capability`）：由名/角色推导（结构性、零 LLM），供推理中枢关键词→控件纯规则匹配
- **增量合并**（`diff.merge_level`）：按 identity 对比，文本差异仅更新 label，不分裂新节点；同位置不同显示内容判同节点
- **持久化**：经 storage 砖 `gui_atlas` 分类落盘，文件命名 `{software_id}.json`

### 4.2 路径记忆（L3）

**回答的问题**：LLM 怎么规划这条路线曾成功过？

- **双层记录**：正常路线（`routes`，LLM 成功路径）+ 异常路线（`exceptions`，LLM 纠正/兜底路径）
- **意图签名**（`intent_signature`）：去停用词 + 中文 1-gram/2-gram + 英文整词，语序无关；Jaccard ≥ 0.5 算同意图
- **置信度校准常量**：
  - 基线 `_TRUST_INIT = 0.12`（单次 LLM 落盘）
  - 规划再确认 `_TRUST_PLAN = 0.14`
  - 执行成功 `_TRUST_EXEC_OK = 0.10`（越用越准的核心回写）
  - 转移/坐标联动佐证 `_TRUST_TRANSITION = 0.08` / `_TRUST_COORD = 0.06`
  - 执行失败 `_TRUST_EXEC_FAIL = -0.28`（直接降信任）
- **信任带**：`TRUST_HIGH = 0.80`（纯推理直执行）/ `TRUST_MID = 0.40`（推理但事后校验）/ 之下仍走 LLM
- **结构签名门控**：`structural_sig` 由当前 Atlas 控件类型+静态名集合哈希计算，不一致即判 stale 并降权 0.4
- **持久化**：经 storage 砖 `gui_routes` 分类落盘

### 4.3 转移规律层（L4）

**回答的问题**：点 X 后界面通常出现哪些控件？

- **数据模型**：纯统计高频共现——`(software_id, action_label) → {(control_key): count}`
- **置信度**：`count / samples`（每次出现 +1，不存派生值）
- **最小样本门限**：`min_samples = 3`，避免单次偶发观察被当成置信度 1.0 的铁律
- **查询接口**：
  - `query_expected(software_id, action_label, threshold, min_samples)` 单动作预期控件
  - `query_software_expected(software_id, ...)` 全局高频控件（规划先验）
- **噪声过滤**：与 `atlas_tool` 对齐的 `_NOISE_CT` / `_NOISE_NAME`（标题栏/菜单栏/搜索框等不计入）
- **持久化**：经 storage 砖 `gui_transitions` 分类落盘

### 4.4 坐标记忆（L5）

**回答的问题**：这个控件上次在窗口的什么位置？

- **数据模型**：归一化包围盒 `(nx, ny, nw, nh)`，nx/ny/nh/nw ∈ [0, 1]
- **越界拒绝**：坐标超出窗口边界直接拒绝写入
- **指数滑动平均**：半窗更新（`a = 0.5`），抑制单次噪声
- **可信样本门限**：`get_coord` 在样本 < 2 时返回 None（单次噪声不可信）
- **执行器接入**：
  - `_coord_memory_lookup`：denormalize 历史归一化坐标 + O(1) 命中测试（`ControlFromPoint`），跳过 UIA 树遍历
  - 身份不符（aid/name 不匹配）立即回退到常规 `find_control_direct`，绝不盲点
- **持久化**：经 storage 砖 `gui_coord_memory` 分类落盘

### 4.5 跨层联动佐证

`reasoning_hub._assess_linkage(software_id, steps)` 在**读取期**为路径记忆命中提供增量信号：

- **转移佐证**：相邻步骤的"动作 label → 下一控件"是否在 transfer 记录中 ≥ 0.4 出现比例 + 最小样本 2
- **坐标覆盖**：每个步骤是否在 `coord_memory` 已有命中（兼容 `name|aid|ct|click` 与 `ct|aid` 两种键格式）
- **返回值**：`{transition_corroborated: bool, transition_rate: float, coord_coverage: float}`
- **作用**：临时上浮置信度（不写存储），让"路径记忆 + 跨层佐证"的组合更快进入 trusted 带

### 4.6 全局联动度审计

`reasoning_hub.linkage_report(software_id)` 输出全局健康度：

- **四子系统覆盖**：`atlas` / `path_memory` / `transition` / `coord_memory` 各占 1/4
- **路线佐证率**：每条正常路线的步骤链是否被 transfer 整体支持
- **联动度评分**：`coverage * 0.6 + corr_rate * 0.4`，0~1 标量
- **缺子系统静默降级**：缺失时分值自动下降，提示"哪一层还没建好"

---

## 5. 关键设计决策

### 5.1 Atlas 铁律：只存结构，禁存动态值

Atlas 持久化只描述"有什么 UI"——控件类型、静态标签、控件间关系。开关的开/关态、编辑文本、状态文本、列表内容等运行态值**绝不**落盘：值的新鲜度由"执行前实时重扫"保证。

这条铁律避免三件事：
- 软件更新导致 Atlas 失效时连带污染所有派生决策
- 隐私数据（用户编辑过的文件名/聊天记录）意外持久化
- 置信度校准被"过时状态"污染

### 5.2 静态地图与运行态严格分离

`atlas_tool.GetCognitiveMapTool` 明确告诉 LLM："Atlas 不是运行时状态：拿到地图规划后，真实点击前仍需由 GUI 工具实时重扫屏幕定位"。

`atlas_tool.click_element` 每次重新 `build_world_model` 拿到实时树，绝不直接用 Atlas 的坐标当运行时位置。这一分离保证了：
- 软件布局微调（按钮换位、DPI 变更、分辨率变化）不影响规划
- LLM 拿到的是"知识"而非"幻觉"

### 5.3 置信度渐进校准

`_TRUST_INIT = 0.12` 的设计哲学："绝一次 LLM 命中就直接全部使用推理"。需要满足：
- 单次 LLM 落盘只给 0.12（远低于 MID）
- 多次执行成功 / 跨层佐证才能越过 MID 进入 verify
- 多次联动佐证才能越过 HIGH 进入 trusted

这一设计抵抗两类风险：
- 偶然成功的路线被永久高估（`_TRUST_EXEC_FAIL = -0.28` 反向校准）
- 软件更新导致旧路线失效被继续信任（`structural_sig` 门控 + 0.4 降权）

### 5.4 像素所有权闸门

`_point_owned_by(hwnd, cx, cy)` 通过 `WindowFromPoint + IsChild` 判定 OCR 文本真实归属。这一闸门在双通道融合中**至关重要**——几何上落在目标窗口矩形内的文本，若该点真实可见的窗口是别窗（任务栏 / 浮动工具栏 / 桌面图标），绝不误认领。

实证数据：Visual Studio 全屏测试中，89/89 命中盒全部在窗口内，21 个 image_only 中 19 个正确归为背景，2 个窗口内异常均为桌面图标（中心落入近乎全屏的 VS 矩形内但实际属桌面）——闸门方向正确（欠认领 > 误认领）。

### 5.5 Fail-soft 落盘策略

四层缓存的读写全部经 storage 砖 capability，砖未就绪时：
- 进程内缓存仍工作（单例 `_cache` dict）
- 落盘调用静默返回 `False`，不抛异常
- 读取调用返回 `None`，调用方按"未建图"处理

这一设计让世界模型缓存与 storage 砖解耦——storage 砖升级、迁移、暂时不可用都不影响运行时推理中枢决策。

### 5.6 UIA 优先 + OCR 兜底

`describe_window` 的 `mode` 参数固化这一原则：默认 `uia`（仅结构，304ms），`full` 才追加 OCR（3617ms）。这一原则贯穿所有四层缓存——OCR 只在 L3 兜底、Atlas 建图、状态文本归属时介入，正常路径不碰 OCR。

---

## 6. 可参考的外部研究

世界模型的设计取舍与外部 GUI 智能体研究领域的多项成果同源。下列文献是设计决策的对照与扩展基础。

| 研究 | 核心问题 | 与世界模型的对应 |
|---|---|---|
| **SeeAct** [Zheng et al., 2024] | Web 任务的"看-决策-执行"分离 | 描述-规划-执行三段式映射到 `describe_window` → `infer_route` → `executor` |
| **WebVoyager** | 多站点 Web 任务的多模态感知 | 印证 UIA + OCR 双通道在真实站点的有效性 |
| **ShowUI / SeeClick** | GUI 视觉 grounding | 印证视觉通道在自绘控件场景的必要性（OmniParser 调研方向） |
| **OmniParser** [Lu et al., 2024] | YOLO 框选 + Florence-2 描述的视觉解析 | 调研中作为 UIA 真空区（自绘/游戏/Web canvas）的视觉兜底 |
| **AITW / Mobile Agent** | 跨设备移动 GUI 任务 | 跨设备归一化思路为 `coord_memory` 提供先验 |
| **OSWorld 2.0** | 长链路跨工具任务 | 印证"路径记忆 + 转移规律层"在长链路上的必要性 |
| **Android World** | 真实 Android 设备的代理评测 | 提供 Android 端世界模型设计的迁移参考 |

### 6.1 与世界模型设计的具体对照

- **SeeAct 的"看-决策-执行"分离**与 `describe_window` → `reasoning_hub.infer_route` → `executor` 的三段式映射是同一架构思路的桌面实现
- **WebVoyager 的多模态感知**验证 UIA + OCR 双通道在真实 Web 任务中的有效性——与 `atlas_tool` 的 mode 切换机制同源
- **ShowUI / SeeClick 的视觉 grounding**研究显示图标按钮等 OCR 漏不掉的盲区需要视觉通道补充；OmniParser（YOLO + Florence-2）已在调研清单，作为 UIA 真空区备选方案
- **AITW 的跨设备归一化**为 `coord_memory` 用"窗口内归一化坐标 + denormalize"提供先验，与之相比桌面实现的额外优势是窗口尺寸更稳定（不像移动设备差异巨大）
- **OSWorld 2.0 的长链路跨工具任务**为路径记忆 + 转移规律层在长链路上的必要性提供外部佐证——任务越长越需要"上次怎么走 + 走完会变什么"的双重记忆

---

## 7. 指标与健康度

世界模型缓存层通过 `linkage_report(software_id)` 输出全局健康度，核心字段：

| 指标 | 含义 | 健康阈值 |
|---|---|---|
| `has_atlas` | 是否有静态地图 | True 表示已建图 |
| `ok_routes` | 正常路线数 | > 0 表示经验开始积累 |
| `exceptions` | 异常处理路线数 | 反映"踩坑-学习"循环 |
| `transition_samples` | 转移规律累计样本 | > 30 表示预测可信 |
| `coord_count` | 坐标记忆条目数 | > 0 表示坐标开始可用 |
| `corroboration_rate` | 路线佐证率 | > 0.6 表示联动充分 |
| `linkage_score` | 联动度评分 | > 0.5 表示四层开始协同 |

`coord_memory.get_coord_stats` 单独报告：控件总数 vs 已达可信样本（≥2）的数量，反映坐标记忆的"可信率"。

---

## 8. 演进路径

世界模型从"瞬时感知"到"全栈联动"经历四个阶段：

### 阶段 1：实时世界模型（当前已完成）
- UIA 树 + OCR 融合、三张清单、可见层级、文档级重建
- 全部窗口可被"看"成结构化数据
- 性能：UIA 模式 304ms / Full 模式 3617ms / 视复杂度浮动

### 阶段 2：静态地图 Atlas（当前已完成）
- 蒸馏 + 合并 + LLM 兜底（仅多 level 高重叠冲突时）
- 静态地图供 LLM 规划，避免每次 LLM 重新发现 UI
- 性能：背景异步落盘不阻塞世界模型产出

### 阶段 3：路径记忆 + 转移规律（当前已完成）
- 路径记忆：经验路线 + 异常处理路线 + 置信度渐进校准
- 转移规律：动作 label → 后续控件集合统计
- 联动佐证：跨层证据合并，临时上浮置信度
- 效果：常用任务从"LLM 规划"演进为"纯推理直执行"

### 阶段 4：跨设备 / 跨工作流联动（未来）
- OmniParser 视觉兜底接入（自绘控件 / Web canvas）
- 跨显示器 / 跨 DPI 坐标记忆的多维索引
- 多窗口协同任务（拖拽 / 跨应用复制）的路径记忆扩展
- 视觉-语义联合 grounding（OmniParser 框 + UIA 控件配对）

---

## 9. 扩展点与未决问题

- **OmniParser 集成**：UIA 真空区（自绘控件 / 游戏 / Web canvas）可接入 OmniParser（YOLO 框选 + Florence-2 描述）作为视觉兜底
- **跨显示器坐标记忆**：`coord_memory` 当前按 `software_id` 分桶，可扩展按显示器类多维索引
- **路径记忆的语义去重**：当前按 `intent_signature` 哈希分桶，相似但不同义的意图可能误并；可引入 embedding 检索
- **结构签名漂移检测**：当前 `_level_struct_sig` 仅在路径记忆查询时门控，可扩展为定期巡检，提示"软件已更新，是否重建 Atlas"
- **外部基准接入**：OSWorld / WebArena / VisualAgentBench 的世界模型快照可直接蒸馏为 Atlas，作为正式回归测试集

---

## 10. 相关文档

- `docs/自动化执行器架构设计.md`（执行器砖块架构设计，与本文件并列）
- `docs/GUI自动化执行器.md`（v1.0 运行笔记，侧重实测数据）
- `docs/世界模型评估报告.md`（2026-08-11 全屏版 Visual Studio 评估，OCR/结构/双通道三关全过）
- `docs/模块复用性分析报告.md`（2026-08-12 模块复用性评估，world_model_cache 评为高复用候选）
- `backend/app/tools/gui/atlas_tool.py`（4 个接入层工具）
- `backend/app/tools/gui/automation_orchestrator.py`（推理中枢入口 `execute_gui_intent`）

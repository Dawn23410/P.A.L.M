# GUI 自动化执行器（实时感知 → 批量执行闭环）

> 版本：v1.0（2026-08-12，基于代码与实测）
> 版本记录：v1.0 首次成文，同步执行器/感知/OCR 引擎全部现状。

## 1. 闭环总览

桌面 GUI 自动化采用「实时感知 → 规划 → 批量执行 → 验证 → 收尾」五环节闭环，LLM 只介入规划一次：

```
describe_window（感知）→ LLM 规划 run_automation steps → 执行器批量执行
→ check 状态验证（stop_if 短路）→ close 收尾
```

| 环节 | 工具/机制 | 关键点 |
|---|---|---|
| 感知 | `describe_window`（mode=uia 默认 / full 可选） | uia 模式仅 UIA 结构 ~304ms/+1MB，**实时感知默认只用 UIA，不做 OCR**（用户拍板） |
| 规划 | `run_automation` spec 教导 | check 状态先验 + stop_if 短路 + 用完 close 的洁癖教导 |
| 执行 | executor.py（L0-L3 容错 + 状态机） | 定向查找主路径 ~10-30ms，失败逐级回退 |
| 验证 | `check` 动作（TogglePattern 读状态） | 开关类控件状态先验，`stop_if=1/0` 命中即短路 |
| 收尾 | `close` 动作（close_window） | 关闭按钮→Alt+F4→保存对话框(不保存)→复查，诚实返回 |

## 2. 执行器（executor.py + executor_locator.py）

- **工具**：`run_automation` —— steps 数组顺序真实键鼠执行，动作 click/type/press/hotkey/wait/check/close。
- **L0-L3 四级容错**：
  - L0 树不变直点缓存坐标；L1 树变但目标控件位置未变；L2 位置变则重定位+更新缓存；L3 全变才 OCR 兜底+增量学习。
- **定位主路径**：定向查找（`Control()+Exists()`，SubName/AutomationId 大写驼峰条件）替代全树 build_uia_tree（560-1200ms → 10-30ms）；depth 自适应（先 12 快查，失败再 24 深查，适配 SystemSettings 深层控件）。
- **状态机**：Idle→Executing→Paused→Cancelled；鼠标被用户移动 >50px 自动中断（屏蔽执行器自身移动）。
- **防卡死**：run 总超时 60s + wait 单步限幅 10s。
- **鲁棒回退链**：窗口解析（hwnd→标题→software_id→last_hwnd→前台诊断）；控件定位分级（全条件→降 automation_id→降 control_type→纯 name→重试→OCR→全树模糊）；失败带近似控件 Top3 诊断。
- **close_window 保存对话框处理**：未保存内容关闭时 Alt+F4 被「是否保存」对话框拦截 → Alt+N（不保存）→ 复查窗口存活，诚实返回不假成功。
- **uiautomation fork 两个坑**（已实锤写死）：`GetFirstChildControl` 不用条件必须 `Control()+Exists()` 模式；属性键必须大写驼峰。

## 3. OCR 引擎分层（ocr_engine.py）

`get_ocr_engine()` 三级自适应：**DML GPU → OpenVINO CPU → onnxruntime CPU**，逐级降级；启动空图预热一次（shader/图编译不计入真实 OCR）；`PALM_OCR_MOBILE=1` 可切轻量模型（文件缺失静默回退 v3）。

| 引擎 | 全屏稳态 OCR | 内存 | 性质 |
|---|---|---|---|
| DML GPU（DirectX12 通用） | 522ms | +494MB 系统 / +1.5GB 显存 | 首选 |
| OpenVINO CPU（C++ 内核） | 549ms | +1.36GB | 无 GPU 回退 |
| onnxruntime CPU | 2.9s（8线程） | ~+500MB | 兜底 |

**OCR 定位**：执行主路径（L0/L1/L2）不碰 OCR；OCR 只用于 L3 兜底、`click_text`、Atlas 建图。世界模型全量转义稳态 ~1.35s（引擎常驻+预热后）。

## 4. 感知模式决策（全量 vs 仅 UIA 实测）

设置窗口（UIA 219 节点）实测：

| 指标 | 仅 UIA | 全量（UIA+OCR） |
|---|---|---|
| 耗时 | 304ms | 3617ms（12 倍） |
| 内存 | +1MB | +452MB（452 倍） |
| 控件清单 | 39 个 | 39 个（相同） |

结论：UIA 完整应用下 OCR 零增量且引入跨窗口污染 → **每次开界面感知默认仅 UIA**；全量只用于 UIA 不可用应用/Atlas 建图/文本级理解。

## 5. 实测数据（本机）

| 指标 | 数值 |
|---|---|
| 定向查找（浅层） | 28-60ms |
| 定向查找（深层 SystemSettings） | 515ms（depth24） |
| 记事本 4 步闭环（点菜单/escape/close） | ~1.9s |
| 开 HDR 总流程（minimax-m3） | 12.3-15.4s（LLM 规划 4-7s + 执行 4-6s + 世界模型 1.4-1.6s） |
| check 状态先验短路（已开不重开） | 65ms |
| close_window（保存对话框场景） | 窗口真关 ✓ |
| 真实 Agent 自主闭环（记事本感知→执行→输入→收尾） | 多轮 ReAct 自主完成 ✓ |

## 6. 相关文件

- `backend/app/tools/gui/executor.py`（执行器 + run_automation）
- `backend/app/tools/gui/executor_locator.py`（定向查找/开关读取/关窗）
- `backend/app/tools/gui/ocr_engine.py`（OCR 引擎分层）
- `backend/app/tools/gui/world_model.py`（世界模型构建，build_world_model mode=window/full）
- `backend/app/tools/gui/atlas_tool.py`（describe_window / get_cognitive_map / click_element）
- `Data/skills/desktop-visual-operator/SKILL.md`（闭环链路教导）
- `Data/skills/gui-atlas-planner/SKILL.md`（规划前置：Atlas 静态认知，仅规划非运行态）

## 7. Office 专项优化（2026-08-12）

**核心结论：Office UIA 完整可读（纠正初判误判）**——Word Ribbon 命令按钮全有 name+automation_id+坐标（加粗=Bold、字号=FontSize、粘贴=Paste、TabItem=TabHome/TabInsert），`build_uia_tree`/`describe_window` 完整命中；之前「Ribbon UIA 空洞」是探测脚本过滤误判。Office 真正瓶颈是长步骤链 + LLM 决策累积，不是 UIA。

专项优化（无任何硬编码位置图，全部通用化）：
1. **感知层**：`_controls_summary` limit 60→120 + 超限按可交互控件（Button/SplitButton/CheckBox/TabItem 等）优先裁剪——保证复杂应用命令按钮不丢。
2. **快捷键映射**：`desktop_control.hotkey` vk_map 补全（导航/编辑/功能键/符号键 OEM 区），多软件通用不绑 Office；executor hotkey 键名归一化（LLM 大写首字母自动小写）。
3. **视觉框选互补（调研结论）**：OmniParser（微软开源，YOLO 框选交互元素 + Florence-2 描述 + grounding，V2 延迟 ~0.8s@4090）可作 UIA 真空区（自绘控件/游戏/Web canvas）的视觉兜底，与 UIA（快+语义）互补；当前 UIA 已覆盖 Office，OmniParser 定位为可选增强。

**Office 任务推荐路径**（两路都可行）：
- 快捷键路径：hotkey ctrl+b/a/s 等（一步到位，Word 实测成功）
- 点击路径：定向查找 Ribbon 命令按钮（Bold/FontSize 等 aid，同样可行）

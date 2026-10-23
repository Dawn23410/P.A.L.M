# P.A.L.M 项目记忆（Trae 风格双日志 · 项目级）

> 本文件对应 Trae 的 `project_memory.md`，为项目级长期记忆（架构/约束/经验），使用正式术语。
> 双日志约定（源自项目工程规范）：聊天日志 `session_memory_*.jsonl` 保留原始术语记录逐次对话；本文件与 `logs/architecture_log_vX` 使用正式术语记录架构决策。
> 逆推重建说明：07-22~08-09 的 `session_memory_*.jsonl` 由 git 提交历史（`git log`）逆推生成，条目标注 `compact_summary_meta.reconstructed=true`；08-10 起为实时记录。

## Hard Constraints（硬约束）

- display 显示层砖块需合并壁纸引擎与组件引擎功能
- 穿透模型简化为 OS 级全有或全无，交互类组件初期使用完全不穿透模式
- 组件窗口尺寸应尽量贴合实际交互区域，减少空白区域点击拦截
- 组件形状仅允许矩形（border-radius ≤ 短边20%）或圆形（border-radius: 50% + 宽高相等），禁止其他异形
- All data acquisition must go through the backend; components cannot directly call APIs
- No simulated data support; display 'N/O' when data is unavailable
- Backend data source collection intervals should be consistent, preferably 0.5s (except audio which uses 30fps independent thread)
- Audio rhythm should directly obtain speaker parameters without complex music matching
- 视觉和键鼠模拟功能必须强化，作为通用工具使用
- Trivial tasks (memory compression, planning, reflection) must use flash_model via `select_model("trivial")` with fallback to main model if unconfigured
- Screenshot tools must send mixed information to the model, including OCR recognition content, ASCII outline escaping, and image metadata text
- Screenshot tools have an optional `send_image` parameter; default sends ASCII-escaped images, parameter enables sending original images
- Screenshot artifacts marked as `internal: True` are not displayed to the user (intermediate files)
- ASCII image escaping must be moderate, balancing token consumption and detail preservation
- Original image sending is only compatible with vision models (e.g., GPT-4o / DeepSeek-VL); non-vision models use ASCII+OCR fallback
- 声纹验证失败时主Agent用角色语气回应拒绝语（台词由角色卡片配置读取），然后进入30秒静默期（STT继续监听但不处理）
- 声纹置信度提供三档用户可调：宽松(0.35)、默认(0.45)、严格(0.55)
- KWS关键词命中仅触发STT转录，无直接判定权，所有打断判断统一走语义分析流程（规则关键词+FastText模型）
- DeepSeek V4 Pro/Flash models must use `extra_body={"enable_thinking": false}` to disable internal reasoning for reduced TTFT
- Boss (Reflex层) must have an empty tool registry to prevent tool calls; `max_iterations` set to 2 as double insurance
- 工具安全链路异常时采用 fail-closed 机制（安全闸门故障时拦截操作）
- 专业Agent私有存储区（ProfessionalMemory）仅存储经验总结、用户画像、错误记录，采用基础关键词检索，主Agent运行时不可读
- 专业Agent任务完成后异步整理经验，不阻塞主Agent返回结果
- 专业Agent新任务启动时动态注入3-5条相关经验，写入时合并同类项以提高信息密度
- GUI操作需遵循合理类人逻辑：打开的标签页、窗口、弹窗、文件选择器等用完必须清理
- 通用键鼠操控优先考虑速度和稳定性，无方法限制
- `desktop-visual-operator` Skill 为通用 GUI 操作工具，适用于桌面软件、浏览器、系统窗口、设置页、文件选择器、弹窗、表单等场景
- `desktop-visual-operator` Skill 仅在处理桌面、浏览器、键鼠、截图、OCR、搜索框、资料页等任务时自动注入，不污染普通对话
- `desktop-visual-operator` Skill 必须包含 OCR 证据凝聚功能
- `desktop-visual-operator` Skill 外部描述需明确 `Invoke when` 触发条件

### 砖架构铁律（本项目核心约束，Trae 期前已确立并贯穿全程）
- 三层解耦：FastAPI(纯HTTP) / React SPA(仅fetch) / PyWebView(JS→Python 桥)
- 加砖 = `bricks/<name>/` + `bricks/__init__.py` import 一行（顺序即依赖序）；`base.py` 定义 `BrickManifest/Brick/BrickRegistry`
- **砖块严格互不调用**，跨砖只经 `capabilities`（缺失降级 None）；仅 `agent.tool_base.Tool` 可被子类化
- **新砖必须用相对导入**（`...core`/`...bricks`）；绝对导入 `app.*` 会注册到第二份 registry → 路由 404
- 外部插件砖(tts_sovits/qwen_tts/display)隔离在根 `plugins/`，经 `_load_plugin` 动态导入（缺失静默跳过）
- 安全加固链（H1 剥离工具结果注入；H2 删除走回收站+保险库归档；H3 文件工具限用户主目录；H4 后台命令守卫；M5 系统目录删/格式化硬阻断；M7 网络拒内网/回环；M9 只读工具进裁决引擎），异常时 fail-closed 拦截

## Engineering Conventions（工程约定）

- 组件类型分为纯观看类（使用 'full' 穿透模式）和交互类（使用 'none' 穿透模式）
- 项目日志分为聊天日志（保留原始术语）和架构日志（使用正式术语）
- 砖块注册需包含 name、is_core、bus 字段，display 砖块配置为 name=display, is_core=False, bus=pcie
- 悬浮组件默认 z-order 为桌面级（非置顶），可通过 alwaysOnTop 设置切回置顶模式
- Audio rhythm display uses a logarithmic frequency spectrum bar scheme with 24 vertical bars, left to right representing bass to treble
- Emotion detection uses regex-based phrase matching (frustration/happiness/anxiety/sadness/calm) in `emotion_detector.py`, mapping to valence/arousal values with Chinese cultural adjustments (e.g., '挫败' valence=-0.5, '悲伤' lower arousal)
- Reflection self-review triggers only after tool usage, with max 1 revision and degradation on parsing failures/errors
- ASCII image escaping uses 11-level gradient (space→`.:-=+*#%`→`@`) combining brightness levels and Canny edge detection
- Mixed screenshot information format includes: OCR text with normalized coordinates, 80-column ASCII gradient map with legend, and image metadata (dimensions/brightness/tone)
- Original images are sent as independent user messages with base64 PNG; ASCII content is wrapped in `[屏幕内容 ASCII 转义]` tags in tool observations
- KWS 功能采用 Sherpa-onnx 提供的中英双语预训练 ONNX 模型（zipformer-zh-en-3M），自定义关键词通过修改文本文件+CLI工具转换音素 token 实现
- 专业Agent采用任务级隔离记忆，每次任务创建独立 buffer memory，通过 TraceStore 记录执行轨迹供主Agent检索
- Skill 需进行结构测试、注册测试和加载测试
- 代码合规五条底线：函数≤50行 / 文件≤500行 / 单一职责 / 业务意图命名 / 最小修改（08-01 全面落实，贯穿后续）
- 全程使用中文（面向用户的说明、标签、状态均中文；代码标识符保留英文）

## Lessons Learned（经验与教训）

- CSS 级穿透无法实现真正的点击穿透，会导致下方窗口点击失效，需使用 OS 级穿透机制
- 组件窗口高度必须大于内容实际高度（含 padding + gap），否则 overflow:hidden 会裁剪底部导致圆角变形为异形
- 实现"桌面图标下方"层级需要 WorkerW 窗口重定向（SetParent），复杂且有兼容性风险，当前使用 HWND_NOTOPMOST 作为简化方案
- Frontend getDisplayMedia for audio capture has poor experience in pywebview/WebView2 environment; backend soundcard library for system audio loopback is preferred
- 视觉闭环存在根因：self._memory.add 仅存储纯文本，图像 artifacts 只进前端不进 AI 记忆，需检查 memory 和 LLM 消息构建是否支持多模态以确定改造方案
- koa-connect wrapper caused ctx leaks; native Koa rewrite required instead of wrapping Express middleware
- `reasoning_effort=none` and `no_cot=true` parameters are unreliable for disabling DeepSeek model reasoning; `enable_thinking=false` via `extra_body` is the only stable solution
- brick.py had duplicate empty `run_proactive_stream` definition causing Python parsing error; resolved by deletion
- `_wd_touch()` call missing "agent" parameter caused `TypeError`; fixed by adding parameter
- Emotion vector encoding must be asymmetric: only positive valence (v≥0) activates encoding consolidation to prevent negative memories from offsetting asymmetric decay
- 裁决引擎内部使用 asyncio.run() 会导致异步事件循环冲突，需进行 async 化改造（Trae 遗留待办）
- 专业Agent任务失败集中在工具执行闭环：能调用工具但无法稳定执行验证、停止和降级流程，需补充 Completion Gate、Result Verifier、Permission Resume Point 和 Failure Policy 机制
- **scheduler store 在 Windows 下 `os.replace` 遇外部进程锁文件抛 WinError 32，需指数退避重试吸收瞬时共享冲突（08-10 真实修复，原为绕过）**
- **crypto 可用性判定不能用 `is_enabled()` 加密总开关（默认关会误判不可用），应直接测 `operations.encrypt_data` 能否产出密文（gmssl 实测可用）**
- **存储重构已落地提交（a95e60d 批次）：整存储收为一块砖，介质层(存储芯片)+管理芯片(controller：quota/lifecycle/audit/health)，冗余层 vault/safe_delete 迁入 storage/redundancy，防环（storage 不 import sandbox）**
- **记忆层已升级为五因子情绪公式（r2）：W_imp×E_enc×T_em×R×E_ret，E_enc 仅 v≥0 激活（AI 正偏置，非人脑负偏置）；emotion_confidence=0 完全回退旧三因子**
- **双 Agent 架构（agent/dual）已实现：Reflex-Cortex，Boss 空工具表+max_iterations=2，Worker 独立 ToolRegistry+buffer memory，IntentRouter 四意图，TraceStore 分片检索，ProfessionalMemory 私有经验层**
- **Git：项目已首次推 GitHub（a130521..a95e60d，08-10），用户绿灯后按主题分 commit（存储/双Agent/基准/清理）推送；历史提交保持原样不重写**
- **语音链路实测结论（08-10）：GSV 为实时 TTS 主线（首字 0.49-0.71s），自定义音色用 CosyVoice 2 生成参考音频，Qwen TTS 降级为历史反例/备用；全链路延迟~2.3s，LLM 占~60% 主瓶颈**

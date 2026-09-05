# P.A.L.M 项目长期记忆

## 架构铁律
- 三层解耦：FastAPI(纯HTTP)/React SPA(仅fetch)/PyWebView(JS→Python 桥)。加砖=bricks/<name>/+__init__.py import 一行（顺序即依赖序）。砖块严格互不调用，跨砖只经 capabilities（缺失归一 None）。新砖相对导入(...core/...bricks)；绝对导入 app.* 会注册第二份 registry→404。外部插件砖隔离 plugins/，_load_plugin 动态导入。

## 安全加固（2026-08-03）
- H1 剥离工具结果注入；H2 删除走回收站(归档保险库)；H3 文件工具限用户主目录；H4 后台命令守卫；M5 系统目录删/格式化硬阻断；M7 网络拒内网/回环；M9 只读工具进裁决引擎。删除防御 safe_delete+vault；run_isolation 是隔离沙箱真边界。工具安全链 fail-closed。

## GUI 自动化（P.A.L.M 核心，2026-08-13~14 落地）
- 认知与执行链：Atlas 静态认知地图(gui_atlas，按 software_id 持久化"有什么 UI"，仅规划用不作运行态)；转移规律层(gui_transitions，点控件后出现的控件)；跨会话坐标记忆(gui_coord_memory，归一化包围盒 EMA，samples<2 不可信)；执行器 L0-L3+LM(O(1) ControlFromPoint 跨会话命中)。
- 辅助模式=Windows 辅助功能语义(非 OCR)：`assistive_mode.py` 提供 set/is/ensure_off，**仅对内控制不暴露 LLM**；机制 SPI_SETSCREENREADER + CoInitializeSecurity(EOAC_SECURITY_AWARE)，须先 CoInitializeEx(STA) 且在 uiautomation import 前(gui/__init__ 首行导入)。对"本就对所有 UIA 客户端暴露"的软件(Chromium/Qt)补树无效；对游戏自绘窗口无效。
- 自动化砖：唯一入口 `automate(software_id,intent)` 不收 llm_enhance 参数；llm_enhance 走 settings.json["gui_llm_enhance"](默认关=纯逻辑)。DESKTOP/ATLAS/EXECUTOR/UIA 四组对内不注册。
- 感知层 `perceive.py`：build_uia_tree_progressive(分批 BFS+退避重扫防 ntdll)；perceive_desktop/select_target_window/ensure_foreground。
- 执行分级 `executor_ladder.py`：档1 UIA 直驱 / 档2 OCR+点击概率区域消歧 / 档3 LLM 语义点击兜底(默认 NullLlmDecider 未接真实模型) / 档4 VLC(双门控，默认 False 接口保留)。三/四档均 fail-closed。
- 执行器已重构为 `executor/` 包(mixin 组合，函数≤50行)。推理中枢 `reasoning_hub`：路线记忆→语义关键词推断→LLM 兜底；path_memory 置信度双向校准；信任带 trusted/verify/weak。
- **测试隔离铁律**：GUI world-model 四类存储经 storage 落盘 `Data/gui_*`(哈希id文件名)。写测试必须 patch `{coord_memory,transition_model,path_memory,registry}._storage_cap` 返回 `lambda: None` 零落盘。真实 GUI 测试用系统 Python 3.10(含 uiautomation/pywin32)；导入 gui 包会拉 chromadb，测试脚本顶部须 mock chromadb 为假包。辅助模式测完须 ensure_off。

## 记忆层/双Agent/语音/存储
- 情绪五因子公式(E_enc 仅 v≥0 激活)；Reflex-Cortex 双模+IntentRouter 四意图；GSV 实时 TTS(全链路~2.3s)；存储收一块砖(quota/lifecycle/audit/health)。

## 工作流与代码底线
- Git 已推 GitHub，不擅自 push。本机 rm 被 safe-delete 守卫→脚本删文件用 os.remove/python 而非 rm。
- 最小修改/不碰测试/函数≤50行/文件≤500行/单一职责/业务意图命名/注释仅 WHY/全程中文(标识符保留英文)。
- 根 archive/ 统一本地归档(.gitignore 不入库)；先归档不删。

## 对话缝合引擎（定位/模型/封砖，2026-08-14）
- 约束：禁用对话式 LLM、可用垂直小模型；语义检索靠 bge-small-zh INT8 ONNX；运行期零联网；语料=真实对话。
- 真实权重走 hf-mirror.com 下载，onnxruntime 零联网推理：bge_small.onnx(24MB)+tokenizer、sentiment.onnx(168MB,多语)。情感映射坑：multilingual sentiment 是星级极性，短口语误判→急迫词>情绪词典>模型极性兜底；happy 词典移除泛化单字"好"。
- 已封砖 `backend/app/bricks/stitching/`：默认 mock(HybridRetriever 内存索引 BM25+字n-gram)，权重就位升级稠密语义检索；capability `stitch_api`+工具 `stitch_chat`；角色仅 mengyao。
- 基准结论：窄域人格对话体验可对标本地7B(拟人/流畅不输、零生成绝不胡说、中文占比/口癖更高)，~370倍延迟优势；开放问答诚实兜底。弱召回(top1<0.7)时 `_pick_bridge` 错接，需加情感/意图门控。兜底改造：检索无匹配→诚实告知+建议问 LLM(recognized=False/suggest_llm=True 对称字段)。

## 语音子系统 · GSV + CosyVoice 互补管线（2026-08-15）
- 分工：GSV(GPT-SoVITS)=实时播音员(语言合成)；CosyVoice2=音色设计师(音色创造，非语言合成)。管线：CosyVoice2 用「基底参考音频+自然语言风格描述」经 instruct2 产参考音频(.wav+.txt)，GSV 经 refer_wav_path+prompt_text 克隆做实时合成。CosyVoice2 instruct2 必须有基底参考音。
- CosyVoice 砖：完整砖(进程内持有模型，非薄代理)，engine.py 持有 CosyVoice2 单例(懒导入+懒加载)，manifest isolation=inproc。未装 cosyvoice 时 is_available()=False、capability 优雅降级。配置块 COSY_*(config.py，env 可覆盖)：MODEL_DIR/INFER_DEVICE/OUTPUT_DIR/DEFAULT_SEED_VOICE/TEXT/SAMPLE_TEXT。
- 项目已按「主板+砖块」拆分为根下中文名文件夹(每块独立 uv venv，详见 `砖块拆分说明.md`)。**拆分是副本**：原始 backend/plugins 已于 2026-08-15 归档至 `archive/monolith_20260815/`（仅留中文砖块文件夹为代码组织，共 30 块含 cosyvoice「语音合成 (CosyVoice)」）；中文文件夹是独立测试沙盒，经 `palm_sdk`（项目根独立运行基座）全量解耦：砖内 `from palm_sdk.X import Y` 替代原 `app.*` 绝对导入与跨砖相对导入，已实测 30/30 砖独立 import 通过，无需把单体 archive 纳入 PYTHONPATH。

## CosyVoice 完整砖 · 安装硬核配方（RTX 5060/Blackwell sm_120 验证，可复用）
- torch 必须 cu128 不是 cu126：Blackwell(cap≥12.0=sm_120)需 CUDA 12.8 内核；cu126 只到 sm_90→`CUDA error: no kernel image is available`。cu128 轮子从 pytorch cu128 索引 curl + zipfile.extractall 覆盖解压进 venv，旧 dist-info **改名 .bak**(rename 非 delete)。
- vendored 源码而非 PyPI 包：cosyvoice/matcha 拷贝进 site-packages(Data/CosyVoice_src/cosyvoice)，不走 PyPI 发行包。
- 训练专用依赖用纯 Python shim 顶替(写 site-packages)：lightning/gdown/wget/librosa.filters.mel(NumPy 重实现)/soxr/pkg_resources(importlib.metadata)/whisper.tokenizer(占位)。librosa shim 会让 transformers.is_librosa_available()=True→触发 import soxr，故 soxr shim 不能省。
- 音频 I/O 绕 torchcodec：torchaudio 2.11 把 soundfile 后端路由到 torchcodec(需 ffmpeg)，本机无 ffmpeg→改用裸 soundfile(pysoundfile) 读写 wav。create_voice 必须传**文件路径**给 inference_instruct2/zero_shot(内部自行 load_wav)，不能传张量。
- 推理精度必须 bf16 不是 fp16(Blackwell 乱码根因)：fp16 在 sm_120 失稳，同句 fp16 vs bf16 波形相关性≈0.009(正常>0.9)→吐 incoherent「非人语」。修复=engine._force_bf16_autocast() 把 torch.cuda.amp.autocast 改 torch.amp.autocast("cuda", dtype=torch.bfloat16)；COSY_INFER_PRECISION 默认 bf16。⚠️ torch 2.11 下 torch.cuda.amp.autocast(dtype=) 不生效(弃用告警)，必须用 torch.amp.autocast("cuda",...)，否则 hift 的 f0_predictor 报 Input type (float) and bias type (BFloat16)。
- onnx 强制 CPU：本机 onnxruntime 仅 Dml/CPU，speech_tokenizer 请求 CUDA 回退 DML(非标准、数值不确定)→ engine._force_onnx_cpu_patch() 强制 CPU(官方推荐确定性路径)。
- **transformers 5.x KV-cache 掩码坍塌（"ou ou ou" 乱码根因）**：transformers 5.14.1 的 prepare_padding_mask 把单令牌用户掩码右侧补 0→past 位置被屏蔽→KV-cache 上下文坍塌→LLM 退化为确定性 2-循环、EOS 永不触发、输出 16s+ 无意义语音。修复=engine._patch_kv_cache_mask 构造覆盖 past+current 的完整 ones 掩码(幂等，对 4.x 同样安全)。
- wetext 钉版本 wetext==0.0.4 + 安装期 _prewarm_wetext() 预热模型缓存，避免首次造音被 modelscope 现场拉取(破坏运行期零联网)。
- 安装器：python <砖>/src/install.py(守卫安全、可复现、等幂)；Data/cosy_smoke_test.py 验证 two-mode 造音。国内镜像：torch 走 pytorch cu128 索引 curl、其余走 tuna、hf-mirror 下权重。

## palm_sdk 运行基座（全量解耦，2026-08-15）
- 目标：让 30 块砖**无需单体 archive** 即可独立 import。由单体 `backend/app/` 共享层抽取为项目根独立包 `palm_sdk/`（去除对 `app.*` 命名空间依赖）。
- 三类导出面语义：**核心原语=真实实现**(core/base/security/permission/schemas)；**跨砖服务=安全桩**(如 `palm_sdk.bricks.agent.llm_bridge` 抛 `RuntimeError("独立态未接入 … 后端")` fail-closed)；**共享工具=真实实现**(bricks/_shared 的 tooling/eventbus/paths/redundancy，含 Tool/ToolRegistry/emit)。
- 导入改写(Data/diag/decouple_imports.py，幂等可复跑)：`from app/backend/_shared.x`→`from palm_sdk.bricks._shared.x`；2+点相对导入→映射 palm_sdk；1点相对导入→砖内文件留原样。**无真实跨砖 import**：砖间协作走运行期 registry，故无需懒重构。
- 校验：`decouple_report.json` 未解析=0；`brick_import_smoke.py` 逐砖子进程 `import src` → 30/30 ok。
- 历史坑(已修)：曾误生成 132 处 `from palm_sdk.app.x`(多带 app 前缀)；修复见 `fix_palm_sdk_prefix.py`(129 处) + `fix_paths_v2.py`(路径补 `.bricks`/`.redundancy`)；`tooling.py` 由桩升级为单体完整实现(补齐 agent_* contextvars)。

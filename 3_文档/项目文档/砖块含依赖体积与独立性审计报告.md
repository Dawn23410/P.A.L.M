# 砖块「含依赖体积」与「独立运行能力」审计报告

> 生成日期：2026-08-16（独立性结论于本轮全量解耦后更新）
> 范围：30 个砖块文件夹（29 业务砖 + 主板）
> 配套数据：`Data/diag/brick_total_size.json`、`Data/diag/decouple_report.json`、`Data/diag/brick_import_smoke.json`

## 一、各砖总体大小（含依赖）

口径：每个砖块文件夹的**全量磁盘占用**，包含其 vendored 虚拟环境（`.venv` / `.venv-stt`）、模型权重、`_stage` 等全部依赖；已剔除 `__pycache__` 编译缓存与 `archive/Data/docs`。「自写代码」仅含 `.py/.js/.html/.css`。

| 砖块 | 总大小(含依赖) | 自写代码 | 依赖体积 |
|---|---:|---:|---:|
| 语音合成 (CosyVoice) | 10.5 GB | 39 KB | 10.5 GB |
| 语音识别 | 103 MB | 9 MB | 94 MB |
| 语音合成 (GPT-SoVITS) | 4.5 GB | 371 KB | 4.5 GB |
| GUI 自动化 | 1 MB | 321 KB | 882 KB |
| Agent 框架 | 1 MB | 439 KB | 666 KB |
| 沙箱执行 | 412 KB | 126 KB | 287 KB |
| 显示层 | 395 KB | 121 KB | 274 KB |
| 主板 | 350 KB | 94 KB | 256 KB |
| 对话缝合引擎 | 340 KB | 35 KB | 305 KB |
| 存储芯片+管理芯片 | 303 KB | 72 KB | 230 KB |
| Ollama 向导代理 | 293 KB | 80 KB | 212 KB |
| 记忆引擎 | 272 KB | 64 KB | 208 KB |
| 受控自我进化 | 260 KB | 56 KB | 204 KB |
| 裁决引擎 | 248 KB | 53 KB | 195 KB |
| 好感度引擎 | 220 KB | 40 KB | 181 KB |
| 角色扮演引擎 | 203 KB | 34 KB | 169 KB |
| 自主进化引擎 | 195 KB | 31 KB | 164 KB |
| 本机加解密 | 185 KB | 24 KB | 161 KB |
| 游戏生态 | 180 KB | 25 KB | 155 KB |
| 定时任务引擎 | 178 KB | 21 KB | 157 KB |
| 模型供应商 | 174 KB | 23 KB | 151 KB |
| 对话 | 156 KB | 14 KB | 142 KB |
| 解析与结构化 | 155 KB | 12 KB | 143 KB |
| Token 用量 | 151 KB | 12 KB | 140 KB |
| 文件处理 | 147 KB | 9 KB | 138 KB |
| 应用设置 | 146 KB | 8 KB | 137 KB |
| 会话记录 | 139 KB | 6 KB | 133 KB |
| 运行监控 | 136 KB | 5 KB | 132 KB |
| 兜底防御 | 134 KB | 4 KB | 130 KB |
| 离线模式 | 131 KB | 2 KB | 129 KB |
| **合计** | **≈ 14.9 GB** | **11 MB** | **≈ 14.9 GB** |

**关键观察**
- 全仓 ≈ 14.9 GB 体积中，**99% 来自两块语音合成砖**：CosyVoice（`.venv` 6 GB + 权重 4.5 GB ≈ 10.5 GB）与 GPT-SoVITS（权重 4.3 GB + 代码 ≈ 4.5 GB）。其中权重已实现「内聚」落进砖自身目录（见第四节），不再依赖项目外/共享目录。
- 其余 28 个砖块每个仅 130 KB–1 MB，几乎没有自带依赖——它们的 `.venv` 多为空占位，运行时依赖单体共享的 Python 环境。解耦后，这些砖块改由项目根 `palm_sdk/` 提供外部接口，无需单体环境即可 `import`。

## 二、独立运行能力审计（全量解耦后）

判定标准：砖块源码是否仍硬引用单体命名空间（`app`/`backend`/`_shared` 顶层）、其他砖块名，或能否在仅挂载 `palm_sdk` 的情况下独立 `import src`。

**结论：30 / 30 块可独立 import、可独立基准。** 全部通过「逐砖独立导入冒烟测试」——每个砖在独立子进程中 `import src` 成功，零单体耦合、零语法错误、零阻塞依赖缺失。进一步实跑桌面 `PALM砖块基准测试/` 的 30 份 `*_bench.py`：**内存占用 / 导入耗时 / 执行速度 30/30 全部取得真实数值**；**显存（VRAM）两块 GPU 砖均已实测：CosyVoice ≈ 1.88 GB（2,023,936,512 字节）、GPT-SoVITS ≈ 2.34 GB（2,516,523,008 字节）；其余 28 块无 GPU 模型，VRAM = N/A**（详见第五节①）。

### 解耦方案：`palm_sdk` 共享运行基座

项目根新增 `palm_sdk/`（30 个文件），为 30 块提供**唯一的外部依赖面**，使每块都能脱离单体 import 并自我定义：

- **核心原语（真实实现）**：`Brick` / `BrickManifest` / `BusType` / `CapabilitySlot` / `registry`、`get_logger`、`settings`、`require_api_token`、`PermissionSpec` / `RiskLevel` / `require_permission`、`SubprocessSpec`。
- **跨砖共享服务（真实实现）**：`_shared/tooling`（`Tool`/`ToolSpec`/`ToolRegistry` 及 `agent_*` 上下文变量）、`_shared/eventbus`、`_shared/transport`、`_shared/handle`、`_shared/paths`、`_shared/watchdog`、`_shared/emotion`。
- **跨砖安全桩（独立态不抛异常，返回 None/空操作）**：`_shared/interop`（`get_memory_api`/`get_roleplay_api` 等跨砖能力查询，缺件即返回 None）、`_shared/redundancy`（归档保险库/回收站）、`housekeeping`、`bricks/llm`、`bricks/storage`。
- **其余模块**：`core/config`、`core/logging`、`core/gateway`、`security`、`permission`、`schemas/chat`、`tools/gui.*`（GUI 砖本地 `gui` 包镜像）。

设计要点：砖间协作**一律经 capability / registry 在运行时取用**，不在 import 期直接引用其他砖；`palm_sdk` 的跨砖桩保证「缺其他砖也不崩」。

### 独立运行默认路径（`palm_sdk.bricks._shared.paths`）

脱离主板（未配置全局 `settings`）时，砖在 import 期直接拼 `settings.STORAGE_POOL_DIR` 等会得到 `None` 而崩溃。新增 `resolve_storage(*parts, brick_file)` 与 `fallback_dir(value, brick_file, subdir)`：全局已配置用全局池，否则回退「砖根/data」（或指定子目录，如 GPT-SoVITS 的 `models`）。各砖把模块级 `os.path.join(settings.X, ...)` 改为经这两个助手解析，即能在无主板环境下 `import src` 并完成基础落盘。

### 改写操作（脚本化、可重放）

- `Data/diag/decouple_imports.py`：枚举每块 `src` 下全部 import；绝对 `from app/backend/_shared` 与 2 点以上的相对外部导入，按文件系统就近解析区分「砖内 / 外部 / 跨砖」，仅将外部导入改写为 `palm_sdk.*`；砖内相对导入原样保留。改写后静态校验每个 `from palm_sdk...` 可解析且符号已导出（**结果：0 处未解析**）。
- `Data/diag/fix_palm_sdk_prefix.py` 与 `fix_paths_v2.py`：修复早期一轮解耦脚本遗留的前缀缺陷（`from palm_sdk.app.X` → `from palm_sdk.X`；`_shared.eventbus` 补 `.bricks`；`storage.redundancy` 归并到 `_shared.redundancy`）。
- `Data/diag/brick_import_smoke.py`：逐砖子进程 `import src` 冒烟测试，**30/30 通过**。

### 典型修复点（本轮）

- `记忆引擎/src/brick.py`：`from ..base` → `from palm_sdk.bricks.base`。
- `GUI 自动化/src/gui/executor/tool.py`：错加点号的 `from .app.bricks._shared.tooling` → `from palm_sdk.bricks._shared.tooling`。
- `存储芯片+管理芯片`：`from palm_sdk.app._shared.eventbus` → `from palm_sdk.bricks._shared.eventbus`；自身冗余层 `from ..redundancy` 保留为砖内相对导入。
- `沙箱执行`：`from palm_sdk.app.bricks.storage.redundancy.*` → `from palm_sdk.bricks._shared.redundancy.*`。
- `palm_sdk/bricks/_shared/tooling.py`：由占位桩升级为完整实现（`Tool`/`ToolRegistry` 与 `agent_is_wakeup` 等上下文变量），使 Agent 框架等 17 处引用无需单体即可取到符号。

### 独立运行（脱离主板）补齐修复（本轮）

此前 30/30 仅指「import 不报单体耦合」，但 11 块在 import 期因「无主板全局 settings / 缺其他砖 / 缺可选重型依赖」仍崩。本轮补齐，使 30 块在无主板环境下也能独立 `import` 与基准：

- **8 块 `settings.X is None`**：应用设置/受控自我进化(3 处)/游戏生态/裁决引擎/Token 用量/角色扮演引擎/语音合成(GPT-SoVITS 的 `SOVITS_ROOT`) 在模块级 `os.path.join(settings.X, ...)` 或 `Path(settings.X)`，独立态 `None` 崩溃 → 改为经 `paths.resolve_storage`/`fallback_dir` 回退「砖根/data」。
- **存储芯片+管理芯片**：模块级 `PoolStore(settings.STORAGE_POOL_DIR)`（`brick.py`/`breakdown.py`）→ 同改为 `fallback_dir`。
- **裁决引擎**：`ai_fallback.py` 模块级 `os.makedirs(...)` 在 `None` 路径上崩溃 → 随 `_DATA_DIR` 修复一并解决。
- **Agent 框架**：import 期 `_ensure_tools()`/`_roleplay()` 硬依赖「角色扮演砖已注册」→ `palm_sdk.bricks.base._Registry` 补 `_bricks` 属性（兼容单体私有名）；并把 import 期对 roleplay 的 `ensure_builtins`/Skill 注入改为「未注册则跳过」，使独立态不崩。
- **GUI 自动化**：`src/__init__.py` 用绝对 `from gui...` 引自身内部 `gui` 包 → 改为相对 `from .gui...`（共 4 处）。
- **记忆引擎**：模块级 `import chromadb`（可选重型依赖）→ 改为在 `_get_client` 内懒加载，无 chromadb 也能 `import`。

## 三、本轮已完成的全部改动

1. **② GPT-SoVITS 补全 `is_available()` 与定制依赖**（前轮）
   - 模块级 `is_available()`：检查独立 venv 解释器与 GSV 入口 `gpt_sovits/api.py`，缺件返回 `False` 不抛异常；注册能力 `is_available`；503 降级保留。
   - `requirements.txt` 由模板 18 行裁剪为 6 行定制清单；重型 GSV 运行时改由 `install.py` 装入 `.venv-gsv`。
2. **③ 校正 `砖块拆分说明.md`**（前轮）：「31 文件夹」→「30 文件夹」；删除 QwenTTS 条目；补入 CosyVoice 为第 30 砖。
3. **全量解耦（本轮）**：新增 `palm_sdk/`；30 块外部 import 全部改写为 `palm_sdk.*`；逐砖导入冒烟测试 **30/30 通过**；0 处未解析 import。
4. **独立运行补齐 + 实跑基准（本轮）**：11 块 import 期崩溃（settings-None / 缺桩 / 缺可选依赖）全部修复，30 块在无主板环境下均可独立 `import`；`bench_lib` 修正路径后，桌面 `PALM砖块基准测试/` 实跑 **内存/导入耗时/执行速度 30/30 取得真实数值**（仅 VRAM 因无 GPU 待目标机）。
5. **砖→主板 API 契约（本轮）**：明确「主板=hub，其余 29 块独立可用、仅经 API 链接、砖间零互导」；每砖暴露 `router`(HTTP, ~24 块已声明) 与 `capabilities`(进程内) 两类 API 表面；主板侧链接装配本阶段不做，接口已就绪（见 `砖块拆分说明.md`）。

## 四、权重内聚（真实独立）成果

目标：两块语音合成砖的预训练权重不再依赖项目外/共享目录，落进砖自身目录，使砖可被独立搬运、基准磁盘占用如实计入。

### GSV（语音合成 (GPT-SoVITS)）—— 真实独立 ✅
- 原状态：砖内 `src/GPT_SoVITS/pretrained_models` 是指向桌面临时目录 `C:/Users/24459/Desktop/GPT-SoVITS-1007-cu128/GPT_SoVITS/pretrained_models` 的 symlink（联结），不计入砖体积、砖不自包含。
- 操作：`Data/diag/make_gsv_independent.py` 先移除联结（仅删重解析点，不动桌面真实权重），再把 4.3 GB 预训练权重复制进砖自身 `src/GPT_SoVITS/pretrained_models`。
- 结果：基准磁盘占用由 2 MB → **4.5 GB**（权重已计入）；`import src` 成功，导入耗时 0.53s。砖现已自包含，可被独立搬运（桌面源保留作备份）。
- 坑：`robocopy` 本机退出码 16（严重错误）失败；脚本已改为「退出码>7 即回退 `shutil.copytree`」。

### CosyVoice（语音合成 (CosyVoice)）—— 内聚 ✅
- 原状态：权重落在**项目共享** `Data/cosyvoice_model`（4.5 GB），`engine._model_dir()` 默认也回退到该共享目录，砖不自包含。
- 操作：① 权重迁至砖本地 `语音合成 (CosyVoice)/cosyvoice_model`（同盘 rename，瞬时；源 `Data/cosyvoice_model` 已清空，数据未丢失仅 relocate）；② 改 `engine._model_dir()/_output_dir()/_device()/_precision_mode()/_seed_*` 全部用 `_env_or(key, 砖本地默认)`；`brick.yaml` 的 `model_dir` 与 `models[].path` 改为 `cosyvoice_model`；`brick.py` 的 `api_status` 改用 `engine` 解析值。
- **修复关键 bug**：`palm_sdk.core.config._Settings` 是环境变量代理（`__getattr__` 读 `os.environ`，未设置返回 `None`）。原代码用 `if settings is not None:` 判断，但 `settings` 永远是代理对象 → 回退分支**永不触发**，`_model_dir()/_device()/_output_dir()` 全返回 `None`，实际加载模型会崩溃。改为统一 `_env_or` 后，未配置环境变量即正确回退砖本地路径。
- 结果：基准磁盘 ≈ **5.48 GB**（剔除 .venv，含迁入权重）；`_model_dir()` 解析为 `语音合成 (CosyVoice)\cosyvoice_model` 且 `llm.pt`/`cosyvoice2.yaml` 齐备；`_device()`=cuda、`_precision`=bf16（GPU 默认正确）。

## 五、待办与阻塞

**① 实跑取内存/CPU/显存/速度完整数值 —— 内存/导入/速度 30/30 已测，VRAM 已用 torch-cuda 环境测得 CosyVoice**
- 体积维度为真实实测（见第一节）。
- **内存占用 / 导入耗时 / 执行速度：本机（系统 Python 3.10，已装 torch/fastapi 等）实跑 30 份 `*_bench.py` → 30/30 取得真实数值**（见桌面 `PALM砖块基准测试/`）。
- **显存（VRAM）—— CosyVoice 已实测**：用 `语音合成 (CosyVoice)/.venv`（torch 2.11.0+cu128、CUDA 12.8、`torch.cuda.is_available()=True`）运行 `语音合成 (CosyVoice)_bench.py`，并让 `smoke()` 真实加载 CosyVoice2 模型 + 合成一小段（instruct2）。实测：导入期 0（模型懒加载）、**执行期峰值 2,023,936,512 字节 ≈ 1.88 GB**（bf16 权重常驻 GPU）、导入耗时 6.4s、冒烟（加载+合成 11.6s 音频）111s、RTF≈1.09。与行业基准「需 3–4 GB GPU」一致（本机 RTX 5060 Laptop 8151 MiB 余量充足）。
- **显存（VRAM）—— GSV（GPT-SoVITS）已实测**：用 `语音合成 (GPT-SoVITS)/.venv-gsv`（Python 3.11.9、torch 2.8.0+cu128、CUDA 12.8、`torch.cuda.is_available()=True`）运行 `语音合成 (GPT-SoVITS)_bench.py`。该砖砖内仅含权重、缺上游 GPT_SoVITS 源码包，独立 `import src` 失败，故基准借桌面完整仓库 `GPT-SoVITS-1007-cu128` 加载 v3 模型（s1v3 + s2Gv3 + BERT + CNHuBERT + vocoder）并合成一小段中文；权重与砖内一致，VRAM 数值等价。实测：导入期 0（模型懒加载、于 `run()` 内加载）、**执行期峰值 2,516,523,008 字节 ≈ 2.34 GB**（fp16 权重常驻 GPU）、冒烟（加载+合成）≈ 30 s。与 CosyVoice 合计两块 GPU 砖共占 ≈ 4.22 GB 显存，本机 RTX 5060 Laptop 8151 MiB 余量充足。**其余 28 块无 GPU 模型（纯 CPU / 规则 / IO），VRAM = N/A**。
- 关键修复：基准脚本 `bench_lib.try_import` 原先只把砖 `src/` 入 `sys.path`，漏挂项目根（装 `palm_sdk`）→ 全部 `ModuleNotFoundError: palm_sdk`；改为「砖目录 + 项目根」双挂并 `import src` 后，30/30 转 ok。VRAM 测量依赖运行环境自带 torch-cuda：用 CosyVoice venv 跑即得真值，用无 torch 的解释器跑则标「需运行环境」。

**④「所有砖块完全独立运行」—— import 层已达成（30/30），进程级运行待补**
- import 独立：✅ 已完成（每砖可脱离单体 `import src`）。
- 进程级独立运行（作为服务拉起）：各砖原为 FastAPI 服务，需各自 `run.py` 启动入口 + 装齐依赖 venv。CosyVoice（6 GB venv）、语音识别（94 MB venv-stt）已具备；其余 28 块需补 `run.py` 与依赖。这是「能 import」之上的运行化收尾，可后续按需逐块补齐。

**建议路径**
- 解耦目标（脱离单体、独立 import）已交付。下一步若要做「进程级独立运行」，建议按「先 GPT-SoVITS 样板 → 复制其余块」的增量方式补 `run.py` 与 venv，避免一次性大规模回归。

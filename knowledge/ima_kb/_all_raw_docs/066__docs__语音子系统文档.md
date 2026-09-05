# 语音子系统文档

> 📅 **时间线**
> - 2026-08-09：TTS 全流程实测（GSV 实时主线 + 自定义音色链路）
> - 2026-08-10：语音链路基线 / 环境搭建 / 合成测试（同批）
> - 注：语音链路基线测试报告.html 源文件损坏（62 段重复拼接、无数据表格），已弃用，核心数据见本报告的 TTS 全流程实测小节。

## 语音交互子系统实现规格

> 本文档涵盖 STT 砖块、声纹识别、打断处理、提示音频、CosyVoice 2 集成、完整语音链路的实现规格。
> 供实现方按此规格编码，所有设计决策已确认，无需再做架构讨论。

---

## 一、项目背景

### 1.1 项目概述

P.A.L.M 是一个本地优先的 AI Agent 平台，采用"主板"隐喻的模块化砖块（Brick）架构。每个能力域为一块砖块，通过总线分类注册进注册表（BrickRegistry）。

- **后端**：Python + FastAPI
- **前端**：Node.js + Vite（React）
- **本地模型**：Ollama
- **TTS**：GPT-SoVITS（GSV，已实现，22.8 字/s，首字 0.49-0.71s）
- **Python 环境**：主 `.venv`（Python 3.13），GSV 独立 `.venv-gsv`（Python 3.10.10）

### 1.2 砖块架构模式

每个砖块是一个 Python 子包，位于 `backend/app/bricks/<name>/`，包含：

```
backend/app/bricks/<name>/
  __init__.py    # 创建 Brick 实例并调用 registry.register(brick)
  brick.py       # 砖块定义：manifest + router + capabilities
  ...            # 其他业务模块
```

**核心基类**（`backend/app/bricks/base.py`）：

```python
class BusType(str, Enum):
    CPU = "cpu"        # CPU 插槽：编排主控
    SATA = "sata"      # 硬盘：持久化数据
    PCIE = "pcie"      # 高速外设：重计算/媒体
    RAM = "ram"        # 内存槽：状态化、易失
    BOARD = "board"    # 板载焊死：系统关键

@dataclass
class BrickManifest:
    name: str              # 砖块唯一标识
    title: str             # 显示名
    description: str
    is_core: bool = False  # 核心砖缺失即启动失败
    is_enabled: bool = True
    bus_type: BusType = BusType.BOARD

@dataclass
class Brick:
    manifest: BrickManifest
    router: APIRouter | None = None
    mounts: list[MountSpec] = field(default_factory=list)
    capabilities: dict = field(default_factory=dict)  # 供其他砖块调用的能力
    permissions: list = field(default_factory=list)
```

**注册方式**：在 `backend/app/bricks/__init__.py` 中 `from . import <name>` 即完成注册。

**外部插件**：隔离至项目根 `plugins/` 目录，通过 `_load_plugin(name)` 动态加载，插件不存在时优雅跳过。

### 1.3 事件总线

进程内发布-订阅通道（`backend/app/bricks/_shared/eventbus.py`）：

```python
# 订阅
from .._shared.eventbus import subscribe, emit

unsubscribe = subscribe("voice.transcript", handler)
# emit 时同步分发到所有订阅方
emit("voice.transcript", {"text": "你好", "is_final": True})
```

已声明的事件类型常量包括 `VOICE_SESSION_START`、`VOICE_SESSION_END` 等。STT 砖块需新增事件类型。

### 1.4 配置模式

配置集中在 `backend/app/core/config.py` 的 `Settings` 类，从环境变量读取：

```python
class Settings:
    HOST: str = os.getenv("HOST", "127.0.0.1")
    # ... 其他配置
```

TTS 相关配置已有 `SOVITS_*`、`QWEN_TTS_*` 前缀。STT 需新增 `STT_*` 前缀配置。

### 1.5 已有的 TTS 能力

GSV 砖块已实现并可用（位于 `plugins/tts_sovits/`）：
- API 端点：`http://127.0.0.1:9880/`
- 支持流式 OGG 输出
- 参考音频编码预加载 + GPU 预热
- 分句兜底（无标点文本硬切）
- 首字延迟 0.49-0.71s，合成速度 22.8 字/s

---

## 二、Task 1：STT 砖块（Sherpa-onnx 集成）

### 2.1 砖块定位

| 属性 | 值 |
|------|-----|
| name | `stt` |
| title | 语音识别 |
| is_core | False（扩展砖块，缺失不影响核心文本对话） |
| bus_type | `cpu`（低资源消耗） |
| 运行环境 | 主 `.venv`（不需要独立 venv） |
| 运行方式 | 后台线程常驻 |

### 2.2 推理引擎

**Sherpa-onnx**（Apache 2.0 许可证），基于 ONNX Runtime。

**安装依赖**（pip 到主 `.venv`）：
```
sherpa-onnx
sounddevice  # 麦克风采集
numpy
```

### 2.3 模型文件

#### 2.3.1 VAD 模型（语音活动检测）

- **模型**：Silero VAD
- **下载**：`https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx`
- **体积**：约 2MB
- **用途**：检测语音起止，触发 ASR 和打断检测

#### 2.3.2 KWS 模型（关键词唤醒）

- **模型**：`sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20`（中英双语）
- **下载**：`https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20.tar.bz2`
- **int8 量化版**：约 5MB
- **chunk_size**：8（延迟约 160ms）
- **用途**：检测自定义唤醒词，触发 STT 转录

**自定义关键词机制**（不需要重新训练模型）：
1. 编写 `keywords_raw.txt`，每行一个关键词，带 `@` 前缀标注显示名
2. 运行 `sherpa-onnx-cli text2token --tokens-type phone+ppinyin` 转换为音素 token
3. KWS 加载生成的 `keywords.txt` 即可识别

#### 2.3.3 ASR 模型（流式语音识别）

- **模型**：Zipformer 中英双语流式模型
- **推荐**：`sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20`（int8 量化版）
- **下载**：`https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20.tar.bz2`
- **chunk 大小**：60ms（平衡延迟与准确率）
- **双语策略**：中文优先识别，英文辅助

### 2.4 音频处理链路

```
麦克风采集（sounddevice, 16kHz, mono）
  ↓
VAD（Silero VAD）—— 检测语音起止
  ↓ 检测到语音
[声纹验证]（可选，默认关闭，见 Task 2）
  ↓ 验证通过（或声纹关闭）
KWS（关键词唤醒）—— 检测唤醒词
  ↓ 唤醒词命中 或 VAD 检测到持续语音
流式 ASR（Zipformer）—— 实时文本输出
  ↓ 文本完整（VAD 检测语音结束）
发布事件 "voice.transcript" → chat 砖处理
```

**关键设计点**：
- VAD 检测到语音时立即开始流式 ASR，不等语音结束
- VAD 检测到语音结束时，ASR 输出最终文本并发送事件
- KWS 命中只是"触发 STT 转录"的信号之一，不直接判定打断（见 Task 3）
- 采样率固定 16kHz 单声道

### 2.5 事件定义

STT 砖块需在 `eventbus.py` 中新增以下事件类型常量：

```python
VOICE_TRANSCRIPT = "voice.transcript"          # ASR 最终文本
VOICE_PARTIAL = "voice.partial"                 # ASR 中间结果（可选，用于实时显示）
VOICE_INTERRUPTION = "voice.interruption"       # 打断信号（VAD 检测到语音，可能打断）
VOICE_VAD_STATE = "voice.vad_state"             # VAD 状态变化（speaking/silence）
```

### 2.6 REST 端点

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/stt/status` | GET | 获取 STT 状态（运行中/空闲/错误） |
| `/api/stt/start` | POST | 启动 STT 监听 |
| `/api/stt/stop` | POST | 停止 STT 监听 |
| `/api/stt/keywords` | GET/PUT | 获取/更新关键词列表 |
| `/api/stt/voiceprint/register` | POST | 声纹注册（见 Task 2） |
| `/api/stt/voiceprint/verify` | POST | 声纹验证状态查询 |
| `/api/stt/voiceprint/config` | GET/PUT | 声纹配置（开关/置信度档位） |

### 2.7 配置参数

在 `config.py` 的 `Settings` 类中新增：

```python
# --- STT 语音识别（Sherpa-onnx）---
STT_ENABLED: bool = _bool(os.getenv("STT_ENABLED"), False)  # 默认关闭
STT_SAMPLE_RATE: int = int(os.getenv("STT_SAMPLE_RATE"), "16000")
STT_VAD_MODEL: str = os.getenv("STT_VAD_MODEL", "")  # Silero VAD 模型路径
STT_KWS_MODEL: str = os.getenv("STT_KWS_MODEL", "")  # KWS 模型目录
STT_KWS_KEYWORDS: str = os.getenv("STT_KWS_KEYWORDS", "")  # keywords.txt 路径
STT_ASR_MODEL: str = os.getenv("STT_ASR_MODEL", "")  # ASR 模型目录
STT_ASR_CHUNK_MS: int = int(os.getenv("STT_ASR_CHUNK_MS"), "60")  # 流式 chunk 毫秒数

# --- 声纹识别（可选）---
STT_VOICEPRINT_ENABLED: bool = _bool(os.getenv("STT_VOICEPRINT_ENABLED"), False)  # 默认关闭
STT_VOICEPRINT_MODEL: str = os.getenv("STT_VOICEPRINT_MODEL", "")  # CAM++ ONNX 模型路径
STT_VOICEPRINT_CONFIDENCE: str = os.getenv("STT_VOICEPRINT_CONFIDENCE", "default")  # loose/default/strict
STT_VOICEPRINT_DATA_DIR: str = os.getenv("STT_VOICEPRINT_DATA_DIR", "")  # 声纹向量存储目录
```

---

## 三、Task 2：声纹识别

### 3.1 功能定位

可选扩展功能，**默认关闭**。开启后作为 STT 的预处理环节——验证通过才将语音送入 ASR。

### 3.2 模型

**CAM++**（3D-Speaker 项目，Apache 2.0 许可证）：

| 属性 | 值 |
|------|-----|
| 模型 | `cam++.onnx`（sherpa-onnx 提供 ONNX 格式） |
| 参数量 | 7.2M |
| 中文 EER | 6.78%（CN-Celeb 测试集） |
| ONNX 大小 | 约 27MB |
| 下载 | `https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-segmentation-models/sherpa-onnx-speaker-segmentation-model-cam++.tar.bz2` |

可选高精度模型：`ERes2NetV2`（17.8M, EER 6.14%, 68MB）。

### 3.3 注册流程

1. 用户在设置面板开启声纹功能
2. 念 3-5 句话（含正常状态 + 疲惫状态样本）
3. 系统提取说话人嵌入向量（speaker embedding）
4. 存储为参考向量集合（JSON 或 .npy 文件，存储在 `STT_VOICEPRINT_DATA_DIR`）

### 3.4 验证流程

1. VAD 检测到语音 → 提取当前音频的说话人嵌入向量
2. 与参考向量集合计算余弦相似度（取最大值）
3. 相似度 >= 阈值 → 验证通过，送入 ASR
4. 相似度 < 阈值 → 验证失败，执行失败响应

### 3.5 置信度档位（用户可调）

| 档位 | 余弦相似度阈值 | 面向场景 | 误拒风险 | 误受风险 |
|------|--------------|---------|---------|---------|
| 宽松（loose） | 0.35 | 嗓子经常哑/环境嘈杂 | 极低 | 较高 |
| 默认（default） | 0.45 | 日常使用（**默认档**） | 低 | 低 |
| 严格（strict） | 0.55 | 不想让任何人冒充 | 中 | 极低 |

用户在设置面板选择档位，系统映射到对应阈值。默认档为"默认"。

### 3.6 失败响应

**每次**验证失败时：
1. 主Agent 用角色语气回应一句拒绝语（台词由角色卡片配置读取，**不硬编码**"你不是我主人"）
2. 进入 30 秒静默期：STT 继续监听但不处理输入，KWS 暂停触发
3. 30 秒后自动恢复正常验证流程

**无降级模式**：没有锁定状态、没有 PIN/密码解锁、没有"连续失败N次进入降级模式"。每次失败都是独立的"拒绝语 + 30s 静默"循环。30 秒静默本身即速率限制。

### 3.7 自适应更新

相似度 > 0.6 时，对参考向量做滑动平均更新，让参考向量跟随用户声音缓慢漂移（感冒/疲劳等）。

### 3.8 多状态注册

注册时采集两种状态样本：
- 正常状态：3-4 句话
- 疲惫状态：1-2 句话

覆盖声音状态变化，降低误拒率。

---

## 四、Task 3：打断处理

### 4.1 设计背景

用户在 AI 语音播放（TTS）过程中可能说话，需要区分"真打断"（用户想插话）和"假警报"（背景噪声/用户自言自语如"没事"）。

### 4.2 三级分流机制

**核心原则**：KWS 命中**不直接判定真打断**，只触发 STT 转录。所有打断判断统一走语义分析。

| 层级 | 检测方式 | 作用 | 延迟 |
|------|---------|------|------|
| 第一级：VAD + KWS | VAD 检测语音 + KWS 检测唤醒词 | 触发 STT 转录（**不判定真假**） | <10ms |
| 第二级：规则关键词 | 正则/关键词匹配 | 判定真假打断 | <1ms |
| 第三级：FastText 模型 | 短文本二分类 | 判定模糊文本 | <5ms |

### 4.3 文本长度分流规则

```
无文本（空/纯噪声）→ 默认假（VAD 误触发）
短文本（1-14 字）→ 规则未命中则走 FastText 模型
长文本（15 字+）→ 默认真（15 字以上几乎不可能是误触发）
```

### 4.4 规则关键词

**假警报关键词**（判定为假）：
- "没事"、"算了"、"没什么"、"不用了"、"继续"、"你说"

**真打断关键词**（判定为真）：
- "停"、"等等"、"停一下"、"等一下"、"闭嘴"

### 4.5 FastText 模型

| 属性 | 值 |
|------|-----|
| 任务 | 短文本二分类（真打断 vs 假警报） |
| 输入 | STT 转录文本（<=14 字） |
| 输出 | 二分类结果 + 置信度 |
| 推理速度 | <5ms（CPU） |
| 模型体积 | <2MB |
| 特征 | character n-gram（中文短文本无需分词） |
| 训练数据 | 数百条标注样本即可 |

**置信度兜底**：FastText 输出置信度 < 0.6 时走"默认真"（安全兜底，宁可误打断不可漏打断）。

**模型文件**：需训练或寻找预训练模型。可用 `fasttext` 库训练，数据格式为：
```
__label__interrupt 停一下别说了
__label__false_alarm 没事你继续说
```

**安装依赖**：`fasttext`（pip 到主 `.venv`）

### 4.6 静音机制

VAD 检测到语音时**立即静音 TTS 输出**，不等语义识别结果。语义识别完成后：
- 真打断 → 停止 TTS，进入新对话轮
- 假警报 → 恢复 TTS 播放

100ms 静音窗口用户基本无感。

### 4.7 设计原则

陪伴型主Agent 的核心体验是 responsiveness。误打断（AI 白停一下又恢复）的代价远低于漏打断（用户说话 AI 不理）。因此所有兜底逻辑偏向"默认真"。

---

## 五、Task 4：提示音频系统

### 5.1 功能

STT 完成后异步播放 1-5s 提示音频（如"让我想想..."），填补 LLM 等待空窗期。用户感知延迟从"说完话 → AI 回复"变为"说完话 → 提示音 → AI 回复"，心理感知大幅改善。

### 5.2 设计

| 属性 | 值 |
|------|-----|
| 生成方式 | AI 根据角色卡片直接生成，预合成为音频文件存储 |
| 语料库规模 | 约 25 条万金油内容 |
| 动态选择 | 根据预估 LLM 处理时间选择不同长度提示音（1s/3s/5s） |
| 存储方案 | 角色卡片 ID → 提示音频列表映射 |
| 播放方式 | 异步播放，不阻塞 LLM 调用和 TTS 合成 |

### 5.3 提示音长度选择逻辑

```
预估 LLM 处理时间 < 1s → 不播放提示音（直接等 TTS）
预估 LLM 处理时间 1-3s → 播放 1s 提示音
预估 LLM 处理时间 3-5s → 播放 3s 提示音
预估 LLM 处理时间 > 5s → 播放 5s 提示音
```

LLM 处理时间预估：基于历史对话的响应时间滑动平均。

### 5.4 语料库示例

万金油内容，不同角色不同语气（由角色卡片定义）：
- "让我想想..."
- "嗯，这个问题..."
- "稍等一下..."
- "我想想看..."
- "好的，我看看..."
- "嗯哼，让我考虑一下..."
- ...（约 25 条）

---

## 六、Task 5：CosyVoice 2 集成

### 6.1 定位

CosyVoice 2 **仅用于**"用户自定义音色"的一次性生成流程，不参与实时对话合成。实时合成仍由 GSV 承担。

### 6.2 使用场景

```
用户描述音色要求（如"温柔大姐姐"）
  ↓
CosyVoice 2 零样本克隆合成样本音频
  ↓
用户试听 → 不满意则重新生成
  ↓
用户确认 → 保存为参考音频文件
  ↓
GSV 加载该参考音频进行实时对话合成
```

### 6.3 选型理由

1. CosyVoice 2 原生支持零样本音色克隆，不需要 Qwen TTS 的 VoiceDesign 流程
2. 支持情感控制，可生成带情感的参考音频
3. 推理速度优于 Qwen TTS（自回归模型更小）

### 6.4 与 Qwen TTS 的关系

Qwen TTS 砖块保留但降级为备用引擎，CosyVoice 2 作为音色克隆首选。Qwen TTS 不做压缩改造。

### 6.5 砖块定位

| 属性 | 值 |
|------|-----|
| name | `cosyvoice` |
| is_core | False |
| bus_type | `pcie`（重计算） |
| 运行环境 | 独立 venv（`.venv-cosyvoice`），与 GSV 类似的隔离模式 |
| 运行方式 | 独立子进程，通过 HTTP 代理通信 |

### 6.6 安装依赖

CosyVoice 2 需要 PyTorch + CUDA，与 GSV 存在版本冲突，必须独立 venv。具体依赖参考 CosyVoice 2 官方仓库。

---

## 七、Task 6：完整语音交互链路

### 7.1 链路总览

```
用户说话
  ↓
[VAD] 检测语音起止（Silero VAD）
  ↓
[声纹验证]（可选，默认关闭）→ CAM++ 嵌入提取 → 余弦相似度比对
  ↓ 通过（或声纹关闭）
[KWS] 关键词唤醒检测（中英双语 ONNX 模型）
  ↓ 唤醒词命中 或 VAD 检测到持续语音
[流式 ASR] Zipformer 中英双语模型 → 实时文本输出
  ↓ 文本完整（VAD 检测语音结束）

  ┌─ 如果 TTS 正在播放 ─────────────────────────────────┐
  │ [打断判断]                                          │
  │  第一级：VAD+KWS 触发 STT 转录（不判定真假）        │
  │  第二级：规则关键词匹配                              │
  │  第三级：FastText 模型二分类                         │
  │  → 真打断：停止 TTS，进入新对话轮                    │
  │  → 假警报：恢复 TTS 播放                             │
  └─────────────────────────────────────────────────────┘
  ↓
[提示音频] 异步播放 1-5s 万金油提示音（预合成存储）
  ↓
[chat 砖] 文本送入主Agent 对话链路
  ↓
[LLM] 主力模型生成回复（非流式，网络中位数 300-500ms）
  ↓
[GSV] TTS 合成（预加载+GPU 预热，首字约 400ms）
  ↓
用户听到回复
```

### 7.2 延迟预算

目标：用户说完话到 AI 语音回复第一个字 <= 1.5s（理想 <= 1.0s）

| 环节 | 预估延迟 | 说明 |
|------|---------|------|
| STT 尾字延迟 | 约 200ms | VAD 检测语音结束 + 最后一个 chunk 解码 |
| 语义识别（打断判断） | 约 10ms | FastText 模型推理（仅打断场景） |
| LLM 首字延迟 | 约 300-500ms | 网络中位数，非流式 API |
| TTS 首字延迟 | 约 400ms | GSV 优化后（预加载+GPU 预热） |
| 音频传输 | 约 100ms | HTTP 传输 + 前端播放缓冲 |
| **总计** | **1.0-1.2s** | 在 1.5s 目标内 |

### 7.3 砖块间通信

STT 砖块通过事件总线发布事件，chat 砖订阅：

```
STT 砖 → emit("voice.transcript", {"text": "...", "is_final": True})
         → chat 砖订阅 → 走正常对话链路

STT 砖 → emit("voice.interruption", {"text": "...", "is_interrupt": True})
         → TTS 砖订阅 → 停止/恢复播放

STT 砖 → emit("voice.vad_state", {"state": "speaking"})
         → TTS 砖订阅 → 立即静音（不等语义结果）
```

---

## 八、硬约束（必须遵守）

### 8.1 数据获取

- 所有数据获取必须走后端，组件不能直接调用 API
- 不支持模拟数据，数据不可用时显示 N/O
- 后端数据源采集间隔应一致，首选 0.5s

### 8.2 砖块隔离

- STT 砖运行在主 `.venv`（轻量，sherpa-onnx 纯 CPU 推理）
- CosyVoice 2 需独立 venv（PyTorch+CUDA，与 GSV 版本冲突）
- 不合并 venv（会导致版本冲突）

### 8.3 异常处理

- 禁止 `except...pass` 静默吞没异常
- 清理/关闭类用 debug 级日志
- 业务逻辑/安全相关用 warning 级日志
- 砖块加载失败不阻断主程序启动

### 8.4 离线优先

- 模型文件需本地存储，不依赖运行时下载
- 配置项留空时优雅降级（不阻断启动）
- sherpa-onnx 纯 CPU 推理，GPU 加速为可选

### 8.5 开源合规

- Sherpa-onnx：Apache 2.0
- CAM++（3D-Speaker）：Apache 2.0
- FastText：MIT
- CosyVoice 2：Apache 2.0
- 所有第三方模型/库需在砖块 README 中标注来源和许可证

---

## 九、依赖清单

### 9.1 主 .venv（STT 砖块）

```
sherpa-onnx>=1.10
sounddevice>=0.4
numpy>=2.0
fasttext-wheel  # 或 fasttext
```

> 修订说明（2026-08-09）：原 `numpy<2.0` 仅对 Python ≤3.12 有预编译 wheel；主
> `.venv` 为 3.13 时无法安装（sdist 源码编译在无编译器环境下失败）。sherpa-onnx≥1.10
> 已兼容 numpy 2，故放宽为 `numpy>=2.0`。

### 9.2 CosyVoice 2 独立 venv

参考 CosyVoice 2 官方 requirements.txt，需要 PyTorch + CUDA。

### 9.3 模型文件清单

| 模型 | 用途 | 体积 | 存放位置 |
|------|------|------|---------|
| silero_vad.onnx | VAD 语音活动检测 | 约 2MB | Data/stt_models/vad/ |
| zipformer-zh-en-3M KWS | 关键词唤醒 | 约 5MB（int8） | Data/stt_models/kws/ |
| zipformer-bilingual ASR | 流式语音识别 | 约 80MB（int8） | Data/stt_models/asr/ |
| cam++.onnx | 声纹识别 | 约 27MB | Data/stt_models/voiceprint/ |
| fasttext_model.bin | 打断语义分类 | 约 2MB | Data/stt_models/interrupt/ |

---

## 十、文件结构规划

```
backend/app/bricks/stt/
  __init__.py              # 砖块注册
  brick.py                 # 砖块定义 + REST 端点
  vad.py                   # VAD 封装（Silero VAD via sherpa-onnx）
  kws.py                   # KWS 封装（关键词唤醒）
  asr.py                   # ASR 封装（流式 Zipformer）
  voiceprint.py            # 声纹识别（CAM++ 嵌入提取 + 余弦相似度）
  interrupt.py             # 打断处理（规则 + FastText 模型）
  prompt_audio.py          # 提示音频管理（预合成存储 + 动态选择）
  audio_stream.py          # 麦克风采集线程（sounddevice）
  keywords_raw.txt         # 关键词原始定义（用户可编辑）
  keywords.txt             # 转换后的音素 token（自动生成）

plugins/cosyvoice/         # CosyVoice 2 独立砖块（与 GSV 同级）
  __init__.py
  brick.py
  brick.yaml               # 砖块清单（Python 版本/依赖/模型）
  README.md
  cosyvoice/               # CosyVoice 2 源码
  install.py               # venv 创建 + 依赖安装

Data/stt_models/           # 模型文件存储
  vad/silero_vad.onnx
  kws/                     # KWS 模型目录
  asr/                     # ASR 模型目录
  voiceprint/cam++.onnx
  interrupt/fasttext_model.bin

Data/voiceprint/           # 声纹向量存储
  <user_id>/
    embeddings.npy         # 参考向量集合
    meta.json              # 注册元信息（时间/状态/样本数）

Data/prompt_audio/         # 提示音频存储
  <character_id>/
    1s/
      00.wav, 01.wav, ...
    3s/
      00.wav, 01.wav, ...
    5s/
      00.wav, 01.wav, ...
```

---

## 十一、实现优先级

建议按以下顺序实现：

1. **STT 砖块基础**（VAD + ASR + 麦克风采集）→ 能听到用户说话并输出文本
2. **KWS 集成**（关键词唤醒）→ 唤醒词触发识别
3. **打断处理**（规则 + FastText）→ TTS 播放时能正确处理打断
4. **提示音频系统**→ 填补 LLM 等待空窗期
5. **声纹识别**（CAM++ + 验证流程）→ 可选功能，最后实现
6. **CosyVoice 2 集成**→ 音色自定义流程，独立于实时链路
7. **完整链路调优**→ 端到端延迟优化到 1.5s 以内

---

## 十二、与现有代码的对接点

| 对接点 | 位置 | 对接方式 |
|--------|------|---------|
| chat 砖 | `backend/app/bricks/chat/brick.py` | STT 通过事件总线发布 `voice.transcript`，chat 砖订阅后走 `/api/chat` 同链路 |
| TTS 砖 | `plugins/tts_sovits/` | STT 通过事件总线发布 `voice.interruption`，TTS 砖订阅后停止/恢复播放 |
| 事件总线 | `backend/app/bricks/_shared/eventbus.py` | 新增事件类型常量 |
| 配置 | `backend/app/core/config.py` | 新增 `STT_*` 配置项 |
| 砖块注册 | `backend/app/bricks/__init__.py` | `from . import stt` 注册内置砖块 |
| 角色卡片 | `backend/app/bricks/roleplay/` | 声纹拒绝语和提示音语料从角色卡片配置读取 |

---

## 附录 A：Sherpa-onnx 关键 API 参考

```python
# VAD
import sherpa_onnx
vad_config = sherpa_onnx.VadModelConfig()
vad_config.silero_vad.model = "path/to/silero_vad.onnx"
vad_config.silero_vad.threshold = 0.5
vad_config.sample_rate = 16000
vad = sherpa_onnx.VoiceActivityDetector(vad_config, buffer_size_in_seconds=30)

# KWS
kws_config = sherpa_onnx.KeywordSpotterConfig(
    model="path/to/kws/model.onnx",
    tokens="path/to/tokens.txt",
    keywords_file="path/to/keywords.txt",
    num_threads=1,
    provider="cpu",
)
kws = sherpa_onnx.KeywordSpotter(kws_config)
stream = kws.create_stream()

# ASR (streaming)
asr_config = sherpa_onnx.OnlineRecognizerConfig(
    model_config=sherpa_onnx.OnlineModelConfig(
        zipformer=sherpa_onnx.OnlineZipformer2ModelConfig(
            model="path/to/encoder.onnx",
            decoder="path/to/decoder.onnx",
            joiner="path/to/joiner.onnx",
        ),
        tokens="path/to/tokens.txt",
        num_threads=1,
        provider="cpu",
    ),
    decoding_method="greedy_search",
)
recognizer = sherpa_onnx.OnlineRecognizer(asr_config)
stream = recognizer.create_stream()

# Voiceprint (speaker embedding)
extractor_config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
    model="path/to/cam++.onnx",
    num_threads=1,
    provider="cpu",
)
extractor = sherpa_onnx.SpeakerEmbeddingExtractor(extractor_config)
embedding = extractor.compute(stream, sample_rate=16000)
# cosine similarity
similarity = extractor.compute_similarity(embedding1, embedding2)
```

## 附录 B：FastText 模型训练参考

```
# 训练数据格式（interrupt_train.txt）
__label__interrupt 停一下
__label__interrupt 别说了
__label__interrupt 等等等
__label__false_alarm 没事
__label__false_alarm 算了算了
__label__false_alarm 你继续说

# 训练命令
import fasttext
model = fasttext.train_supervised(
    input="interrupt_train.txt",
    epoch=25,
    lr=1.0,
    wordNgrams=2,
    dim=100,
)
model.save_model("fasttext_model.bin")
```

---


## TTS 全流程实测（GSV 实时主线）

> 测试日期：2026-08-09
> 环境：RTX 5060 Laptop 8GB VRAM | CUDA 12.8 | Python 3.13 主环境 | GSV 独立运行环境 | Qwen TTS 历史测试环境
> 方法：保留 Qwen TTS 历史延迟实测，同时按后续架构日志修正当前结论：GSV 已完成环境搭建和合成实测；自定义音色生成主线已从 Qwen TTS 改为 CosyVoice 2。

---

## 0. 结论先行

1. **GSV 已经是当前实时 TTS 主线，不是环境未就绪。** 后续实测显示，GSV 中文首字延迟为 **0.49–0.71s**，长文本 80 字总耗时 **3.51s**，速度 **22.8 字/s**，基本满足实时对话的首字目标。
2. **Qwen TTS 历史测试只保留为反例基准。** 旧 VoiceDesign / NF4 4bit 测试中，单句合成需 **30–110s**，分句伪流式只能降低“相对首字等待”，不能解决绝对速度瓶颈。
3. **自定义音色链路已改为 CosyVoice 2。** CosyVoice 2 用于“用户描述音色要求 → 生成样本 → 用户确认 → 保存参考音频”的一次性流程；实时合成仍由 GSV 承担。
4. **当前架构不是 Qwen TTS 替换 GSV，而是“CosyVoice 2 生成音色参考 + GSV 实时合成”。** Qwen TTS 砖块保留为备用，不再作为主推荐方案。

---

## 1. 测试概况

| 引擎/模块 | 当前定位 | 状态 | 关键数据 |
|----------|---------|------|---------|
| GSV (GPT-SoVITS) | 实时对话 TTS 主线 | 已完成环境搭建 + 实测 | 中文首字 0.49–0.71s，长文本 22.8 字/s |
| CosyVoice 2 | 自定义音色生成主线 | 架构决策已替代 Qwen TTS | 用于生成 GSV 所需参考音频，不参与实时对话合成 |
| Qwen TTS | 历史测试 / 备用引擎 | 已测试旧 VoiceDesign 路线 | 30–110s/句，不适合实时对话 |
| GSV 优化项 | 参考音频预加载 + GPU 预热 + 无标点硬切 | 已实现并随 GSV 实测验证 | 首字延迟与文本长度解耦 |

---

## 2. GSV 实时合成实测

GSV 环境已完成搭建并成功执行 4 组合成延迟实测。测试环境为 RTX 5060 Laptop 8GB VRAM / CUDA 12.8 / torch 2.8.0+cu128 / 模型 v2 / FP16 / 流式 normal。

| 测试项 | 字数 | 首字延迟 | 总时间 | 音频大小 | 估算时长 | 速度 |
|--------|------|---------|--------|---------|---------|------|
| 短文本 | 5 | 0.710s | 0.710s | 14.0 KB | 0.45s | 7.0 字/s |
| 中等文本 | 30 | 0.609s | 1.559s | 28.3 KB | 0.91s | 19.2 字/s |
| 长文本 | 80 | 0.490s | 3.510s | 78.5 KB | 2.51s | 22.8 字/s |
| 中英混合 | 40 | 3.212s | 4.119s | 24.3 KB | 0.78s | 9.7 字/s |

关键结论：

- 中文首字延迟 0.49–0.71 秒，用户 1 秒内能听到首字，接近 0.8 秒目标。
- 长文本速度 22.8 字/s，80 字文本 3.51 秒完成。
- 参考音频编码预计算 + GPU 预热消除了冷启动延迟。
- 标点切分有效，长文本被分成多句流式输出，首字延迟与文本长度解耦。
- 中英混合首次延迟较高，主要是英文资源首次加载开销，后续请求应下降。

---

## 3. 与历史测试对比

| 指标 | 历史 GSV 测试 | 当前 GSV 测试 | 变化 |
|------|--------------|--------------|------|
| 平均合成速度 | 11.5 字/s | 22.8 字/s | 提升约 98% |
| 平均总时间 | 3.9s/段 | 3.5s（80字） | 下降约 10% |
| 首字延迟 | 未测量 | 0.49–0.71s | 新增关键指标 |
| 流式分块 | 未启用 | normal 模式 | 已启用 |
| 预加载 | 无 | 参考音频编码 + GPU 预热 | 已启用 |

与 Qwen TTS 历史测试相比，GSV 的速度优势非常明确：

| 引擎 | 代表速度 | 首字体验 | 当前定位 |
|------|---------|---------|---------|
| GSV | 22.8 字/s | 0.49–0.71s | 实时对话主线 |
| Qwen TTS 历史 VoiceDesign | 约 0.17 字/s | 30–110s/句 | 历史反例 / 备用 |

GSV 不是“待验证方案”，而是当前实时 TTS 的主线方案。Qwen TTS 的测试价值在于证明：仅靠分句伪流式无法把一个慢模型变成实时模型。

---

## 4. Qwen TTS 历史测试结果

以下数据保留为历史对照，不代表当前推荐架构。

### 4.1 分句伪流式延迟测试

测试 `/api/stream` 端点（分句伪流式），测量首字节延迟（TTFB）、首音频块延迟（TTFA）和总耗时。

| 测试项 | 字符数 | TTFB (ms) | TTFA (ms) | 总耗时 (ms) | TTFA/总耗时 | 伪流式 |
|--------|-------|----------|----------|-----------|------------|--------|
| short | 5 | 70 | 48,826 | 48,831 | 100.0% | 否（单句） |
| medium | 17 | 48 | 42,160 | 84,848 | 49.7% | 是 |
| long | 54 | 61 | 110,203 | 311,359 | 35.4% | 是 |
| no_punct | 51 | 49 | 95,224 | 213,234 | 44.7% | 是 |

分句伪流式本身有效：medium / long / no_punct 的首字等待相对总耗时降低 50–65%。但绝对延迟仍在 30–110 秒量级，因此无法服务实时对话。

### 4.2 流式 vs 非流式

| 指标 | 值 |
|------|-----|
| short 非流式总耗时 | 42.267s |
| short 流式首字/总耗时 | 29.710s / 29.714s |
| medium 非流式总耗时 | 74.586s |
| medium 流式首字/总耗时 | 44.223s / 68.877s |

分句没有额外开销，流式总耗时反而更短。原因是短句推理更容易，减少了整段合成时的长序列开销。

### 4.3 GPU 预热效应

| 指标 | 值 |
|------|-----|
| 首次测试（GPU 冷启动后第一个请求） | 48.8s |
| 对比测试（GPU 已预热） | 29.7s |
| 预热后速度提升 | −39.1% |

GPU 首次推理存在约 19 秒的额外初始化开销。即便预热后，Qwen TTS 单句 5 字仍需约 29.7 秒，速度约 0.17 字/s，仍不适合实时对话。

---

## 5. 优化效果汇总

| 优化项 | 引擎 | 状态 | 效果 | 达标 |
|--------|------|------|------|------|
| GSV 实时合成 | GSV | 已实现 + 实测 | 中文首字 0.49–0.71s，长文本 22.8 字/s | 达标/接近达标 |
| 参考音频编码预加载缓存 | GSV | 已实现 + 实测 | 消除重复参考音频编码开销 | 达标 |
| GPU 预热 | GSV | 已实现 + 实测 | 消除冷启动延迟 | 达标 |
| 标点切分/长文本流式 | GSV | 已实现 + 实测 | 长文本首字与文本长度解耦 | 达标 |
| 自定义音色生成 | CosyVoice 2 | 架构决策已替代 Qwen TTS | 一次性生成参考音频，交给 GSV 实时合成 | 推荐路线 |
| 分句伪流式 | Qwen TTS 历史路线 | 已实测 | 多句文本首字相对降低 50–65% | 只解决相对等待 |
| 绝对首字延迟 < 0.8s | Qwen TTS 历史路线 | 未达标 | 实测 30–110s/句 | 不适合实时 |

---

## 6. 当前语音合成架构

当前链路应按下面理解：

```
用户自定义音色
  ↓
CosyVoice 2 生成候选参考音频
  ↓
用户确认音色
  ↓
保存为 GSV 参考音频
  ↓
GSV 预加载参考音频编码 + GPU 预热
  ↓
实时对话时由 GSV 流式合成
```

这条链路的关键点是：**CosyVoice 2 负责“造音色”，GSV 负责“实时说话”**。这比“Qwen TTS 实时合成”更合理，因为实时路径必须优先满足首字延迟，而音色生成可以是一次性、离线或半离线流程。

---

## 7. 根因分析与建议

### 7.1 为什么 GSV 是实时主线

| 因素 | GSV 表现 | 架构意义 |
|------|---------|---------|
| 首字延迟 | 0.49–0.71s | 接近实时对话目标 |
| 长文本速度 | 22.8 字/s | 足够支撑日常回复 |
| 参考音频复用 | 可预加载 | 适合固定角色音色 |
| GPU 预热 | 已实现 | 避免首次请求卡顿 |
| 句子切分 | 已验证 | 长文本不拖慢首字 |

### 7.2 为什么 Qwen TTS 不再作为推荐实时路线

| 因素 | 影响 |
|------|------|
| 1.7B 自回归架构 | 逐 token 生成音频 codec，历史实测约 0.17 字/s |
| NF4 4bit 量化 | 减少显存但增加反量化计算 |
| 旧 VoiceDesign 模式 | 每次合成都需生成音色嵌入，额外开销大 |
| 分句伪流式 | 只能降低相对等待，不能把 30–110s/句变成实时 |

### 7.3 为什么 CosyVoice 2 替代 Qwen TTS 的位置

CosyVoice 2 的位置不是实时合成，而是自定义音色生成。它原生支持零样本音色克隆和情感控制，可以根据用户描述生成候选样本。用户确认后，样本保存为 GSV 参考音频，后续实时对话由 GSV 合成。

这相当于把 TTS 拆成两个阶段：

| 阶段 | 目标 | 推荐引擎 |
|------|------|---------|
| 音色生成 | 生成/挑选用户想要的声音 | CosyVoice 2 |
| 实时合成 | 在对话中低延迟说话 | GSV |

### 7.4 建议

1. 固化 GSV 为实时对话 TTS 默认引擎。
2. 固化 CosyVoice 2 为自定义音色生成主线。
3. Qwen TTS 保留为备用或实验路线，不再写成下一步优化重点。
4. 后续测试重点应转向 GSV 的长会话稳定性、中英混合二次请求延迟、参考音频切换成本。

---

## 8. 复现方式

```bash
cd P.A.L.M/backend
# GSV 实时合成测试：使用 plugins/tts_sovits 的独立运行环境
# Qwen TTS 历史测试：使用 .venv-qwen-tts 和 /api/stream、/api/synthesize
```

本报告保留 Qwen TTS 历史测试数据用于解释路线取舍，但当前架构结论以 GSV 实测和 CosyVoice 2 替代决策为准。

---


## TTS 实际合成测试

P.A.L.M 项目 · GSV (GPT-SoVITS) + Qwen TTS · 2026-08-09

## 测试环境
RTX 5060

GPU (8GB VRAM)

24

CPU 核心

12.8

CUDA 版本

| 项目     | GSV (GPT-SoVITS)                   | Qwen TTS                        |
| -------- | ---------------------------------- | ------------------------------- |
| Python   | 3.11.12（旧 runtime）              | 3.10.10（.venv-qwen-tts）       |
| PyTorch  | 2.8.0+cu128                        | 2.8.0+cu128                     |
| 模型     | v2 预训练（s2G2333k + s1bert25hz） | Qwen3-TTS-12Hz-1.7B-CustomVoice |
| 量化     | 半精度（FP16）                     | NF4 4bit（bitsandbytes）        |
| API 端口 | 9880                               | 19300                           |
| 音频格式 | OGG（流式压缩）                    | WAV（无损 PCM）                 |
| 参考音频 | 需要（Windows SAPI 生成）          | 不需要（零样本）                |

## 测试总览

### GSV (GPT-SoVITS)
4/4

成功率

11.5

字/秒（后续平均）

3.9s

后续平均耗时

28.9s

首次（含预热）

### Qwen TTS
4/4

成功率

2.2

字/秒（后续平均）

18.6s

后续平均耗时

48.2s

首次（含加载）

## GSV (GPT-SoVITS) 详细结果

| 测试 ID       | 文本                                         | 字符数 | 结果   | 耗时 (ms)     | 音频大小 (KB) | 速度 (字/秒) |
| ------------- | -------------------------------------------- | ------ | ------ | ------------- | ------------- | ------------ |
| short_5char   | 你好世界。                                   | 5      | ✅ 成功 | 28,884 含预热 | 10.1          | 0.2          |
| medium_20char | 今天天气真不错，我们一起出去玩吧。           | 17     | ✅ 成功 | 1,346         | 29.1          | 12.6         |
| long_50char   | 语音合成技术是人工智能领域的重要分支…        | 54     | ✅ 成功 | 3,033         | 88.6          | 17.8         |
| mixed_lang    | Hello你好，这是一段mixed中英文test测试文本。 | 29     | ✅ 成功 | 7,267         | 32.9          | 4.0          |

关键参数： 模型版本 v2 · 半精度 FP16 · 流式模式 normal · 文本切分符号" ，。？！；：" · 参考音频由 Windows SAPI 生成（"大家好，欢迎使用语音合成系统。"） · 首次请求含 GPU 预热（CUDA 上下文初始化 + 模型权重加载到显存）

## Qwen TTS 详细结果

| 测试 ID       | 文本                                         | 字符数 | 结果   | 耗时 (ms)     | 音频大小 (KB) | 速度 (字/秒) |
| ------------- | -------------------------------------------- | ------ | ------ | ------------- | ------------- | ------------ |
| short_5char   | 你好世界。                                   | 5      | ✅ 成功 | 48,205 含加载 | 41.3          | 0.1          |
| medium_20char | 今天天气真不错，我们一起出去玩吧。           | 17     | ✅ 成功 | 7,380         | 123.8         | 2.3          |
| long_50char   | 语音合成技术是人工智能领域的重要分支…        | 54     | ✅ 成功 | 38,354        | 648.8         | 1.4          |
| mixed_lang    | Hello你好，这是一段mixed中英文test测试文本。 | 29     | ✅ 成功 | 9,941         | 165.0         | 2.9          |

关键参数： 模型 Qwen3-TTS-12Hz-1.7B-CustomVoice · NF4 4bit 量化 · Voice=Cherry（回退首个说话人） · 首次请求触发模型懒加载（从磁盘加载权重到 GPU，含 4 个模型文件 fetch） · 警告：SoX 未安装（非关键）、flash-attn 未安装（使用手动 PyTorch attention）

## 引擎对比分析

| 对比维度         | GSV (GPT-SoVITS)     | Qwen TTS                        | 胜出              |
| ---------------- | -------------------- | ------------------------------- | ----------------- |
| 后续请求平均耗时 | 3,882 ms             | 18,559 ms                       | GSV（4.8x 更快）  |
| 后续请求平均速度 | 11.5 字/秒           | 2.2 字/秒                       | GSV（5.2x 更快）  |
| 首次请求耗时     | 28,884 ms            | 48,205 ms                       | GSV               |
| 短文本响应       | 1,346 ms             | 7,380 ms                        | GSV               |
| 长文本响应       | 3,033 ms             | 38,354 ms                       | GSV（12.7x 更快） |
| 音频文件大小     | 10~89 KB（OGG）      | 41~649 KB（WAV）                | GSV（压缩更小）   |
| 参考音频需求     | 需要参考音频         | 零样本，无需参考                | Qwen TTS          |
| 音色克隆         | 支持（参考音频克隆） | 支持（VoiceDesign/CustomVoice） | 各有优势          |
| 混合语言处理     | 4.0 字/秒            | 2.9 字/秒                       | GSV               |
| 显存占用         | ~2-3 GB（FP16）      | ~2 GB（4bit 量化）              | 接近              |

### 速度对比可视化（后续请求平均，字/秒）
GSV: 11.5 字/秒 ████████████████████

Qwen: 2.2 字/秒 ████

### 长文本合成耗时对比（ms）
GSV: 3,033ms ██

Qwen: 38,354ms ████████████████████

## 测试过程问题与修复

### 问题 1：Qwen TTS HuggingFace 缓存损坏
现象：Qwen TTS 首次合成返回 503，错误为 "config file is not a valid config file"。 根因：HuggingFace 缓存中所有快照文件为 0 字节。Windows 不支持符号链接（未开启开发者模式）， 导致 snapshot → blob 的符号链接创建失败，文件内容为空。 修复：删除损坏的快照目录和 0 字节 blob，保留 4 个有效大 blob（3.6GB 模型权重 + 650MB 语音 tokenizer + 2 个小文件），通过 huggingface_hub.snapshot_download 重新拉取。大文件被复用，仅下载缺失的小配置文件，7 秒完成。

### 问题 2：VoiceDesign 模型未缓存
现象：Qwen TTS 默认使用 VoiceDesign 模型，但本地仅缓存了 CustomVoice 模型。 修复：设置 QWEN_TTS_MODEL 环境变量为 CustomVoice，使用已缓存模型避免下载。

### 问题 3：GSV 无参考音频
现象：GSV 需要参考音频进行音色克隆，项目内无现成的语音样本。 修复：使用 Windows 内置 SAPI（System.Speech）生成中文参考音频"大家好，欢迎使用语音合成系统。"。

## 结论

| 评估维度          | 结论                                                                      |
| ----------------- | ------------------------------------------------------------------------- |
| GSV 合成能力      | ✅ 全部通过，4/4 测试成功，中文/混合语言均正常合成                         |
| Qwen TTS 合成能力 | ✅ 全部通过，4/4 测试成功，中文/混合语言均正常合成                         |
| GSV 性能          | ✅ 后续请求 1.3~7.3s，适合实时对话场景                                     |
| Qwen TTS 性能     | ⚠️ 后续请求 7.4~38.4s，长文本较慢，适合非实时场景                        |
| 双引擎互补        | GSV 适合实时语音专线（低延迟），Qwen 适合高质量离线合成（零样本、多音色） |

P.A.L.M TTS 合成测试报告 · 2026-08-09 · 测试设备: RTX 5060 Laptop (8GB) · torch 2.8.0+cu128

---


## GSV 环境搭建与合成实测

测试时间：2026-08-09 16:27 · 硬件：RTX 5060 Laptop (8GB VRAM) · CUDA 12.8 · torch 2.8.0+cu128

## 一、测试环境

| 项目     | 详情                                                                   |
| -------- | ---------------------------------------------------------------------- |
| GPU      | NVIDIA RTX 5060 Laptop (8GB VRAM)                                      |
| CUDA     | 12.8                                                                   |
| PyTorch  | 2.8.0+cu128 (torchaudio 2.11.0)                                        |
| Python   | 3.10.10 (.venv-gsv 独立虚拟环境)                                       |
| 模型版本 | v2 (gsv-v2final-pretrained)                                            |
| 精度     | FP16 (半精度)                                                          |
| 流式模式 | normal (分块流式返回)                                                  |
| 标点切分 | ，。？！；：                                                           |
| 音频格式 | OGG / int16                                                            |
| 参考音频 | ref_audio.wav (22050Hz, 单声道, ~7.7s) — Windows Speech Synthesis 生成 |

## 二、环境搭建 — 解决的 7 个问题

| # | 问题                                     | 根因                                                                                   | 解决方案                                                                        | 类型     |
| - | ---------------------------------------- | -------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- | -------- |
| 1 | AR.models 模块完全缺失                   | 源码分发时 AR/models/ 目录丢失（含 t2s_lightning_module.py / t2s_model.py / utils.py） | 从 GPT-SoVITS 官方仓库 + jsDelivr CDN 补全 3 个文件                             | 缺失文件 |
| 2 | jieba_fast 编译失败                      | MSVC 缺少 Windows SDK 头文件 (io.h)，C++ 扩展无法编译                                  | 创建 jieba_fast 兼容 shim → 重定向到纯 Python jieba（含 posseg/analyse 子模块） | 编译失败 |
| 3 | torchaudio.load 强制依赖 torchcodec      | torchaudio 2.11.0 默认使用 torchcodec 后端，但 torchcodec 的 FFmpeg DLL 缺失           | sitecustomize.py monkey-patch：torchaudio.load 回退到 soundfile 后端            | 依赖缺失 |
| 4 | fast_langdetect 模型缺失                 | lid.176.bin 语言识别模型未下载，文本语言分割失败                                       | 从 fbaipublicfiles 下载 lid.176.bin (125.2 MB)                                  | 模型缺失 |
| 5 | g2pW.onnx 缺失                           | 中文多音字消歧模型未随源码分发                                                         | 从 ModelScope 下载 G2PWModel_1.1.zip (561.6 MB) 并提取 g2pW.onnx                | 模型缺失 |
| 6 | NLTK averaged_perceptron_tagger_eng 缺失 | NLTK 新版需要 _eng 后缀的资源，旧版资源不兼容                                          | nltk.download('averaged_perceptron_tagger_eng')                                 | 资源缺失 |
| 7 | zero_wav UnboundLocalError               | 预加载缓存命中时，zero_wav 变量仅在未命中分支定义，缓存命中后引用未定义变量            | 在缓存命中分支添加 zero_wav = zero_wav_torch.cpu().float().numpy()              | 代码 Bug |

## 三、实测结果

### 核心指标总览
0.49s

中文首字延迟（长文本）

22.8

中文合成速度（字/秒）

3.51s

80字总合成时间

3.21s

中英混合首字延迟

### 详细测试数据

| 测试     | 字数 | 首字延迟 | 总时间 | 音频大小 | 估算时长 | 速度(字/s) |
| -------- | ---- | -------- | ------ | -------- | -------- | ---------- |
| 短文本   | 5    | 0.710s   | 0.710s | 14.0 KB  | 0.45s    | 7.0        |
| 中等文本 | 30   | 0.609s   | 1.559s | 28.3 KB  | 0.91s    | 19.2       |
| 长文本   | 80   | 0.490s   | 3.510s | 78.5 KB  | 2.51s    | 22.8       |
| 中英混合 | 40   | 3.212s   | 4.119s | 24.3 KB  | 0.78s    | 9.7        |

### 首字延迟 vs 总时间（流式效果可视化）
0.71s

短文本(5字)

1.56s

中等(30字)

3.51s

长文本(80字)

4.12s

中英混合(40字)

首字延迟 后续合成时间 中英混合首字（含NLTK加载）

## 四、与历史测试对比

| 指标         | 历史测试 (2026-08-09 上午) | 本次测试                | 变化     |
| ------------ | -------------------------- | ----------------------- | -------- |
| 平均合成速度 | 11.5 字/s                  | 22.8 字/s               | ↑ 98%    |
| 平均总时间   | 3.9s                       | 3.5s (80字)             | ↓ 10%    |
| 首字延迟     | 未测量（无流式）           | 0.49-0.71s              | 新增指标 |
| 流式分块     | 未启用                     | normal 模式             | 已启用   |
| 预加载       | 无                         | 参考音频编码 + GPU 预热 | 已启用   |

## 五、关键发现
- 中文首字延迟 0.49-0.71 秒：流式模式下，用户在 1 秒内就能听到第一个字的声音，体验接近实时
- 合成速度 22.8 字/秒：80字长文本仅需 3.5 秒完成全部合成，相比历史测试提升近一倍
- 预加载效果显著：参考音频编码预计算 + GPU 预热使首次请求无需冷启动，延迟稳定
- 中英混合延迟较高：首字延迟 3.2 秒，因 NLTK 英文词性标注资源首次加载开销大；后续请求应显著降低
- 标点切分有效：启用中文标点切分后，长文本被分成多个句子并行流式输出，首字延迟不受总文本长度影响
- 0.8 秒目标：中文纯文本已接近 0.8 秒首字延迟目标；中英混合需优化 NLTK 资源预加载

## 六、待优化项
- NLTK 资源预加载：在服务启动时预加载 averaged_perceptron_tagger_eng，消除中英混合首请求的 3 秒延迟
- onnxruntime CUDA 支持：当前 onnxruntime 不支持 CUDA 12.x，G2PW 多音字推理走 CPU；安装 onnxruntime-gpu 可减少约 50-100ms
- 参考音频质量：当前参考音频为 Windows TTS 生成，使用真人录音可提升音色还原度
- v3/v4 模型测试：本次仅测试 v2 模型，v3 (BigVGAN) 和 v4 (HiFiGAN) 声码器可提供更高音质

## 七、结论
GSV 环境搭建完成，所有 7 个依赖/代码问题已解决。实测结果表明：

- 中文合成：首字延迟 0.49-0.71s，合成速度 22.8 字/s，满足实时对话需求
- 流式效果：标点切分 + 流式返回使首字延迟与文本长度解耦，长文本也能快速出声
- 预加载：参考音频编码预计算 + GPU 预热有效消除冷启动延迟
- 对比 Qwen TTS：GSV 速度优势显著（22.8 vs 2.2 字/s），但需要参考音频；Qwen TTS 零样本但速度慢

---

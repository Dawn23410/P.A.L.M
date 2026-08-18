# tts_sovits — 语音合成砖块

> 基于 [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS) 的 P.A.L.M 语音合成砖块。

## 概述

`tts_sovits` 是 P.A.L.M 桌面助手的可选砖块（brick），提供文字转语音（TTS）能力。砖块内嵌完整的 GPT-SoVITS 源码，通过独立 venv 运行重依赖（PyTorch / Transformers），以 HTTP 子进程方式与 P.A.L.M 主进程隔离，互不污染。

### 特性

- **源码随砖块分发**：GPT-SoVITS 源码直接包含在 `gpt_sovits/` 目录，无需额外下载
- **进程级隔离**：重 ML 依赖运行在独立 venv + 子进程，主进程零侵入
- **Agent 工具集成**：自动注册 `text_to_speech` 工具，Agent 可直接调用
- **流式合成**：支持分块流式输出，首字延迟低
- **音色克隆**：支持参考音频指定音色，默认音色开箱即用
- **优雅降级**：未安装依赖或无 GPU 时自动跳过，不阻断 P.A.L.M 启动

## 目录结构

```
plugins/tts_sovits/
├── brick.yaml          # 砖块清单（元信息/依赖/模型声明）
├── brick.py            # 砖块注册与 HTTP 路由（含子进程启动命令构造）
├── install.py          # 安装脚本（venv 创建 + pip install）
├── client.py           # GSV 上游 HTTP 客户端
├── tool.py             # Agent 工具定义
├── __init__.py         # 包入口
└── gpt_sovits/         # GPT-SoVITS 源码（随砖块分发）
    ├── api.py           # GSV 推理 API（子进程入口）
    ├── api_v2.py        # GSV v2 API
    ├── config.py        # GSV 配置
    ├── requirements.txt # GSV 依赖清单
    ├── extra-req.txt    # 额外依赖（ASR）
    ├── LICENSE          # MIT 许可证
    └── GPT_SoVITS/      # 核心实现
        ├── AR/          # 自回归模型
        ├── module/      # 声学模块
        ├── text/        # 文本处理（多语种）
        ├── feature_extractor/
        ├── configs/     # 模型配置
        └── ...
```

## 环境要求

| 项目 | 要求 |
|------|------|
| Python | 3.11（受 `transformers<=4.50` + `numpy<2.0` 约束） |
| GPU | NVIDIA CUDA（推荐）/ CPU（可用但慢） |
| 磁盘 | venv 约 5-6 GB + 模型约 3-4 GB |
| 系统 | Windows / Linux |

## 安装

### 1. 创建 venv 并安装依赖

```bash
python plugins/tts_sovits/install.py
```

该脚本会：
1. 在项目根创建 `.venv-gsv` 虚拟环境（Python 3.11）
2. 安装 `gpt_sovits/requirements.txt` 中的依赖
3. 安装 `gpt_sovits/extra-req.txt` 中的额外依赖

### 2. 下载预训练模型

模型不随源码分发。请从 [GPT-SoVITS Releases](https://github.com/RVC-Boss/GPT-SoVITS/releases) 下载预训练模型，放置到：

```
gpt_sovits/GPT_SoVITS/pretrained_models/
├── gsv-v2final-pretrained/
│   ├── s2G2333k.pth
│   └── s1bert25hz-5kh-longer-epoch=12-step=369668.ckpt
├── chinese-hubert-base/
├── chinese-roberta-wwm-ext-large/
└── ...
```

具体模型路径见 `brick.yaml` 的 `models` 字段。

### 3. 配置（可选）

通过环境变量覆盖默认配置：

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `SOVITS_ROOT` | `plugins/tts_sovits/gpt_sovits` | GSV 源码目录 |
| `SOVITS_API_PORT` | `9880` | API 服务端口 |
| `SOVITS_INFER_DEVICE` | `cuda` | 推理设备（`cuda`/`cpu`） |
| `SOVITS_AUTO_LAUNCH` | `true` | 启动时自动拉起子进程 |
| `SOVITS_DEFAULT_REFER_WAV` | （空） | 默认参考音频路径 |
| `SOVITS_DEFAULT_REFER_TEXT` | （空） | 默认参考音频对应文本 |
| `SOVITS_DEFAULT_REFER_LANG` | `zh` | 默认参考音频语种 |

## 使用

### HTTP 接口

```http
# 合成语音
POST /api/tts/synthesize
{
  "text": "你好世界",
  "text_language": "zh"
}

# 流式合成
POST /api/tts/synthesize-stream

# 查询状态
GET /api/tts/status

# 手动拉起
POST /api/tts/launch
```

### Agent 工具

砖块自动注册 `text_to_speech` 工具，Agent 可在对话中直接调用：

```
用户：帮我念一下这段话
Agent：[调用 text_to_speech 工具合成语音]
```

## 许可证

- GPT-SoVITS 源码：[MIT License](gpt_sovits/LICENSE) (c) 2024 RVC-Boss
- 砖块封装代码：随 P.A.L.M 项目许可

## 致谢

- [GPT-SoVITS](https://github.com/RVC-Boss/GPT-SoVITS) — RVC-Boss 开源的零样本/少样本语音合成系统
- [BigVGAN](https://github.com/NVIDIA/BigVGAN) — NVIDIA 声码器
- [HuBERT](https://github.com/facebookresearch/fairseq) — Meta 语音表征模型

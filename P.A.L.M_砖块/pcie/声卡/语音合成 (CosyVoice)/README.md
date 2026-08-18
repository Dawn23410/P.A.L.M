# cosyvoice 砖块（音色创造 · 完整砖）

基于 **CosyVoice2** 的「音色创造」砖块——与 GSV（GPT-SoVITS）互补：

- **本砖（CosyVoice2）= 音色设计师**：用一段基底参考音频 + 自然语言风格描述，
  产出一段干净、可克隆的参考音频（`.wav` + `.txt`），落盘到 `Data/cosyvoice_voices/`。
- **GSV（GPT-SoVITS）= 实时播音员**：经 `refer_wav_path` 克隆该参考音频，做低延迟实时合成。

> 侧重点是**造音色**，不是语言合成。本砖不负责把用户的话实时念出来，
> 那是 GSV 的活；本砖只负责「把想要的音色造出来、交给 GSV 去克隆」。

## 完整砖（非薄代理）

本砖是**完整砖**：CosyVoice2 模型在砖进程内直接加载与推理，路由 / capability / Agent
工具都直接调用 `engine.py`，**不经过任何外部 HTTP 服务、不含 client/serve 代理、不拉起
独立子进程**。这与 `tts_sovits`（薄代理 + 外部 serve.py）是相反的取向。

- **懒加载**：`cosyvoice` 重依赖在首次 `create_voice` 时才懒导入，模型也懒加载，
  不常驻占显存，P.A.L.M 启动不被阻塞。
- **优雅降级**：若 `cosyvoice` 未安装，`is_available()` 返回 False，`/status` 给出安装提示，
  `create_voice` 返回明确「未安装」错误——不抛导入异常、不阻断启动。
- **代价**：模型与 P.A.L.M 同进程，显存/内存共享。8GB 卡上 GSV(2.5G)+Cosy2-0.5B(4G)
  共存偏紧，建议错峰/按需（首次造音才加载，用完留在进程内；需释放可重启）。

## 为什么是 CosyVoice2

- 支持 **instruct2 模式**：在一段基底参考音频之上，用自然语言指令叠加风格
  （情绪、方言、语速、角色感），例如「温柔的少女音色，带一点慵懒和笑意」。
- 3 秒零样本克隆基底；中文 WER 低；模型仅 0.5B，约 4GB 显存即可跑。
- Apache 2.0，可商用。

> 注意：CosyVoice2 的 instruct 必须配合**基底参考音频**（v2 已无纯 spk_id 的
> instruct）。所以本砖的核心路径始终需要 `seed_audio`（请求提供，或配置
> `COSY_DEFAULT_SEED_VOICE` 作默认基底）。不带描述时退化为纯克隆（zero_shot）。

## 架构

```
P.A.L.M 主进程
  └─ plugins/cosyvoice/brick.py  (HTTP 路由 + capability + Agent 工具)
       └─ engine.py  (直接持有 CosyVoice2 单例，进程内推理；懒加载)
```

无独立 venv、无 serve.py、无端口、无 HTTP 代理。

## 安装

```bash
# 把 CosyVoice2 依赖装入运行 P.A.L.M 的同一 Python 环境（完整砖要求）。
# install.py 是守卫安全、可复现的安装器：自动探测 Blackwell→cu128、拷贝 vendored
# 源码、--no-deps 装叶子包、写 shim，绝不 uninstall 已装包。
python plugins/cosyvoice/install.py

# 权重（本机已落盘 Data/cosyvoice_model/，含 llm.pt / flow.pt / hift.pt / cosyvoice2.yaml）：
# 上游：https://github.com/FunAudioLLM/CosyVoice  （模型 iic/CosyVoice2-0.5B）
# 国内镜像可用 ModelScope / hf-mirror 下载，无需直连 GitHub。
```

## 本机验证的关键坑（RTX 5060 Laptop / Blackwell sm_120）

`install.py` 已把这些坑全部封装好，此处仅记录来龙去脉，便于排错：

1. **torch 必须 cu128，不是 cu126。** RTX 5060 是 Blackwell 架构（compute cap 12.0），
   cu126 只编译到 `sm_90`，推理会报 `CUDA error: no kernel image is available for execution
   on the device`。cu128（CUDA 12.8）才含 `sm_120` 内核镜像。本机实测 `torch.cuda.get_arch_list()`
   为 `['sm_75','sm_80','sm_86','sm_90','sm_100','sm_120']`。
2. **vendored 源码而非 PyPI 包。** `cosyvoice` / `matcha` 直接拷贝进 site-packages
   （`Data/CosyVoice_src/cosyvoice`），不走 PyPI 的 `cosyvoice` 发行包（版本/依赖不匹配）。
3. **训练专用依赖用 shim 顶替。** 配置加载链会 import `lightning`/`gdown`/`wget`/`librosa`/
   `soxr`/`pkg_resources`/`whisper.tokenizer`，但推理从不使用。这些用纯 Python 保真 shim 顶替
   （如 `librosa.filters.mel` 用 NumPy 重实现、`pkg_resources` 用 `importlib.metadata`、
   `whisper.tokenizer` 仅占位），避免拉一整棵训练依赖、也避开 setuptools 83 移除 pkg_resources 的坑。
4. **音频 I/O 绕开 torchcodec。** torchaudio 2.11 把 `soundfile` 后端路由到 torchcodec，
   本机无 ffmpeg 会失败。已改为直接用 `soundfile`（pysoundfile）读/写 wav。
5. **引擎 bug 修正。** `create_voice` 必须把**文件路径**传给 `inference_instruct2` /
   `inference_zero_shot`（CosyVoice2 内部自行 `load_wav`），不能传预加载张量。

验证：`Data/cosy_smoke_test.py` 跑通 instruct2 + zero_shot 两种模式，产出
`Data/cosyvoice_voices/*.wav`（+ `.txt` + `.json`），`.json` 含 `gsv_refer_wav_path` 供 GSV 克隆。

## 配置（backend/app/core/config.py，均可用环境变量覆盖）

| 配置项 | 环境变量 | 默认 | 说明 |
| --- | --- | --- | --- |
| `COSY_MODEL_DIR` | `COSY_MODEL_DIR` | `Data/cosyvoice_model` | 权重目录 |
| `COSY_INFER_DEVICE` | `COSY_INFER_DEVICE` | `cuda` | `cuda` / `cpu` |
| `COSY_OUTPUT_DIR` | `COSY_OUTPUT_DIR` | `Data/cosyvoice_voices` | 参考音频落盘目录 |
| `COSY_DEFAULT_SEED_VOICE` | `COSY_DEFAULT_SEED_VOICE` | 空 | 默认基底参考音频（无 seed_audio 时兜底） |
| `COSY_DEFAULT_SEED_TEXT` | `COSY_DEFAULT_SEED_TEXT` | 空 | 默认基底原文 |
| `COSY_DEFAULT_SAMPLE_TEXT` | `COSY_DEFAULT_SAMPLE_TEXT` | 「你好，我是这个音色…」 | 参考音频朗读文案 |

## 使用

### Agent 工具 `create_voice`

```
create_voice(
  description="温柔的少女音色，带一点慵懒和笑意",
  seed_audio="C:/.../my_base_voice.wav",
  sample_text="你好，我是这个音色，很高兴为你服务。",
)
```

返回参考音频路径 + GSV 克隆指令：

```
refer_wav_path=Data/cosyvoice_voices/cosy_xxx.wav
prompt_text=你好，我是这个音色，很高兴为你服务。
prompt_language=zh
```

把 `refer_wav_path` / `prompt_text` 交给 GSV 的 `text_to_speech` 工具即可克隆该音色。

### HTTP 接口

- `POST /api/cosy/create_voice` — 造音（需 `cosyvoice.create_voice` 权限）
- `GET  /api/cosy/voices` — 列出已造音色
- `GET  /api/cosy/status` — 运行时状态（含 `mode: in-process`）
- `GET  /api/cosy/audio/{filename}` — 回放某参考音频

### 端到端示例（造音 → GSV 克隆）

```bash
# 1. 造音
curl -X POST http://127.0.0.1:8000/api/cosy/create_voice \
  -H "Content-Type: application/json" \
  -d '{"description":"温柔的少女音色，带一点慵懒","seed_audio":"Data/seed.wav","sample_text":"你好呀"}'

# 2. 取返回的 wav_path，交给 GSV 克隆（经 GSV 的 text_to_speech）
curl -X POST http://127.0.0.1:8000/api/tts/synthesize \
  -H "Content-Type: application/json" \
  -d '{"text":"今天天气真好","refer_wav_path":"Data/cosyvoice_voices/cosy_xxx.wav","prompt_text":"你好呀","prompt_language":"zh"}'
```

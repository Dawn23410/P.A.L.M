# 声纹识别砖（speaker）

基于 **CAM++（campplus，sherpa-onnx）** 的本地说话人识别砖块。与 `语音识别`（stt）砖
同模式：推理引擎跑在砖内独立 venv（`.venv-speaker`）的独立子进程，主进程绝不 import
`sherpa_onnx`；识别结果经事件总线 `voice.speaker` 广播，供对话/记忆链路按说话人切换
角色与个性化。

## 能力

- 注册说话人（`enroll`）：名称 → 平均 192 维声纹嵌入，持久化到 `data/speakers.json`
- 1:N 识别（`identify`）：输入音频，返回最相似说话人 + 余弦相似度
- 验证（`verify`）：输入音频与指定说话人比对，按阈值判是否匹配
- 本地声纹库：零联网、零云端依赖

## 模型

- **CAM++ fp16 ONNX**（`src/speaker_models/campplus_zh_en_fp16.onnx`，14MB）
- 中文训练约 20 万说话人；CPU 推理 ~70ms/句；余弦相似度比对
- 默认阈值 `0.31`（sherpa-onnx 默认值，可用准确性检验集重新标定）

## 安装

```bash
python 声纹识别/src/install.py
```

创建 `.venv-speaker`（sherpa-onnx / onnxruntime / sounddevice / numpy / httpx /
soundfile）并下载 CAM++ 模型。P.A.L.M 启动时自动拉起引擎子进程。

## 运行接口

| 端点 | 方法 | 说明 |
|---|---|---|
| `/api/speaker/status` | GET | 引擎就绪状态、已注册说话人 |
| `/api/speaker/enroll` | POST | `{name, wav_path}` 注册 |
| `/api/speaker/identify` | POST | `{wav_path}` 1:N 识别，并广播 `voice.speaker` |
| `/api/speaker/verify` | POST | `{name, wav_path}` 验证 |
| `/api/speaker/list` | GET | 列出说话人 |
| `/api/speaker/remove` | POST | `{name}` 删除 |

跨砖经能力总线调用：`is_speaker_available` / `enroll_speaker` / `identify_speaker` /
`verify_speaker` / `list_speakers`。

## 与 stt 的音频共享（实时链路）

麦克风由单一采集点打开，原始 PCM 帧经本地 socket/pipe 复制给 stt 与声纹两个引擎子进程
（避免 PortAudio 设备独占）。声纹引擎已提供 `/audio_frame`（摄入 int16 PCM）与
`/flush_identify`（段结束识别）端点，stt 引擎只需在采集回调里把帧扇出到此即可。事件总线
`voice.speaker` 只在识别结果层广播，**不承载原始音频帧**（音频走专用通道，总线仅传结果）。

## 准确性

见 `accuracy_report.md`（用 CosyVoice 砖生成的检验集评估；TTS 合成语音为冒烟级验证，
真实人声基准建议用 CN-Celeb / VoxCeleb 复测）。

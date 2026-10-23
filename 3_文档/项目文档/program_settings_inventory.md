# P.A.L.M 主程序可设置内容 & 前端对接清单

> 整理时间：2026-08-24
> 范围：P.A.L.M 主程序（mentalcore / guardrail / memory / 语音链路 / 后端 engine）所有可配置项，
>       以及运营控制台前端（ui/migrated-frontend）需要消费的数据与接口。
> 用途：作为前端团队对接主程序的唯一事实源。

---

## 〇、现状说明（重要）

- 控制台前端已迁移至 `ui/migrated-frontend`（React 18 + antd 5 + zustand + vite）。
- 本控制台**仅保留两大模块**：
  1. **仪表盘（Dashboard）** —— 系统监控（CPU/内存/GPU/网络/存储）+ 模块状态 + 控制台输出。
  2. **语音播报（TTS）** —— 仅 GPT-SoVITS 引擎（GSV 线已接上）。
- **已移除**：Qwen3-TTS 全部前端（页面 / api / 配置 / 样式）；模块管理（ModuleManagement）整页。
- **原侧边栏其他入口（壁纸 / Dock / Agent / ASR）的具体内容页已删除**，其对应 schema 配置字段在 `configSchema.ts` 中仍保留（供将来扩展，不影响当前构建）。

---

## 一、环境变量与部署配置（来源：`.env` / `.env.example`）

> 不填则用默认值，应用可直接启动。复制 `.env.example` 为 `.env` 后覆盖。

### 1.1 服务监听
| 变量 | 默认 | 说明 |
|---|---|---|
| `HOST` | `127.0.0.1` | 后端监听地址 |
| `PORT` | `8000` | 后端监听端口 |
| `CORS_ALLOW_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000,http://127.0.0.1:8000` | 跨域白名单（开发/PyWebView/静态托管） |

### 1.2 GPT-SoVITS 语音合成（`tts_sovits` 内置砖，推理跑在独立 venv `.venv-gsv` 子进程）
| 变量 | 默认 | 说明 |
|---|---|---|
| `SOVITS_ROOT` | 砖内 `src/GPT_SoVITS` | GPT-SoVITS 源码根 |
| `SOVITS_API_URL` | `http://127.0.0.1:10080` | GSV API 地址（**前端 `gptSoVits` 服务 baseUrl**） |
| `SOVITS_API_PORT` | `10080` | GSV API 端口 |
| `SOVITS_API_ROUTE` | `/` | 路由前缀 |
| `SOVITS_INFER_DEVICE` | `cuda` | 推理设备 |
| `SOVITS_SOVITS_MODEL` | `GPT_SoVITS/pretrained_models/gsv-v2final-pretrained/s2G2333k.pth` | SoVITS 模型 |
| `SOVITS_GPT_MODEL` | `gsv-v2final-pretrained/s1bert25hz-5kh-longer-epoch=12-step=369668.ckpt` | GPT 模型 |
| `SOVITS_HUBERT_DIR` | `chinese-hubert-base` | HuBERT 目录 |
| `SOVITS_BERT_DIR` | `chinese-roberta-wwm-ext-large` | BERT 目录 |
| `SOVITS_DEFAULT_REFER_WAV` | `gpt_sovits/ref_audio.wav` | 默认参考音频 |
| `SOVITS_DEFAULT_REFER_TEXT` | `你好，我是语音助手。` | 默认参考文本 |
| `SOVITS_DEFAULT_REFER_LANG` | `zh` | 默认参考语种 |

> 前端 GSV **运行时（整合包管理）** 地址：`SOVITS_RUNTIME_URL` 默认 `http://127.0.0.1:5000`（前端 `gptSoVitsRuntime` 服务；env 覆盖键 `VITE_GSV_RUNTIME_BASE`）。

### 1.3 STT 语音识别（内置砖 `stt`，独立 venv `.venv-stt`）
| 变量 | 默认 | 说明 |
|---|---|---|
| `STT_ENABLED` | `false` | 是否启用 STT |
| `STT_AUTO_LAUNCH` | `true` | 自动拉起推理子进程 |
| `STT_API_URL` | `http://127.0.0.1:19500` | STT 服务地址 |
| `STT_SAMPLE_RATE` | `16000` | 采样率（固定单声道 16kHz） |
| `STT_VAD_MODEL` / `STT_ASR_MODEL` / `STT_KWS_MODEL` / `STT_KWS_KEYWORDS` | 按 `Data/stt_models/` 约定探测 | 模型路径 |
| `STT_VENV_PYTHON` | 自动 | 推理 venv 解释器 |

### 1.4 Qwen3-TTS（语音合成 —— **前端已弃用，后端服务可保留/弃用**）
> 前端不再调用 Qwen-TTS；以下变量仅当后端仍需该服务时有效。
| 变量 | 默认 | 说明 |
|---|---|---|
| `QWEN_TTS_API_URL` | `http://127.0.0.1:19300` | qwen-tts 服务地址 |
| `QWEN_TTS_AUTO_LAUNCH` | `true` | 未配置 URL 时自动拉起 serve.py |
| `QWEN_TTS_MODEL_DIR` | `Data/qwen_tts_voicedesign` | 本地模型目录 |
| `QWEN_TTS_MODEL` | `Qwen3-TTS-12Hz-1.7B-VoiceDesign` | 模型标识（VoiceDesign/CustomVoice/Base） |
| `QWEN_TTS_QUANTIZE` | `4bit` | 量化（4bit/8bit/off） |
| `QWEN_TTS_VOICES_DIR` | 空 | few-shot 参考音色目录 |

---

## 二、后端服务与 API 端点清单（来源：`src/api/apiConfig.ts` + `gptSoVits.ts` + `engine/backend`）

### 2.1 服务注册表（前端 `SERVICES`）
| key | 名称 | 默认 baseUrl | 健康检查端点 |
|---|---|---|---|
| `performance` | 性能监控 | `http://127.0.0.1:8080` | `GET /api/metrics` |
| `moduleManager` | 模块管理 | `http://127.0.0.1:9090` | `GET /api/config` |
| `gptSoVits` | GPT-SoVITS API | `http://127.0.0.1:10080` | `GET /status` |
| `gptSoVitsRuntime` | GPT-SoVITS Runtime（整合包） | `http://127.0.0.1:5000` | `GET /health` |

> 覆盖方式：环境变量 `VITE_PERF_API_BASE` / `VITE_MODULE_API_BASE` / `VITE_GSV_API_BASE` / `VITE_GSV_RUNTIME_BASE`。
> 另含全局 Mock 开关 `VITE_FORCE_MOCK=true` 时前端不请求真实后端，使用 `mockData.ts` 模拟数据。

### 2.2 GPT-SoVITS API（`gptSoVits` :10080）
| 方法 | 路径 | 入参 | 出参 | 前端调用点 |
|---|---|---|---|---|
| GET | `/status` | — | `{status, version?}` | 健康检查 / TTS 页模型状态 |
| POST | `/tts` | `TtsPayload{text, text_lang, ref_audio_path?, ref_text?, ref_lang?, text_split_method?, streaming?}` | audio Blob(wav/mp3) | **GsBasicVoice 语音合成** |
| POST | `/voice-clone` | `VoiceClonePayload{text, text_lang, ref_audio_path, ref_text?, ref_lang?}` | audio Blob | GSV 语音克隆（规划） |
| GET | `/models` | — | `ModelInfo[]{name, version, loaded}` | 模型管理 |
| POST | `/models/set` | `{name}` | `{success}` | 切换模型 |

### 2.3 GPT-SoVITS Runtime（`gptSoVitsRuntime` :5000，整合包管理）
| 方法 | 路径 | 入参 | 出参 | 前端调用点 |
|---|---|---|---|---|
| GET | `/packages/path` | — | `{path}` | 整合包根目录 |
| GET | `/packages/search` | — | `PackageEntry[]{name, path, type?, refLang, modelVersion, cutMethod, audioCount?}` | **TTS 页整合包列表** |
| POST | `/packages/upload` | multipart `file`(.gsvp) | `{name, meta}` | 上传整合包 |
| POST | `/packages/load` | `{path}` | `{success,name,path}` | 加载整合包 |
| POST | `/packages/delete` | `{name}` | `{success}` | 删除整合包 |
| GET | `/packages/config?name=` | — | `{refText,...}` | 高级包参考文本补读 |
| POST | `/packages/download` | `{path}` | `{success,dest}` | 下载整合包 |
| POST | `/files/scan-mates` | `{base_name, dir?}` | `{ckpt[], pth[], wav[], ref_texts[], versions}` | 创建整合包时扫描配套文件 |
| POST | `/files/read` | `{path}` | File | 读取文件（导入参考音频） |

### 2.4 性能监控（`performance` :8080）
| 方法 | 路径 | 出参 | 前端调用点 |
|---|---|---|---|
| GET | `/api/metrics` | `PerfSnapshot{cpu{model,baseFreq,currentFreq,usage,temperature}, memory{speed,total,available,usage}, gpus[{model,usage}], network{uploadSpeed,downloadSpeed}, disks[{mount,total,used}]}` | **Dashboard 概览卡/存储卡** |
| GET | `/api/modules` | `ModuleEntry[]{id, name, status, description}` | **Dashboard 模块状态** |

### 2.5 模块管理（`moduleManager` :9090）
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/config` | 模块配置（健康检查用） |
> 注：前端已移除"模块管理"页面，该服务目前仅作健康检查保留。

---

## 三、前端可配置项（来源：`src/store/configSchema.ts`）

> 所有配置经 `configStore.ts`（zustand + 防抖持久化到 localStorage）管理；`useModuleConfig(moduleId)` 供页面消费。

### 3.1 仪表盘 `dashboard`
| key | 类型 | 默认 | 说明 |
|---|---|---|---|
| `refreshInterval` | number | 1 | 刷新间隔（秒） |
| `visibleWidgets` | select[] | `['system','network','storage','services']` | 可见组件 |

### 3.2 语音播报 `tts`（仅 GPT-SoVITS）
| key | 类型 | 默认 | 说明 |
|---|---|---|---|
| `selectedModel` | select | `gpt-sovits` | 当前模型（**选项仅剩 GPT-SoVITS**） |
| `selectedSection` | select | `voice` | 当前功能：`voice`(语音合成)/`design`(音色设计)/`clone`(语音克隆) |
| `gsvDevice` | select | `cuda:0` | 设备 CUDA/CPU |
| `gsvHalfPrecision` | switch | true | 半精度 |
| `gsvStreaming` | switch | false | 流式输出 |
| `gsvDeterministic` | switch | false | 确定性（复用上次结果调参防随机） |
| `gsvSynthLang` | select | `中文` | 合成语种（中/英/日/粤/韩/中英混合…） |
| `gsvCutMethod` | select | `不切` | 切句方式（不切/四句一切/50字一切/中英文句号切/标点切） |
| `gsvActivePkg` | string | `''` | 当前激活整合包名 |
| `gsCloneSpeed` | number | 1.0 | 克隆语速 |
| `gsClonePauseSec` | number | 0.3 | 克隆句间停顿 |
| `gsCloneTopK` | number | 20 | 克隆 Top-K |
| `gsCloneTopP` | number | 0.8 | 克隆 Top-P |
| `gsCloneTemperature` | number | 0.8 | 克隆温度 |

> **已删除的 qwen 配置项**：`qwenSize`/`qwenDevice`/`qwenDtype`/`qwenFlashAttn` 及原 `tts` 通用 engine/voice/speed/pitch/volume/cache* 等"播报引擎"字段（控制台现聚焦 GSV 合成，不再有通用播报引擎抽象）。

### 3.3 保留但当前无对应页面的 schema（供将来扩展，不影响构建）
`wallpaper` / `dock` / `agent` / `asr` 四个模块的 `DEFAULT_CONFIGS` 与 `GROUPS` 仍在 `configSchema.ts` 中，侧边栏入口已移除，字段暂未使用。

---

## 四、前端需要消费的关键数据（对接要点）

1. **实时指标轮询**：Dashboard 每 `refreshInterval` 秒拉 `/api/metrics`；模块状态每 4s 拉 `/api/modules`。
2. **GSV 模型健康**：TTS 页加载时 `GET /status` 探活，显示"已连接/未连接"。
3. **整合包生命周期**：选择/上传/删除/创建整合包均经 `:5000/packages/*`；上传后轮询 `search` 直至出现。
4. **语音合成产物**：`POST /tts` 返回 WAV Blob，前端用 `URL.createObjectURL` 播放并支持下载。
5. **配置持久化**：所有 `tts`/`dashboard` 配置存 localStorage，重启前端恢复。
6. **控制台命令**：`useConsole` 纯前端模拟（help/状态等），无需后端。

---

## 五、前端 → 主程序对接缺口（需后端/主程序补充确认）

- [ ] `:8080 /api/metrics` 与 `/api/modules` 的真实响应结构（前端已按 `PerfSnapshot`/`ModuleEntry` 定义，待后端对齐字段名）。
- [ ] `:5000` Runtime 服务是否随主程序启动；若未启动，TTS 整合包管理将显示"未连接"（前端已容错）。
- [ ] GSV `:10080 /tts` 的 `text_lang`/`text_split_method` 取值枚举需与 GSV 后端严格一致（前端已做映射：`中文→zh` 等、`不切→none` 等）。
- [ ] Qwen3-TTS 服务若后端仍保留，前端不再消费，可独立下线。

---

## 六、构建与运行

```bash
cd ui/migrated-frontend
npm install
npm run dev        # vite dev server，默认 http://localhost:43210（见 vite.config.ts）
npm run build      # 产物输出到 ui/dist
```

> 注意：在 WorkBuddy 沙箱内运行 dev/build 需关闭 safe-delete（`set GENIE_SAFE_DELETE=off`），否则 vite 清理 `.vite/deps` 缓存会被拦截导致启动失败。`WebUI.bat` 已内置该设置。

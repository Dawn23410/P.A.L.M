# 声卡（PCIe 扩展卡 · 简易主板式容器）

> 对外只暴露「声卡」一块砖；内部像简易主板一样加载并管理 4 个音频引擎组件，
> 统一提供卡级与模块级管理面。外部经 `soundcard_*` 能力即可控制声卡，
> 颗粒度直达声卡内的各个模块。

## 设计要点

- **对外仅含声卡**：发现逻辑只把本砖当作一块砖（PCIe 插槽），4 个引擎作为内部组件
  由声卡自行加载（经 `palm_sdk.bricks.loader`），**不作为独立砖重复发现**。
- **声卡控制内部**：声卡持有各引擎句柄（`registry.get(引擎键)`），内部转发控制。
- **外部颗粒度直达各模块**：`soundcard_command(component, action, **params)` 把指令
  精确下达到任一引擎的任一能力；`soundcard_list_actions(component)` 列出可下发的动作。

## 对外接口（5 通道协议模型）

对外的 6 个命名能力已收敛为 **5 通道**，原语义全部折叠进「控制」通道的控制码：

| 通道 | 能力键 | 方向 | 作用 |
|---|---|---|---|
| 传入 | `soundcard_ingest(envelope)` | 入站 | 入站总线，按 `type` 路由：control→解码器，data→数据通道，其余暂存 |
| 传出 | `soundcard_drain()` | 出站 | 抽取并清空出站队列（心跳信号 + 加载数据包 + 出站数据） |
| 心跳 | `soundcard_heartbeat()` | 出站只读 | 返回统一 UUID 存活信号（就绪/异常两态）；后台每 5s 写入传出队列，消费者没收到即「没活着」 |
| 控制 | `soundcard_control(code, params)` | 双向 | 控制码 + 解码器单入口：`status` / `power.on` / `enable.stt` / `command.cosyvoice.create_voice` / `actions` / `schema` … |
| 数据 | `soundcard_data(payload?)` | 双向 | 与控制面分离的数据载荷通道（音频/文本等），提供载荷即写入并随传出广播 |

HTTP 面（`/api/soundcard/...`，均要求 API token）：`ingest` `drain` `heartbeat`
`control` `data`。

### 首次加载：主动推送加载数据包
`SoundCard.__init__` 完成后，立即向**传出队列**推送一帧 `load_packet`，主板后续接入时
`drain` 即可收到，内容包含三部分：
- **启动引导 `boot`**：卡名/插槽/隔离方式/组件目录映射/心跳周期——主板据此完成卡槽接入。
- **控制码 `control_codes`**：解码器接受的全部控制码表（11 项）——主板据此生成路由表。
- **内容 `content`**：各引擎 加载/启用/就绪/能力 明细。

主板本次未改动；加载数据包暂存于传出队列，待主板侧 drain 消费。

## 卡上引擎（内部组件，保持各自隔离方式）

| 引擎 | registry 键 | 原插槽 | 隔离 |
|---|---|---|---|
| 声纹识别 | `speaker` | cpu | 子进程 |
| 语音识别 | `stt` | cpu | 子进程 |
| 语音合成 (GPT-SoVITS) | `tts_sovits` | pcie | 子进程 |
| 语音合成 (CosyVoice) | `cosyvoice` | pcie | 进程内 |

组件砖经 `load_brick_package` 导入即注册进全局 registry（导入即触发其 `src/__init__.py`
的 `registry.register`），声卡随后取句柄；声卡**不重复注册**组件能力键 → 零键冲突。

## 目录布局

```
pcie/声卡/
├── src/brick.py                  # 容器：加载组件 + 统一控制面
├── src/__init__.py               # 触发 brick 注册
├── brick.yaml
├── 声纹识别/                      # speaker（独立进程）
├── 语音识别/                      # stt（独立进程）
├── 语音合成 (GPT-SoVITS)/         # tts_sovits（独立进程）
└── 语音合成 (CosyVoice)/         # cosyvoice（进程内）
```

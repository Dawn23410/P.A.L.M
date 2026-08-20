# mentalcore · 心智核心（纯库，无内置前端）

开源 AI 陪伴微核心，**以库形态提供，仅暴露插槽接口**（前端由调用方自备）：

- **魔方（MentalCore）**：有性格的聊天核心——六面（人格/记忆/情感/织语/律动/储存）+ 两个中间件（动态注入、回复拆分），好感度吝啬制、情绪识别、防污染清档、五位控制码、对话加密落盘。

纯聊天文本通道（限死）：**不做工具调用、不开深度思考**（一律非推理模型，首字优先）。

## 快速开始（纯库接口，无内置前端）

```bash
pip install -e .            # 可编辑安装（跳过依赖：--no-deps）
cp .env.example .env        # 填入 MENTALCORE_API_KEY（非推理模型端点）
python -m mentalcore.selftest   # 离线自检（带断言，mock 模式，零落盘）
```

接口调用（唯一对外边界 `MentalCoreSlotPort`，四个方法）：

```python
from mentalcore.config import load_config
from mentalcore.core import build_core
from mentalcore.persona_card import default_persona

core = build_core(load_config(), default_persona())   # mock 只聊不记；live 需 .env 配端点
packet, manifest, emotion = core.send_message("你好呀")  # 对话（流式用 stream_message）
core.receive({"mood": "开心"}, "外部上下文")             # 向内注入，下一轮可见
core.control(30000)                                     # 控制码（/code help 同表见 transport.CONTROL_USAGE）
core.get_model_info()                                   # 模型参数
```

控制码最小颗粒度：查/改好感度（30000/30300）、查/改角色卡（40000/40300）、
对话记录明细/删单条/导出（10010/10120/10200）、语义检索（21000）等，
完整清单见 `mentalcore/transport.py` 的 `CONTROL_USAGE`。

## 外骨骼（Work 大魔方）：双 Agent 链

心智魔方（Boss，纯聊天不碰工具）与**外骨骼**（Worker，只干活、无性格）组成异步双链：

- **接入协议 `||EXO||`**：Boss 模型在回复末尾追加 `||EXO||{"goal":...,"context":...}||END||`，`ReplySplitter` 识别后透传，心智核心后台拉起 Worker（不阻塞 Boss 回复）。
- **Worker = 微核心 + 5 小魔方**：`WorkCore`（ReAct 循环）编排 工具/沙箱/计划/通信/记忆 五个微内核。
- **安全三拆分**：工具魔方做权限闸门、沙箱魔方做隔离执行（fail-closed）、通信魔方做全程审计。
- **回传**：Worker 完成后自动 `core.receive()` 把结果交回 Boss，由角色卡做语言加工。
- **模型解耦**：Worker 模型可独立于 Boss（经独立配置注入）；技能包/专业记忆明文，加密仅覆盖聊天等敏感内容。

装配与接线：

```python
from mentalcore import build_core, build_exo, default_persona

boss = build_core(load_config(), default_persona())
# 模型解耦：exo_config 缺省回退主配置；传入独立 Config 即可让 Worker 用不同模型
from mentalcore.config import Config
exo = build_exo(load_config(), exo_config=Config.from_env("MENTALCORE_EXO_"))
boss._exo_broker = exo.make_broker(boss)        # 注入「那一个 tool」

packet, _, _ = boss.send_message("帮我查下日志并汇总")  # Boss 委派 → 后台 Worker 执行
# Worker 完成后经 core.receive() 回传，下一轮 Boss 用角色卡复述结论
```

离线自检：

```bash
python -m mentalcore.exo.selftest    # EXO 解析 / 权限闸门 / 沙箱执行 / 异步回传
```

worker 默认工具：`run_shell`（沙箱隔离）、`summarize`（纯函数）、`danger_reset`（权限演示，默认拒绝）。

## 配置（环境变量 / .env）

| 变量 | 说明 |
|---|---|
| `MENTALCORE_MODE` | `live`（真实 LLM） / `mock`（离线回显，只聊不记） |
| `MENTALCORE_BASE_URL` | OpenAI 兼容端点（不内置任何端点） |
| `MENTALCORE_MODEL` | 模型名（须为非推理模型） |
| `MENTALCORE_API_KEY` | API 密钥（放 .env，已被 .gitignore 忽略） |

密钥默认走 `.env`（gitignore 排除，不进源码）。运行时数据默认落 `mentalcore_data/`。

## 架构

```
对外插槽（ABC）          MentalCoreSlotPort（魔方）   WorkSlotPort（工坊）
                          │                            │
cpu 核心                 MentalCore 编排一轮对话        WorkshopCore 一次任务
                          │                            │
六面（prompt 模块）      人格 / 记忆 / 情感 / 织语 / 律动 / 储存
两个中间件               动态注入（固定上·动态下·清单留痕） / 回复拆分（好感度消费·其余外发）
模型层（纯文本通道）     PalmLLM 桥接 palm provider.stream_chat（非推理，无工具）
```

- 情绪识别放后台线程，不阻塞首字（TTFT 优化）。
- 记忆面只注入最近 3 轮 + 语义召回，注入块 600 字截断防爆。
- 好感度吝啬制：日常 Δ=0，仅关系质变轮 ±1，100 轮全加 ≈ 10 左右。
- 所有数据落盘经 SM4 国密加密（复用 palm crypto 原语，缺失降级明文并告警）。

## 开发

```bash
pytest                              # 17 项离线测试
python -m mentalcore.selftest       # 心智核心全流程自检（mock，带断言）
python -m mentalcore.exo.selftest   # 外骨骼自检：EXO 解析 / 权限 / 沙箱 / 异步回传
python chat_100.py --rounds 100     # 双模型真实对话采集（用户侧动态生成）
python analyze.py                   # 生成 100 轮可视化分析报告（HTML）
```

依赖说明：`palm` 为同仓库兄弟目录（非 pip 依赖），包导入时自动把仓库根加入 `sys.path`；正式分发需把 palm 一并打包。`chromadb` 缺失时语义记忆自动降级为仅近期对话。

## 开源

MIT License（见 `LICENSE`）。

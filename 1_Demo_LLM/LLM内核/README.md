# palm-llm

P.A.L.M 的 **LLM 全栈内嵌独立项目**：多厂商流式调用微内核 + 对话应用服务层。

**内核层**（`palm_llm`）：
- 支持四种协议，按 `cfg.type` 分发（未实现的 type 一律回落 `openai_compat`）：
  - `openai_compat`（默认）—— OpenAI 兼容端点，覆盖绝大多数国内外厂商与网关；
  - `anthropic` —— Anthropic **原生** `/v1/messages`（`x-api-key` + `anthropic-version`）。
    system 外提、`max_tokens` 必填、块级 SSE、原生缓存 token 字段、`output_config.effort`。
    base_url 填站点根地址（`https://api.anthropic.com`，误写 `/v1` 会被自动剥掉）。
  - `ollama` —— Ollama **原生** `/api/chat`，本地部署首选（`think` 是一等参数、
    思维链在 `message.thinking`、返回 token 计数与分段耗时）。base_url 填原生根地址
    （`http://127.0.0.1:11434`，不带 `/v1`）。
  - `gemini` / `google` —— Gemini **原生** `generateContent`。只有 user/model 两个角色、
    内容一律 `parts[]`、system 走 `systemInstruction`、鉴权 `x-goog-api-key`、**无 `[DONE]` 收尾**
    （连接关闭即结束）。思考参数 **3 系列 `thinkingLevel` 与 2.5 系列 `thinkingBudget` 两套并存、
    同传即 400**，档位用**最近邻夹取**（`minimal` → `low`，不是最高档）。
- **能力矩阵前置拦截**（`providers/_capability.py`）：发请求**前**按模型能力挡掉注定失败的调用
  （视觉/文档/体积）。三条铁律：① 只拦**已知不支持**（`capabilities_known=False` 的未知档位
  只记账不硬拦，宁可放过不可错杀）；② 只看内核 `Message`、不看各家 payload 方言；
  ③ 报错必须可照着改（第几条消息 / 什么类型 / 超多少 / 支持什么 / 命中哪条规则）。
  违规抛 `CapabilityError`，未命中则把记账写进 `stats.extra`。见
  `docs/能力矩阵前置拦截_v1.0.md`
- **文档附件**：`Message.files` 与 `images` 同形态（str data URI 或 dict），
  按通道渲染为各家原生文档块 —— OpenAI `{"type":"file",...}`（Chat Completions 官方只认 `.pdf`）、
  Anthropic `{"type":"document",...}`、Gemini 与图片同构的 `inlineData`。
- **类型化异常 + 有界重试 + 结构化日志**：错误分类（据错决策能不能重试）、重试策略
  （`ProviderConfig.retry`，个人低延迟档 / 企业高稳档同一个旋钮）、`request_id` 贯通的结构化
  异步日志。见 `docs/可观测与异常_v1.0.md`
- **函数库入口**：`palm_llm/api.py` 收敛全部公开符号（37 个 `__all__`）——两个动词
  `stream()` / `complete()` 即可调用，`resolve()` 拿配置、`classify_error()` 判错、
  `usage_from()` 归一用量；`palm_llm/__init__.py` 只做再导出。内部件（wire/telemetry/
  profiles/tooltext/capability/multimodal）一律 `_` 前缀、**不对外承诺**。
  见 `docs/API函数库重构_v1.0.md`
- 纯异步流式接口：`async for chunk in provider.complete(...)`
- 事件循环安全的 httpx 客户端复用（按 loop 对象身份缓存，跨循环不串号）
- HTTP/2 优先；未装 `h2` 时自动降级 HTTP/1.1（仅一次警告）
- 思维链随增量透传，兼容多种字段名（`reasoning_content` / `reasoning` / Anthropic 的
  `thinking_delta` / ollama 的 `message.thinking`）
- **两级匹配**：端点/`cfg.type` → 供应商 Profile；模型 id 正则 → 模型级规则。
  字段差异改**数据**，不新增分支
- **回传拆分器**：收尾帧携带跨协议归一的 `stats`（缓存命中 token、TTFT、首个正文 token
  延迟、TPOT/ITP 分位、输出速度等），调用方不必再认各家 `usage` 方言
- **思考块回传**：多轮把上一轮思考送回是部分供应商的硬契约（DeepSeek 带 tools 时必需、
  Kimi K3 无条件；反之 legacy `deepseek-reasoner` 收到即 400）。是否回传由
  `Profile.needs_reasoning_echo` 数据决定，默认不发（安全侧）。见
  `docs/思考块回传契约_v1.0.md`
- **原生 Tool Calling**：声明 / 选择 / 流式分片 / 结果回填四面按通道各自适配
  （ollama 的结果回填字段是 `tool_name` 而非 `tool_call_id`；Anthropic 的强制工具选择与
  手工思考互斥时会**降级为 auto 并记账**在 `stats.extra.tool_choice_downgraded`，
  不静默改写）。见 `docs/工具原生支持审计_v1.1.md`
- **正文文本工具调用降级**：端点未实现原生 function calling 时（自定义 GGUF、透明转发网关），
  模型会把调用写进正文。内核按五族公开约定（Hermes `<tool_call>` / Llama3 `<|python_tag|>` /
  Mistral `[TOOL_CALLS]` / Qwen2.5 `✿FUNCTION✿` / ```json 围栏）把调用抠成正常 `tool_calls`，
  三条安全阀保证不把正常正文误吞，流式下**一字不丢**。见
  `docs/文本工具调用降级_v1.0.md`

**服务层**（`palm_llm.server`，v0.2 起，吸收自 engine/backend）：
- 配置管理（`config.json`）+ 会话持久化（JSON 落盘，`run_chat` 内 `asyncio.to_thread` 不阻塞事件循环）
- `run_chat()` SSE 调度：`meta / reasoning / token / done / error` 事件化，错误不打断前端
- 模型发现 `discovery`（三协议拉远端模型列表）
- HTTP 服务仅一个入口：`palm_llm.server.api`（FastAPI，纯 API，**无前端资源**）
- CLI 三件套（`palm_llm.cli`：交互对话 / Textual TUI / 基准测试）

> **纯 API 定位**：原 `server/web.py`（标准库 http.server 的零依赖 WebUI，含静态前端、
> 代码沙箱、蜜罐审计等无关功能）与 `cli/push_answer.py`（推送到 `/view` 阅读器）已移除。
> 内核只提供 API 与 SSE 事件流，前端由调用方自行实现。
- 数据目录外置：环境变量 `PALM_LLM_HOME`（默认 `~/.palm-llm`），config.json 与 data/ 都挂这里

> 本包从 P.A.L.M 主项目（`P.A.L.M/llm/` 微内核 + `P.A.L.M/engine/backend/` 服务层）合并抽离，
> 自带全部依赖、可独立安装运行，不再依赖 P.A.L.M 任何其他模块。

## 运行方式（内嵌，无需安装）

本目录是 P.A.L.M 主目录下的**内嵌独立项目**：源码自带、开箱即用，**不需要 pip install**。
在 P.A.L.M 主目录内先导入自举内核即可（见主目录 `palm_boot.py`）：

```python
import palm_boot            # 自动把 palm-llm/ 等内嵌项目挂进 sys.path
from palm_llm import stream, complete, resolve   # 函数库入口（等价于 from palm_llm.api import ...）
```

需要的功能按需装第三方依赖（都已在环境里则零安装）：

```bash
pip install -r requirements.txt   # 运行依赖：httpx + pydantic
pip install h2                    # 可选：HTTP/2，降低流式首字延迟
pip install textual rich          # 可选：终端 TUI（chat_tui）
pip install fastapi uvicorn       # 可选：生产部署（FastAPI 入口）
```

## 命令行入口

```bash
palm-llm-chat     # 交互式命令行对话（--config / --list / "单次提问"）
palm-llm-bench    # 基准测试（维度矩阵 / 首字延迟 / 深度思考项）
palm-llm-api      # FastAPI 服务入口（默认端口 10083，/health 健康检查 + SSE；需 pip install "palm-llm[deploy]"）
# 或 python -m palm_llm.cli.chat / python -m palm_llm.server.api
```

## 快速开始

**最简（函数库直调）**：两个动词 —— `stream`（流式）/ `complete`（一次性），不用自己建 Provider。
`cfg` 传字典或 `ProviderConfig` 都行；`model` 留空则用 `cfg.default_model`。

```python
import asyncio
from palm_llm import stream, complete, Message

CFG = {"type": "openai_compat", "base_url": "https://api.openai.com/v1",
       "api_key": "sk-xxx", "default_model": "gpt-4o-mini"}

async def main():
    msgs = [Message(role="user", content="你好")]
    async for ev in stream(msgs, model="gpt-4o-mini", cfg=CFG):     # 流式
        if "content" in ev:
            print(ev["content"], end="", flush=True)
        if ev.get("done"):
            print("\n[完成]", (ev.get("stats") or {}).get("tps"), "tok/s")
    out = await complete(msgs, model="gpt-4o-mini", cfg=CFG)        # 一次性
    print(out["content"], "| total:", out["stats"]["total_tokens"])

asyncio.run(main())
```

> 也可 `prov=` 直接传入已建好的 Provider 实例（复用连接 / 自定义传输），
> 或 `resolve(model=..., type_hint=...)` 先拿到命中的 `(Profile, ModelRule)` 再决定参数。

**进阶（直接持 Provider）** —— 需要精细控制传输/参数时：

```python
import asyncio
from palm_llm import get_provider_instance, ProviderConfig, Message, ModelParameters

cfg = ProviderConfig(
    name="my-openai",
    type="openai_compat",
    base_url="https://api.openai.com/v1",
    api_key="sk-xxx",
    default_model="gpt-4o-mini",
)
prov = get_provider_instance(cfg)

async def main():
    async for chunk in prov.complete(
        [Message(role="user", content="你好")],
        ModelParameters(temperature=0.7, max_tokens=512),
        model="gpt-4o-mini",
        stream=True,
    ):
        if "content" in chunk:
            print(chunk["content"], end="", flush=True)
        if chunk.get("done"):
            stats = chunk.get("stats") or {}
            print("\n[TTFT]", stats.get("ttft_ms"), "ms",
                  "| 输出速度", stats.get("tps"), "tok/s",
                  "| 缓存命中", stats.get("cache_read_tokens"), "tok")

asyncio.run(main())
```

## 接口约定

**对外只需认函数库**：`palm_llm.stream(...)` / `palm_llm.complete(...)`（薄封装，自动 `resolve`
配置并建/复用 Provider）。它们与底层 `BaseProvider.complete(...)` 产出**同一套事件字典**，
契约如下（异步生成器，依次产出）：

| chunk | 含义 |
|---|---|
| `{"content": "文本片段"}` | 增量 token |
| `{"reasoning": "思考片段"}` | 思维链增量（深度思考） |
| `{"tool_call_delta": {"index","id","name"}}` | 工具调用开始（拿到工具名即下发，供前端实时显示） |
| `{"tool_calls": [...]}` | 完整工具调用（arguments 为 JSON 字符串；流式在收尾前给出，非流式一次给全） |
| `{"done": True, "usage": {...}}` | 结束（usage 为厂商原始字段，可选） |
| `{"done": True, "usage": {...}, "stats": {...}}` | `stats` 为**跨协议归一**后的统一字段 |

读数据请优先用 `stats`（缓存命中 token / TTFT / 首个正文 token 延迟 / 输出速度等口径已统一），
`usage` 保留原始字段仅为向后兼容。字段全表见 `docs/回传拆分器字段说明_v1.0.md`。

工具路径两条注记：

- 原生 `tool_calls` 与正文解析出的调用**不会同时**产出 —— 原生是权威通道，派生那份作废
  （避免同一逻辑调用被执行两次）。
- 由正文解析来的调用会把 `stats.finish_reason` 置为 `"tool_calls"`，原值留在
  `stats.extra.finish_reason_vendor`，并以 `stats.extra.text_tool_calls` 标明来源。
- **原生**工具调用的 `finish_reason` 也统一归一为 `"tool_calls"`（Ollama 报 `stop`、
  Gemini 报 `STOP`，不归一则调用方可能静默不执行工具），原值同样存
  `stats.extra.finish_reason_vendor`。

出错时抛出**类型化异常**（均为 `RuntimeError` 子类，`except RuntimeError` 仍兜得住）：
`TransportError` / `UpstreamServerError` / `RateLimitError` / `AuthError` / `BadRequestError` /
`NotConfiguredError` / `StreamInterruptedError` / `CapabilityError`。每个错误带 `retryable`
标记与 `provider` / `model` / `status` / `retry_after` / `request_id` 上下文，调用方可据错决策
（能不能重试、要不要等）。重试按 `ProviderConfig.retry` 策略执行（默认低延迟档：最多重试 1 次、
不退避；企业可传 `STABLE`）。日志为结构化异步输出（`QueueHandler`，热路径零阻塞），
`request_id` 跨 `await` 贯通。详见 `docs/可观测与异常_v1.0.md`。

## 包结构

```
palm_llm/
  api.py              # ★ 内核函数库【唯一公开入口】：stream / complete / resolve / classify_error /
                      #   usage_from + 数据类型(ProviderConfig/Message/ModelParameters/Tool/TurnStats)
                      #   + 四类 Provider + 错误层级 + 重试策略；共 37 个 __all__
  __init__.py         # 纯再导出：from .api import *，__all__ = list(api.__all__)（不再各自 import）
  __main__.py         # python -m palm_llm 演示入口
  models.py           # 内核数据模型（dataclass）：ProviderConfig / Message / Tool / ModelParameters
  errors.py           # 类型化异常层级（PalmLLMError + 8 类）与状态码/传输分类器
  retry.py            # 有界重试策略（LOW_LATENCY / STABLE 两档预设 + 退避/抖动/Retry-After）
  obs.py              # 结构化异步日志（队列非阻塞）+ request_id contextvar 贯通
  providers/
    __init__.py       # PROTOCOLS 协议表 + DEFAULT_PROTOCOL + get_provider_instance 工厂
    base.py           # BaseProvider 抽象基类 + 事件循环安全的 httpx 客户端复用
                      # + 共享件（首字节超时 / 行流拼接 / message 归一 / normalize_tool_calls）
    openai_compat.py  # OpenAI 兼容协议（含原生 Tool Calling + 三级容错降级）
    anthropic.py      # Anthropic 原生 /v1/messages（传输 + 思考配置）
    _anthropic_wire.py# 内核 Message ↔ 原生内容块/SSE 双向转换（内部件，下划线 = 不公开）
    gemini.py         # Gemini 原生 generateContent（传输 + 思考双 API 夹档）
    _gemini_wire.py   # 内核 Message ↔ parts[]/systemInstruction/SSE 双向转换（内部件）
    ollama.py         # Ollama 原生 /api/chat（think 一等参数、message.thinking、分段耗时）
    _tooltext.py      # 正文文本工具调用降级（五族形态 + 三条安全阀；无原生 tool_calls 时兜底）
    _profiles.py      # 两级匹配引擎（Profile / ModelRule / apply_rule / resolve）
    _profiles_data.py # 10 家 Profile 规则数据（唯一事实来源）
    _capability.py    # 能力矩阵前置拦截（视觉/文档/体积，发请求前挡）
    _telemetry.py     # 回传拆分器（字段+口径归一：usage_from / 缓存 token / TTFT / 输出速度…）
    _multimodal.py    # 多模态内容块（文本 / 图片 / 文档附件；content_blocks / data_uri / split_data_uri）
  tests/              # 内核测试（.bench_venv 无 pytest，一律 -m unittest）
    test_api_surface.py            # 函数库契约：__all__ 一致 / 旧名硬切 ImportError / 合并等价 / stream+complete 端到端
    test_ollama_provider.py        # OllamaProvider：纯逻辑用例 + 联调用例（无服务时自动跳过）
    test_openai_compat_degrade.py  # 通用通道 → 降级通道 + stats 挂载（MockTransport）
    test_profiles_matching.py      # 两级匹配 + apply_rule 顺序
    test_telemetry.py              # 回传拆分器：usage 归一与派生指标算式
    test_anthropic_provider.py     # Anthropic 原生通道：载荷形状 / 流式 / 错误解包
    test_gemini_provider.py        # Gemini 原生通道：parts / 思考夹档 / 无 [DONE] 收尾
    test_reasoning_echo.py         # 思考块回传：跨通道契约与凭证往返
    test_tool_text_fallback.py     # 正文文本工具降级（40 例）+ 工具原生支持修复回归（F1–F5）
    test_capability.py             # 能力矩阵前置拦截（27 例：三闸门 + 查询 + 渲染 + 已接线）
    test_errors.py                 # 类型化异常：层级 / retryable / 状态码分类 / interrupted
    test_retry.py                  # 重试策略：退避 / 封顶 / Retry-After / 抖动 / 预设
    test_obs.py                    # 可观测：request_id 传播与隔离 / 日志装配幂等
    test_retry_wiring.py           # 端到端：策略真的接在 provider 上（重试 / 429 / 流中断）
  docs/               # 设计/实测文档（纯中文 + 版本号）
    API函数库重构_v1.0.md            # ★ 函数库化：5 组同类合并 15→6、8 内部模块私有化、api.py 37 导出
    LLM内核架构_v1.5.md              # 最新架构（四通道 + 能力闸门 + 对照实测）
    能力矩阵前置拦截_v1.0.md          # 能力矩阵怎么接进内核、三条铁律、规则逐项复审
    可观测与异常_v1.0.md              # 类型化异常 + 有界重试 + 结构化日志（企业/个人平衡点）
    网关对照实验_v1.0.md              # 与开源实现的控制变量对照实测（净开销）
    适配层决策说明_v1.0.md            # 该不该做中心翻译层
    Anthropic原生通道_v1.0.md
    思考块回传契约_v1.0.md            # 哪些模型必须回传思考块、凭证怎么存
    工具原生支持审计_v1.1.md          # 工具路径 F1–F6 的修复报告（v1.0 为问题清单）
    文本工具调用降级_v1.0.md          # 无原生 tool_calls 时怎么从正文抠调用
    回传拆分器字段说明_v1.0.md
    各供应商各模型支持能力_v2.0.md     # 按模型粒度 + 扩展名/上限
    同功能异字段差异矩阵_v1.0.md
    各模型思考强度调研_v1.0.md
    供应商协议差异与特化通道方案_v1.2.md
    Ollama原生适配_v1.0.md
  server/             # 应用服务层（pydantic 模型，v0.2 起并入）
    __init__.py       # run_chat / load_config / storage / discovery 等导出
    models.py         # 应用模型（AppConfig/ChatRequest/Conversation...，含 to_kernel() 边界转换）
    config.py         # config.json 读写；数据目录 PALM_LLM_HOME（默认 ~/.palm-llm）
    storage.py        # 会话 JSON 持久化 CRUD + 导入导出
    chat.py           # run_chat SSE 调度（落盘走 asyncio.to_thread）
    discovery.py      # 远端模型列表发现（三协议）
    api.py            # FastAPI 服务入口（纯 API，:10083）
  cli/                # 命令行
    chat.py           # 交互式对话（argparse，纯标准库）
    chat_tui.py       # Textual 终端 UI（可选依赖 tui）
    benchmark.py      # 基准测试
bench/gateway/        # 与开源实现的控制变量对照实验（净开销测量）
  mock_upstream.py    # 确定性 mock 上游（固定 token/延迟，关 Nagle、每 chunk 立即 flush）
  clients.py          # 四类客户端：httpx 直连 / 本内核 / LiteLLM / OpenAI SDK
  harness.py          # 计时器（warmup 不计入、顺序单发、服务端耗时减净开销）
  run_bench.sh        # 单次会话内跑完全流程（mock + 各客户端 + Bifrost/Portkey 容器）
  report.py           # 从 results_* JSON 生成中文报告（数字全部从数据算出）
  third_party.md      # 第三方公开基准数字（仅供参考，与本地环境不可比）
```

### 服务层快速用法

```python
import asyncio
from palm_llm.server import run_chat, ChatRequest, ModelParameters

async def main():
    req = ChatRequest(content="你好", provider="zhipu", model="glm-4.5-air",
                      parameters=ModelParameters(max_tokens=512))
    async for ev in run_chat(req):
        if ev["type"] == "token":
            print(ev["content"], end="", flush=True)
        elif ev["type"] == "error":
            print("\n[错误]", ev["message"])

asyncio.run(main())
```

> 内核/服务层边界：服务层 pydantic 模型经 `to_kernel()` 显式转换为内核 dataclass 后
> 才交给 provider，不依赖内核字段的隐式 duck-type。

## 控制变量对照实验（与开源实现）

`bench/gateway/` 是一套**控制变量**对照：让本内核与 LiteLLM / OpenAI SDK（同语言 Python）
以及 Bifrost / Portkey（Go/JS，**跨语言，单独成组**）都指向**同一个本地确定性 mock 上游**，
再减掉「httpx 直连 mock」这条基线，得到**净开销**。

```bash
bash bench/gateway/run_bench.sh           # 一次跑完全流程，结果落 bench/gateway/results_*/
python bench/gateway/report.py            # 生成中文对照报告
```

关键设计：

- **净开销 = 该实现耗时 − 直连 httpx 耗时**，剔除网络与上游抖动；
- 每次实验前后各复测一次基线，量化**漂移带**；
- mock 上游必须 `TCP_NODELAY` + 每 chunk 立即 flush —— 否则「流式小写」会触发
  **Nagle + 40ms 延迟 ACK 伪像**，基线被凭空抬高（本项目实测踩过，见 `third_party.md`）。

本机实测结论：本内核净开销 ≈ **+0.83 ms/次**（同语言最轻；LiteLLM +18.72 ms、
OpenAI SDK +5.85 ms；跨语言 Bifrost +2.73 ms、Portkey +30.45 ms）。在拟真延迟
（~477 ms/回合）下，除 Portkey 外差异**全部淹没**，但 Portkey 仍有约 +24 ms 的首字惩罚。
完整数字与 8 条局限披露见 `docs/网关对照实验_v1.0.md`。

## 自定义 Provider

继承 `BaseProvider`，实现 `async def complete(self, messages, params, model, stream=True)` 即可；
通过 `providers/__init__.py` 的 `get_provider_instance` 工厂按 `cfg.type` 分发。

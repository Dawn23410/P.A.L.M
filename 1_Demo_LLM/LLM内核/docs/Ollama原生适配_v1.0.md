# Ollama 原生适配（内核 Provider）技术文档 v1.0

> 日期：2026-09-22　｜　位置：`1_Demo_LLM/LLM内核/palm_llm/providers/ollama.py`
> 验证环境：Windows 11 + ollama 0.34.1（`127.0.0.1:11434`）+ `spark-x2.5:1.7b`（RTX 5060）
> 姊妹文档：`llm_benchmark/docs/ollama本地首字延迟基准_v1.2.md`（延迟实测）
> 前身：`palm_ollama.OllamaChat`（独立同步客户端，已**迁移并并入**内核，原位置已删除）

---

## 1. 结论（先看这里）

1. **新增内核 Provider `OllamaProvider`**，协议键 `type: "ollama"`（别名 `ollama_native`），
   走 ollama **原生** `/api/chat`，与 `OpenAICompatProvider` 同一接口
   （`async for ev in provider.complete(...)`），由 `get_provider_instance` 按 `cfg.type` 分发。
2. **模型调用统一收归内核** —— 对话适配器从 `Ollama嵌入/palm_ollama` 迁出，
   `palm_ollama` 只保留**嵌入 + 本地模型工作区**，并因此继续维持**零第三方依赖**
   （不必被 httpx / pydantic 拖累，记忆层等底层模块可安全引用）。
3. **顺手修掉三处既有缺陷**（§4）：
   - `openai_compat` 只认 `reasoning_content` → 本地 ollama 的 `reasoning` 被静默丢弃；
   - 关思考示例 `enable_thinking` 对 ollama 无效；
   - `app/engine/config.json` 的 ollama 条目协议/地址/模型名全部过期，
     且 `app/engine/backend/providers/__init__.py` **导入已删除的类，整条 provider 入口 ImportError**。
4. **额外发现并修复**：`app/palm_boot.py` 的搜索根不含 `1_Demo_LLM/` 与 `2_实验/`
   → **整个 app 的 LLM 桥接挂不上内核**（见 §4.4）。
5. **首字延迟（迁移后，走内核 provider）**：median 落在 **54–58ms**（8 批 ×10 轮），
   p99(=max) 58–62ms、极差 7–9ms；总耗时 p50 **1.43–1.61s**（迁移前为 1.79s）。
   比迁移前的 `palm_ollama.OllamaChat`（69.6ms）快约 12ms —— 机制清楚：内核 provider
   复用异步连接池，旧实现每次新建 TCP。详见 §5.3。

---

## 2. 为什么单独实现原生协议，而不是继续用 `/v1` 兼容层

同一模型、同一提示词、同一 `num_predict`，非流式对拍：

| 请求 | 思维链字段 | 思维链字数 | 正文字数 | 墙钟 |
|---|---|---|---|---|
| 原生 `/api/chat` + `think=False` | `message.thinking` | **0** | 110 | 524ms |
| 原生 `/api/chat` + 不传 `think` | `message.thinking` | 102 | **0** | 494ms |
| `/v1/chat/completions` + `reasoning_effort:"none"` | — | 0 | 105 | 471ms |
| `/v1/chat/completions` + 不传参数 | `message.reasoning` | **103** | **0** | 477ms |

- 第 2/4 行：**`spark-x2.5:1.7b` 的模板默认开思考**（不传参就吐思维链）
  → 本实现因此采取"**仅在显式给定时才下发 `think`**"，`None` 一律沿用模型默认，不替用户做决定。
- 第 4 行：103 字思维链落在 **`reasoning`** 字段；老 `openai_compat` 只读 `reasoning_content`
  → 拿到空正文、思考被整体丢弃。
- 原生协议的关思考（第 1 行）与 `/v1` 的 `reasoning_effort:"none"`（第 3 行）效果等价；
  但前者是一等参数，语义明确、跨版本稳定。

**原生协议还多给两样东西**：`prompt_eval_count`/`eval_count` token 计数，
以及**分段耗时**（`load_duration` / `prompt_eval_duration` / `eval_duration` / `total_duration`），
可把一次请求拆成 **模型加载 / 提示预填充 / 解码** 三段做延迟归因 —— `/v1` 连 usage 都不返回。
本实现把这些映射进 `usage` 的 `load_ms` / `prompt_eval_ms` / `eval_ms` / `total_ms`。

---

## 3. 交付物

| 文件 | 变更 | 说明 |
|---|---|---|
| `LLM内核/palm_llm/providers/ollama.py` | **新增** | `OllamaProvider` + 载荷/事件/思考翻译/tool_calls 归一/usage 映射 |
| `LLM内核/palm_llm/providers/base.py` | 修改 | 抽出共享件：`FIRST_BYTE_TIMEOUT` / `FirstByteTimeout` / `chain` / `to_chat_message` |
| `LLM内核/palm_llm/providers/openai_compat.py` | 修改 | 改用共享件；修 `reasoning` 字段；纠正关思考注释 |
| `LLM内核/palm_llm/providers/__init__.py` | 修改 | 注册 `ollama` / `ollama_native`，导出 `OllamaProvider` |
| `LLM内核/palm_llm/__init__.py` | 修改 | 导出 `OllamaProvider` / `OLLAMA_DEFAULT_BASE_URL` |
| `LLM内核/palm_llm/server/discovery.py` | 修改 | 增 ollama 分支（`GET /api/tags` → `models[].name`） |
| `LLM内核/palm_llm/server/models.py` | 修改 | `type` 字段描述补齐两种协议 |
| `LLM内核/palm_llm/cli/chat.py` | 修改 | 新建 provider 时提示两种 type + 地址填法 |
| `LLM内核/tests/test_ollama_provider.py` | **新增** | 12 个用例（6 纯逻辑 + 6 联调），无服务时联调部分自动 SKIP |
| `LLM内核/docs/`、`LLM内核/README.md` | 新增/修改 | 本文件；包结构与协议说明 |
| `Ollama嵌入/palm_ollama/chat.py`、`tests/`、`docs/` | **删除** | 迁移后不保留第二份实现 |
| `Ollama嵌入/palm_ollama/__init__.py`、`README.md`、`_net.py` | 修改 | 收窄职责为"嵌入 + 模型工作区"，零依赖 |
| `app/engine/config.json` | 修改 | ollama 条目：`type: "ollama"`、`base_url` 去 `/v1`、模型名换成本机实际 |
| `app/engine/backend/providers/__init__.py` | 修改 | 移除已删除的 `AnthropicProvider`/`GeminiProvider` 导入 |
| `app/palm_boot.py` | 修改 | 搜索根补上数字前缀容器目录（否则内核挂不上） |
| `llm_benchmark/bench_ollama_native.py` | 重写 | 改为走内核 provider（并注明 base_url 必须用 `127.0.0.1`） |

### API 速览

```python
from palm_llm import get_provider_instance, ProviderConfig, Message, ModelParameters

prov = get_provider_instance(ProviderConfig(
    name="ollama", type="ollama",
    base_url="http://127.0.0.1:11434",     # 原生根地址，不带 /v1
    default_model="spark-x2.5:1.7b"))

await prov.prewarm()          # 预建连（GET /api/tags）
await prov.list_models()      # ['spark-x2.5:1.7b', 'qwen2.5:0.5b']

params = ModelParameters(max_tokens=256, extra_body={"think": False})
async for ev in prov.complete([Message(role="user", content="你好")], params, "spark-x2.5:1.7b"):
    ev.get("reasoning")   # 思维链增量（原生 message.thinking）
    ev.get("content")     # 正文增量
    ev.get("tool_calls")  # 工具调用（已归一为 OpenAI 结构）
    ev["done"], ev["usage"]   # {"prompt_tokens","completion_tokens","total_tokens",
                              #  "load_ms","prompt_eval_ms","eval_ms","total_ms"}
```

**思考开关翻译**（`extra_body`，任一写法都认，其余键顶层透传给服务端）：

| 调用方写法 | 原生 `think` | 备注 |
|---|---|---|
| `{"think": false}` | `False` | 直传，也可给 `"low"/"medium"/"high"` |
| `{"reasoning_effort": "none"}` | `False` | ollama `/v1` 上唯一干净的写法，这里也认 |
| `{"enable_thinking": false}` | `False` | 内核注释里那个（对 `/v1` 无效，这里认） |
| `{"thinking": {"type": "disabled"}}` | `False` | 智谱原生写法（`--no-think` 走的就是它） |
| 不传 / `None` | 不下发 | 沿用模型模板默认 |

**参数映射**：`temperature` / `top_p` → 同名；`max_tokens` → **`num_predict`**；
`frequency_penalty` / `presence_penalty` → 同名；`tools` / `tool_choice` 原样透传。

---

## 4. 修掉的既有缺陷

### 4.1 `openai_compat` 只认 `reasoning_content`（思维链被静默丢弃）

`palm_llm/providers/openai_compat.py` 非流式（原 `:71`）与流式（原 `:118`）
均只读 `reasoning_content`，而 ollama `/v1` 发的是 `reasoning`。

修法（最小）：`msg.get("reasoning_content") or msg.get("reasoning")`（流式同理）。

**验证**：走 `/v1` + 不传关思考参数，修复前思维链 **0 字**，修复后 **125 字**、正文 `'2'`。

### 4.2 关思考注释误导

原注释把 `{"enable_thinking": False}` 列为关思考手段，实测对 ollama 无效。
已改为列出各厂商真实可行的两种写法，并指向原生 provider。

### 4.3 `app` 侧配置与桥接层过期

| 项 | 修复前 | 修复后 |
|---|---|---|
| `config.json` ollama `type` | `openai_compat` | `ollama` |
| `config.json` ollama `base_url` | `http://localhost:11434/v1` | `http://127.0.0.1:11434` |
| `config.json` ollama `models` | `llama3.1 / qwen2.5 / deepseek-r1`（本机都没有） | `spark-x2.5:1.7b / qwen2.5:0.5b` |
| `backend/providers/__init__.py` | `from palm_llm.providers import AnthropicProvider, GeminiProvider` → **ImportError** | 只导入真实存在的符号（+ `OllamaProvider`） |

> `localhost` → `127.0.0.1` 不是洁癖：本机 `localhost` 解析出 `::1` 优先，而 ollama 只监听 IPv4，
> 每次新连接都会白付一次失败建连（实测同步 ~2.05s / 异步 ~250ms）。详见
> `llm_benchmark/docs/ollama本地首字延迟基准_v1.1.md` §3。

### 4.4 `palm_boot.py` 挂不上内核（本次额外发现）

`app/palm_boot.py` 的候选根只覆盖 `ROOT` / `../P.A.L.M` / `../P.A.L.M/实验`，
而现网里项目实际躺在 **`1_Demo_LLM/`**（LLM内核 / 记忆 / 加解密内核 / Ollama嵌入 …）
与 **`2_实验/`**（模型适配 / 智能体框架 / 工具集 …）下 —— 两者都不在候选根里。

**后果（实测）**：`cd app && python -c "import llm"` → `ModuleNotFoundError: No module named 'palm_llm'`。
即 app 的 LLM 桥接整体失效，配置里写什么 `type` 都到不了 provider。

修法（**纯增量**，不改既有根的优先级逻辑）：候选根补上数字前缀容器目录
（`CONTAINER_DIRS = ("1_Demo_LLM", "2_实验")`）及其 `P.A.L.M/<容器>` 变体。

**验证**：修复后 `import llm` → OK，且 `from palm_llm import OllamaProvider` 可见。

---

## 5. 验证结果

### 5.1 测试套件（`palm_llm/tests/test_ollama_provider.py`，12 用例全 PASS）

| 用例 | 覆盖 | 依赖服务 |
|---|---|---|
| `test_registry` | `ollama`/`ollama_native` → `OllamaProvider`；未知 type → `openai_compat` 兜底 | 否 |
| `test_base_url_normalization` | 尾斜杠 / 误写 `/v1` / 空值 均归一到原生根地址 | 否 |
| `test_resolve_think` | 9 种思考开关写法 | 否 |
| `test_build_payload` | options 映射 + think 翻译 + 其余键透传 + 思考键不外泄 | 否 |
| `test_normalize_tool_calls` | dict→JSON 字符串 / id 补全 / 空值 | 否 |
| `test_usage_mapping` | 计数 + 纳秒→毫秒分段耗时 | 否 |
| `test_live_think_off` | 正文非空、思维链为空、usage 有计数与 `*_ms` | 是 |
| `test_live_think_default` | 默认（不传）时思维链落进 `reasoning` | 是 |
| `test_live_non_stream` | 非流式路径 | 是 |
| `test_live_openai_compat_reasoning_field` | **4.1 的回归**：`/v1` 的 `reasoning` 必须被接收 | 是 |
| `test_live_fail_closed` | 坏端口 → `RuntimeError`（含"连接失败"），不静默返空 | 是 |
| `test_live_discovery` | `/api/tags` 列表；误写 `/v1` 也能用；坏地址报错可读 | 是 |

联调用例在 ollama 不可达时打印 `SKIP` 并跳过，**不判失败**（无服务环境下不误报红）。

### 5.2 联调实测输出（节选）

```
[联调 think=False] 首事件=168ms 正文='好' 思维链=0字
                   usage={'prompt_tokens': 21, 'completion_tokens': 2, 'total_tokens': 23,
                          'load_ms': 8.5, 'prompt_eval_ms': 141.8, 'eval_ms': 8.5, 'total_ms': 175.1}
[联调 think=默认]  正文=1字 思维链=79字
[联调 非流式]      正文='好' usage 同上结构
[联调 /v1 字段兼容] 思维链=98字 正文='2'
[fail-closed]      error=RuntimeError: [ollama] 连接失败（已自动重试 1 次）：ConnectError: ...
[discovery]        原生根=['spark-x2.5:1.7b', 'qwen2.5:0.5b'] 误写/v1=同左
```

### 5.3 首字延迟（迁移前 vs 迁移后）

`spark-x2.5:1.7b`、`think=False`、`num_predict=256`、1 轮冷启动 + 1 轮预热均不计入、n=10：

| 实现 | 协议 / base | median | p50 | p90 | p99(=max) | min | 极差 | 总耗时 p50 |
|---|---|---|---|---|---|---|---|---|
| A′ `palm_ollama.OllamaChat`（迁移前，stdlib） | `/api/chat` @ `127.0.0.1` | 69.6 | 69.2 | 79.3 | 79.7 | 55.9 | 23.8 | 1785ms |
| **A `palm_llm.OllamaProvider`（迁移后，httpx）** | `/api/chat` @ `127.0.0.1` | **54.3–58.2**（8 批） | 55.9–58.1 | 60.5 | 61.9 | 52.1 | 7.3–8.7 | 1425–1607ms |
| B `OpenAICompatProvider`（对照，`/v1` @ `localhost`） | `/v1/chat/completions` | 316 | 314.8 | — | 324.2 | 308.6 | 15.6 | 1930ms |

单位 ms。**迁移后共跑 8 批 ×10 轮**，中位首字落在 **54.3–58.2ms** 区间（批间漂移约 ±2ms，
同机同模型同参数；末批数值偏高，推测与 ollama 长时间运行后的负载/热状态有关，未进一步归因）。
末批逐轮：`54.2 58.3 61.9 54.1 57.7 53.3 58.1 60.4 60.5 58.5`。

**迁移后更快的原因**：内核 provider 用 `get_client()` 的**异步连接池**（保活 60s），
旧实现用 urllib 每次新建 TCP（`Connection: close`）；总耗时 p50 也从 1785ms 降到 1425–1607ms。

> ⚠️ **诚实说明**：迁移带来的 ~12ms 差异（69.6 → 54–58）**大于**批间漂移（±2ms），
> 但两者同机同日报测、环境未做隔离，故只作"量级上更快"的结论，不做小数点级归因。
> 唯一有直接机制支撑的是**总耗时**的下降（输出 token 数 10/10 一致，连接复用直接省掉逐 token 传输开销）。

> **n=10 的分位数口径**：nearest-rank 下 `ceil(0.95×10)=10`、`ceil(0.99×10)=10`
> → **p95/p99 全部退化为 max**。上表 p99 只能读作"观测最大值"，非统计 99 分位；
> 真 tp99 需 n ≥ 100。

> ⚠️ **对照行 B 的 316ms 不代表 `/v1` 比原生慢** —— 逐层剥离后，差异主因是 `localhost`
> 的 IPv6 回退（~250ms），协议层两条等价（裸 httpx 对拍：原生 61.6–75.1ms vs `/v1` 68.8–84.4ms）。
> 完整归因见 `llm_benchmark/docs/ollama本地首字延迟基准_v1.1.md` §3。

### 5.3.1 实现细节踩坑：嵌套异步生成器的 aclose 重入

`complete` 最初拆成"外层包装 + 内层 `_stream`"两层异步生成器，功能与数字都正常，
但 10 轮基准的 stderr 里稳定出现：

```
an error occurred during closing of asynchronous generator <async_generator object AsyncClient.stream ...>
RuntimeError: aclose(): asynchronous generator is already running
```

根因：调用方收到 `done` 帧后 `break` 早退 → 外层生成器停在自己的 `yield`（位于
`async with` 之内）→ GC 终结器关闭外层时，内层 httpx stream 也在同期被 aclose，重入告警。

修法：**`complete` 只保留一层生成器**（非流式改用返回 list 的 `_fetch_once` 协程）。
另在基准脚本收尾补 `close_client()`。修后连续 6 批基准 stderr 干净。

> 曾疑心嵌套还带来 ~2ms/token 的生成器帧开销，**对照测试后否证**（单生成器版与嵌套版
> 中位都在 54–58ms 区间）—— 记下来是为了避免下次把批间漂移误当性能问题。

### 5.4 冷启动与预热的边界（实测更正）

`prewarm()` 只预热**连接**（GET `/api/tags`），**不加载模型**：
本轮冷启动轮显示 `首轮 2.07s（首字 1891.9ms，其中模型加载 1765.5ms）`。
要做"连模型一起热"，须在应用启动时主动跑一次 1-token 的 `complete` ——
是否值得由调用方决定（本地模型加载占显存，未必时刻需要）。

---

## 6. 局限与诚实声明

- 全部延迟数据来自**单机、单模型（1.7B）、n=10**，且 `p90/p95/p99` 在 n=10 时退化为极值，
  **不能**当正式尾延迟指标；结论仅在"该路径比那条路径快/慢"的量级对比上成立。
- **批间漂移 ±2ms，且末批明显偏高**（median 58.2ms / 总耗时 p50 1607ms，早批 54.3ms / 1425ms）。
  迁移前 vs 迁移后的 ~12ms 差异虽大于漂移，但两次测量未做环境隔离（同一台机、同一下午、
  ollama 已连续运行数小时），故只给"量级上更快"，不给精确增益；有机制支撑的只有**总耗时**下降。
- 1.7B 小模型首字快是模型属性的一部分，**不可外推**到大模型。
- **未验证项**：多轮对话、长上下文、并发压测、原生 `tools` 的端到端工具调用链路
  （`_normalize_tool_calls` 有单元测试，但未与真实工具调用模型跑通）。
- `think` 的档位取值（`"low"/"medium"/"high"`）仅做了透传，**未在 ollama 0.34.1 上验证**
  是否被服务端接受。
- §5.4 的"模型加载 1765.5ms"是**一次观测**，冷/热磁盘条件下会变。
- `Ollama嵌入/palm_ollama/workspace/_net.py` 的 `read1()` 修复（旧 `read(n)` 会阻塞到读满
  n 字节，实测首块 478.6ms → 59.6ms）保留在本包内，服务模型文件下载的进度回调与断点续传。

---

## 7. 复现命令

```bash
# 测试套件（需要 httpx + pydantic）
cd D:/P.A.L.M/1_Demo_LLM/LLM内核
"D:/P.A.L.M/1_Demo_LLM/RAG/.bench_venv/Scripts/python.exe" tests/test_ollama_provider.py

# 首字延迟基准（迁移后路径）
cd D:/P.A.L.M/1_Demo_LLM/llm_benchmark
"D:/P.A.L.M/1_Demo_LLM/RAG/.bench_venv/Scripts/python.exe" bench_ollama_native.py --rounds 10 --warmup 1

# 对照：/v1 兼容路径
"D:/P.A.L.M/1_Demo_LLM/RAG/.bench_venv/Scripts/python.exe" bench_ollama.py \
    --rounds 10 --warmup 1 --out-dir results_ollama_spark_v1_recheck

# app 侧桥接自检（应打印 OK + OllamaProvider）
cd D:/P.A.L.M/app
"D:/P.A.L.M/app/engine/.venv/Scripts/python.exe" -c "
import llm
from palm_llm import OllamaProvider
print('OK', llm.OpenAICompatProvider.__name__, OllamaProvider.__name__)"
```

> 本目录下可用的含依赖解释器：`1_Demo_LLM/RAG/.bench_venv/Scripts/python.exe`（httpx 0.28.1、
> pydantic）。`palm_llm` 的 CLI / server 亦可用它跑。

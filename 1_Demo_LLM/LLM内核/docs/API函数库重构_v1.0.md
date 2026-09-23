# LLM 内核 API 函数库重构 v1.0（同功能合并 + 内部件私有化 + 唯一入口）

> 版本：v1.0　｜　日期：2026-09-23　｜　来源：**逐文件实读 + 重构前后 AST 口径对拍 + 248 项单元测试实测 + ollama 实机联调**
> 关联：`LLM内核架构_v1.5.md`（骨架与四通道）、`可观测与异常_v1.0.md`、`回传拆分器字段说明_v1.0.md`、`能力矩阵前置拦截_v1.0.md`、`适配层决策说明_v1.0.md`
> 备份：`.workbuddy/backup/20260923_api_merge/LLM内核/`（51 个 .py，重构前完整快照）

---

## 0. 一句话结论

调用方此前面对的是「**585 个可引用符号 + 8 个可深链的实现模块**」；现在只有
「**一个入口 `palm_llm`（= `palm_llm.api`），37 个明确导出**」。中间那 8 个模块里的
**63 个公开符号**全部退到 `_` 私有路径，**5 组同功能函数从 15 个收敛到 6 个**。

内部件仍然都在、行为一字未改 —— 改的只是**它们还算不算"对外契约"**。

---

## 1. 判据：为什么这样合并

沿用加解密内核那次重构定下的两条判据：

| 判据 | 含义 | 本次落在哪 |
|---|---|---|
| **能用数据表达的差异写进数据** | 同一件事、只是取值/字段不同 → 参数化，不新增函数 | `usage_from(raw, protocol)`、`data_uri(media, default_mime)` |
| **必须用代码表达的差异新增一个薄文件** | 结构级差异（协议骨架）→ 独立文件，不硬塞进数据层 | 四家 provider 类**不合并**（见 §7） |
| 追加判据：**调用方永远连用的两步 → 合成一步** | 分开只会多出一个"可以被传错"的中间值 | `resolve(base_url, model, type_hint)` |
| 追加判据：**同一问题的两个入口 → 合一个** | 调用方不该因为错误来自 HTTP 还是 socket 而去记两个函数名 | `classify_error(...)` |

反面对照：**没有为了减少数字而硬合并**。`feed` / `mark_finish_tool_calls` /
`map_stop_reason` 都是三条通道共用、但各自语义独立的小件，合并只会让"哪种帧算输出"
这类语义藏进参数里 —— 那是把清晰度换成数字，不划算（见 §7）。

---

## 2. 5 组同功能合并（15 个函数 → 6 个）

### 2.1 回传用法归一：4 → 1

| 合并前 | 合并后 | 差异如何表达 |
|---|---|---|
| `usage_from_openai(raw)` | | |
| `usage_from_anthropic(raw)` | **`usage_from(raw, protocol)`** | `protocol ∈ openai / anthropic / gemini / ollama` |
| `usage_from_gemini(raw)` | | 未知值**回落 `openai`**（与 provider 工厂"未知 type 回落 openai_compat"同口径） |
| `usage_from_ollama(obj)` | | |

- 落码：`providers/_telemetry.py`；四个解析体保留为 `_usage_openai` / `_usage_anthropic` /
  `_usage_gemini` / `_usage_ollama`。
- 为什么必须合并：四个入口的**返回形状完全相同**，差异只在"字段名"和"含不含缓存"这两个
  **取值口径**上。拆开唯一的"好处"是调用方可以挑错入口 —— 而挑错的代价是
  **算出一个不报错的错数**（比如把 Anthropic 的 `input_tokens` 再减一次缓存）。
- 新增常量 `PROTOCOLS` 供自检。

### 2.2 多模态 data URI：3 → 1

| 合并前 | 合并后 |
|---|---|
| `data_uri(media, default_mime)` | **`data_uri(media, default_mime=DEFAULT_MIME)`** |
| `image_url(img)` = `data_uri(img, image/png)` | （删） |
| `file_uri(doc)` = `data_uri(doc, octet-stream)` | （删） |

- 三个函数的**函数体逐字一致**，只差一个默认 mime —— 这是最典型的数据级差异。
- 调用方改为显式传 `DEFAULT_FILE_MIME`；两个常量一并导出，避免调用方硬编码 `"image/png"`。
- `split_data_uri`（解析）与 `file_name`（反推显示名）语义不同，**保留**。

### 2.3 两级匹配：2 → 1

| 合并前 | 合并后 |
|---|---|
| `resolve_provider(base_url, type_hint)` | **`resolve(base_url="", model="", type_hint="") → (Profile, ModelRule\|None)`** |
| `resolve_model(profile, model_id)` | |

- 合并理由：调用方**永远**是嵌套调用 `resolve_model(resolve_provider(b, t), m)`。
  分开只多出一个能被传错的中间值。
- `_match_rule(profile, model_id)` 保留为**私有**口子，给"Profile 已经在手上"的场景
  （本模块的二级单测即走它）。
- 未命中一律回落、不报错（一级回落 `generic`，二级回落 Profile 默认）—— 语义未变。

### 2.4 错误分类：2 → 1

| 合并前 | 合并后 |
|---|---|
| `error_for_status(status, message, *, ...)` | **`classify_error(message, *, status=None, exc=None, interrupted=False, ...)`** |
| `error_for_transport(exc, message, *, interrupted=False)` | |

- 两者回答的是**同一个问题**：「这次失败值不值得再试一次」。调用方不该因为错误来自
  HTTP 还是 socket 而去记两个函数名。
- 两条来源**互斥**；同时给时以 `status` 为准（HTTP 层比 socket 层更具体）。
- 关键语义一字未动：`interrupted=True`（**已向调用方产出内容后**才断）一律归
  **不可重试**的 `StreamInterruptedError`，而不是可重试的 `TransportError` ——
  这是防重复生成、防重复计费的那条线，不能被"合并"顺手抹平。

### 2.5 request_id：4 → 2

| 合并前 | 合并后 |
|---|---|
| `new_request_id()` | `_new_request_id()`（私有） |
| `get_request_id()` | **`request_id()`**（读；未设置则生成并落定） |
| `ensure_request_id()` | （并入 `request_id()`） |
| `set_request_id(rid)` | **`set_request_id(rid=None)`** |

- `get` 与 `ensure` 在"已有 id 时"**行为完全一致**，分开只会让调用方在"只读"与
  "读不到就建"之间选错 —— 选错的后果是日志里出现 `-`（排障时关联不上）。
- `new_request_id` 是纯实现件（生成 12 位十六进制），调用方没有理由直接用它，转私有。

---

## 3. 内部件私有化（8 个模块 → `_` 前缀）

| 重构前 | 重构后 | 重构前公开符号数 |
|---|---|---|
| `providers/profiles.py` | `providers/_profiles.py` | 6 |
| `providers/profiles_data.py` | `providers/_profiles_data.py` | 13 |
| `providers/telemetry.py` | `providers/_telemetry.py` | 10 |
| `providers/multimodal.py` | `providers/_multimodal.py` | 8 |
| `providers/capability.py` | `providers/_capability.py` | 2 |
| `providers/tooltext.py` | `providers/_tooltext.py` | 5 |
| `providers/anthropic_wire.py` | `providers/_anthropic_wire.py` | 10 |
| `providers/gemini_wire.py` | `providers/_gemini_wire.py` | 9 |
| | **合计** | **63** |

**硬切**：旧路径**不保留兼容别名**（`import palm_llm.providers.profiles` 现在直接
`ModuleNotFoundError`）。这一条由测试 `tests/test_api_surface.py::LegacyPathTest` 钉住 ——
留着 shim 等于把"内部件可以随手重排"这个唯一好处重新交出去。

**没被私有化的**：`providers/base.py`（`BaseProvider` 是对外契约）、
四家 provider 实现文件（`openai_compat.py` / `anthropic.py` / `ollama.py` / `gemini.py`，
对外是 `cfg.type` 的取值来源，且测试与 `bench/` 直接引用）。

---

## 4. 唯一入口：`palm_llm/api.py`

`palm_llm/__init__.py` 现在只做两件事：**转出 `api.__all__`** + 惰性挂载 `server` 子包。
真正的函数清单与文档在 `api.py`（单一事实来源）。

导出 37 个符号，构成如下 —— **函数只有 12 个**，其余都是数据契约与类型：

| 分类 | 数量 | 内容 |
|---|---|---|
| 版本 / 自述 | 3 | `VERSION`、`describe()`、`protocols()` |
| 数据契约 | 5 | `ProviderConfig`、`Message`、`ModelParameters`、`Tool`、`TurnStats` |
| provider 层 | 8 | 4 个 provider 类、`BaseProvider`、`get_provider_instance`、2 个默认 base_url |
| 调用 | 2 | `stream()`、`complete()` |
| 能力 | 3 | `capabilities_for`、`check_capabilities`、`CapabilityError` |
| 失败分类 | 9 | `classify_error` + 8 个异常类 |
| 重试 | 3 | `RetryPolicy`、`LOW_LATENCY`、`STABLE` |
| 可观测 | 4 | `configure_logging`、`log_event`、`request_id`、`set_request_id` |

### 4.1 本次新增的 4 个符号（都是**真新**，不是同义词）

| 符号 | 作用 | 不新增同义词的说明 |
|---|---|---|
| `protocols()` | 协议键 → provider 类名 | 与工厂**共用** `providers.PROTOCOLS` 同一张表（原先表只存在于工厂函数体内，外部无从查询） |
| `stream(messages, ..., cfg=\|prov=)` | 异步流式调用 | 把"取实例 → 选模型 → 调用"三步收成一次调用 |
| `complete(messages, ..., cfg=\|prov=)` | 一次性调用 | 内部仍走流式，把增量拼成整段后返回 + 统一 stats |
| `describe()` | 版本 / 协议 / 函数 / 数据契约清单 | 供自检、文档生成与 UI 用 |

**刻意没有做的事**：没有给 `get_provider_instance` 加 `provider()` 别名，也没有给
`capabilities_for` 加 `capabilities()` 别名 —— 加同义词正是本次要消灭的东西。

### 4.2 `providers/__init__.py` 同步瘦身

- 协议映射从"工厂函数体内的局部 dict"提为模块级 `PROTOCOLS` 常量 (+`DEFAULT_PROTOCOL`)。
- 移除了原先在此重复转出的**异常层级与重试策略**（`palm_llm.errors` / `palm_llm.retry`
  才是它们的家）；`providers` 包只导出 provider 层的东西。

---

## 5. 硬切清单（本次删掉的旧名，一次性列全）

| 旧名 | 去向 |
|---|---|
| `usage_from_openai` / `usage_from_anthropic` / `usage_from_gemini` / `usage_from_ollama` | `usage_from(raw, protocol)` |
| `image_url` / `file_uri` | `data_uri(media, default_mime)` + 两个 mime 常量 |
| `resolve_provider` / `resolve_model` | `resolve(base_url, model, type_hint)`（Profile 在手上时用私有 `_match_rule`） |
| `error_for_status` / `error_for_transport` | `classify_error(message, *, status=\|exc=)` |
| `new_request_id` / `get_request_id` / `ensure_request_id` | `_new_request_id()`（私有）/ `request_id()` |
| `palm_llm.providers.{profiles, profiles_data, telemetry, multimodal, capability, tooltext, anthropic_wire, gemini_wire}` | 同名前加 `_` |
| `benchmark.py::resolve_provider(args)`（CLI 局部函数，与内核同名易混） | 改名 `provider_from_args(args)` |

全部由 `tests/test_api_surface.py::EntryPointTest` 的 `REMOVED` / `REMOVED_MODULES`
两张清单逐项断言"已消失"。

---

## 6. 验证证据

### 6.1 测试

| 项 | 重构前 | 重构后 |
|---|---|---|
| unittest（13 模块） | 226 通过 | **248 通过**（+22 项 API 面契约） |
| `tests/test_ollama_provider.py`（模块级脚本 + 实机联调） | ALL PASS | **ALL PASS** |
| 编译 | — | `compileall palm_llm tests examples bench` 无错 |

新增的 `tests/test_api_surface.py` 覆盖五件事：

1. `palm_llm.__all__` 与 `palm_llm.api.__all__` **逐字一致**；
2. 13 个旧函数名 + 8 个旧模块路径**确实消失**；
3. 5 组合并后的行为**逐一等价**（含"未知 protocol 回落 openai"）；
4. 新动词 `stream()` / `complete()` 走 `httpx.MockTransport` **真跑通**（含
   `cfg.default_model` 兜底、缺 cfg 抛 `NotConfiguredError`、复用已有实例）；
5. `describe()` / `protocols()` 与实际导出**不脱节**。

### 6.2 端到端

- `examples/basic_usage.py` 现在**无需 Key、无需联网**即可跑完（`MockTransport` 回放），
  实测输出：`stream()` 增量到达（思考帧 / 正文帧 / done+stats），`complete()` 拼出
  `"你好，世界。"` 并给出 `input_tokens=2 / cache_read_tokens=6 / output_tokens=4`。
- `palm_llm.server.chat` / `palm_llm.cli.*` / `bench/gateway/clients.py` 全部导入通过
  （`server/api.py` 因本地 venv 无 `fastapi` 未导入，与本次改动无关）。
- 核心链路冒烟：`get_provider_instance` → `capabilities_for` 正常。

### 6.3 重构前后的 AST 口径对拍

| 口径 | 重构前 | 重构后 |
|---|---|---|
| `palm_llm/` 下 .py 文件数 | 32 | 33（+`api.py`） |
| 全包可引用符号（无 `_` 前缀） | 585 | 577 |
| 声明 `__all__` 合计 | 134 | 132 |
| 可由旧深链到达的实现件符号 | 63 个（8 个模块） | **0**（旧路径已 import 失败） |
| 顶层包导出 | 25 | **37**（函数 12 + 契约/类型 25） |

⚠️ **诚实披露**：顶层导出**从 25 涨到 37**，不是缩小。原因是原先有些东西"能 import 但
没写进 `__all__`"（4 个 provider 类、`TurnStats`、`check_capabilities`、`log_event`、
`AnthropicProvider`… ），本次把它们**显式化**了。本次真正缩小的是：
**同功能重复函数 15 → 6**、**可深链的实现面 63 → 0**。
"导出更多但都是明确契约"比"导出更少但边界靠猜"更符合函数库的定义。

---

## 7. 明确**没有**合并的东西（以及理由）

1. **四家 provider 类不合并**。协议差异是**结构级**的（system 外提 / tool→tool_result
   成对 / 块级流式状态机 / 思考签名），翻译表盖不住。判据见《适配层决策说明_v1.0》：*
   "必须用代码表达的差异新增一个薄文件，不要为看起来统一把第二类硬塞进第一类。"*
2. **`feed` / `mark_finish_tool_calls` / `map_stop_reason` 保留**。三条通道共用，但各自
   语义独立（"哪种帧算输出" / "有工具调用时归一 finish_reason" / "停止原因词典"）。
   合并的唯一办法是塞参数，等于把语义藏起来。
3. **`usage` 与 `stats` 双回传保留**。`usage` 保厂商原样是**向后兼容契约**（有调用方已
   依赖某家独有键），`stats` 是归一字段。删 `usage` 会打断既有调用方。
4. **`_match_rule` 保留**为私有二级入口，给"Profile 已经在手上"的场景。
5. **历史文档不改写**：`LLM内核架构_v1.0`–`v1.4`、`供应商协议差异与特化通道方案_v1.0/v1.1`
   保留当时形态（多版本管理而非时间对照）；**当前**文档的旧模块路径/旧函数名已就地修正，
   并在文首加了指向本文的指引。

---

## 8. 时间线注释

```
2026-09-23  内核 v1.5：四通道（openai_compat / anthropic / ollama / gemini）+ 能力闸门
2026-09-23  可观测与异常 v1.0：类型化错误 + 有界重试 + request_id 贯通
2026-09-23  工具路径 F1–F6 全修 + 文本工具调用降级（tooltext）
2026-09-23  对外 API 引脚图（芯片引脚式页面）交付，暴露"符号多且入口散"
2026-09-23  ▶ 本次：同功能合并 15→6、内部件私有化 63→0 可深链、唯一入口 api.py（37 导出）
```

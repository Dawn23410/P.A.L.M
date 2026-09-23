# palm_llm 内核架构 v1.5（四通道 + 能力闸门 + 对照实测版）

> 版本：v1.5　｜　日期：2026-09-23　｜　来源：**逐文件实读 + 180 项单元测试实测 + ollama 实机联调 + 网关控制变量对照实跑**
> 取代：`LLM内核架构_v1.4.md`（v1.4 及更早版本保留作历史版本）
> 关联：`适配层决策说明_v1.0.md`、`Anthropic原生通道_v1.0.md`、`回传拆分器字段说明_v1.0.md`、
> 　　　`各供应商各模型支持能力_v2.0.md`、`同功能异字段差异矩阵_v1.0.md`、`各模型思考强度调研_v1.0.md`、
> 　　　`思考块回传契约_v1.0.md`、`工具原生支持审计_v1.1.md`、`文本工具调用降级_v1.0.md`、
> 　　　**`能力矩阵前置拦截_v1.0.md`（新）**、**`网关对照实验_v1.0.md`（新）**

> **v1.5 增补（2026-09-23，原文保留）**：三条缺口关闭 —— ① **Gemini 原生通道**落地
> （`gemini.py` + `gemini_wire.py`）；② **能力矩阵接进内核**（`capability.py`，发请求前硬拦）；
> ③ **规则数据按 v2.0 §11 复审修正**，并补齐各家的视觉/文档字段。
> 另新增**与开源实现的控制变量对照实测**（`bench/gateway/`）。测试数 115 → **180**。

---

## 0. v1.4 → v1.5 修订

| 事项 | v1.4 | v1.5 |
|---|---|---|
| 协议通道 | 3（openai_compat / anthropic / ollama） | **4**（+ **gemini 原生 `generateContent`**） |
| 能力矩阵 | 只是文档，内核不校验 | **`capability.py` 前置拦截**：发请求前拦视觉/文档/体积违规 |
| 文档附件 | `Message` 只有 `images` | **新增 `Message.files`**，三家协议各自渲染为原生文档块 |
| 规则数据 | 未复审 | 按 v2.0 §11 修正 + 补 `supports_vision` / `doc_mimes` / `reject_documents` |
| `finish_reason` | 各家原生值不一致，工具可能静默不执行 | **统一归一为 `tool_calls`**（`mark_finish_tool_calls`） |
| 性能证据 | 无 | **控制变量对照实测**：净开销 ≈ +0.8 ms/次，见 `网关对照实验_v1.0.md` |
| 新增文件 | `tooltext.py` | `providers/capability.py`、`providers/gemini.py`、`providers/gemini_wire.py` |
| 代码量（`palm_llm` 包） | 26 文件 / 5607 行 | **29 文件 / 6918 行** |
| 测试 | 115 + ollama | **180 + ollama 联调（13 例）** |

---

## 1. 四种协议通道

| `cfg.type` | 端点 | 为什么单独存在 |
|---|---|---|
| `openai_compat` | `{base}/chat/completions` | 国内外绝大多数厂商与网关；**自带三级容错降级** |
| `anthropic` | `{base}/v1/messages` | system 外提、`max_tokens` 必填、块级 SSE、原生缓存 token、`output_config.effort` |
| `ollama` / `ollama_native` | `{base}/api/chat` | 原生 `think` 一等参数、`message.thinking`、分段耗时、消息字段与 OpenAI 不同 |
| **`gemini` / `google`** | `{base}/v1beta/models/{m}:generateContent` | 只有 user/model 两个角色、内容一律 `parts[]`、system 走 `systemInstruction`、思考参数 **3 系列 `thinkingLevel` 与 2.5 系列 `thinkingBudget` 两套并存（同传即 400）**、鉴权 `x-goog-api-key`、**无 `[DONE]` 收尾** |

未实现的 type 一律回落 `openai_compat`（容错，非静默失败）。

四通道共享 `base.py`：HTTP 客户端复用、首字节短超时、`to_chat_message` 归一、
`normalize_tool_calls` 归一、`image_to_b64`。

### 1.1 Gemini 通道的三个独立坑（`gemini_wire.py` 注释里逐条写明）

1. **两套思考 API 互斥**：`thinkingLevel`（3.x）与 `thinkingBudget`（2.5.x）同传报 400；
   档位不能用「超范围取最高档」的通用策略 —— 那会把 `minimal` 变成满档，
   故用**最近邻夹取**（`minimal` → `low`，而非 `high`）。
2. **没有 `[DONE]`**：连接关闭即收尾，不能因为等哨兵而丢收尾帧。
3. **`thoughtSignature` 回传**：模型返回的签名要随 parts 原样带回（不带 tools 时不必），
   且我们自己合成的 `fc_<n>` 假 id **绝不回传**（服务端认不出来）。

---

## 2. 两级匹配（沿用 v1.2）

```
请求（base_url + cfg.type + model）
   ├─【一级】cfg.type ＞ 端点/域名特征 ＞ generic   →  Profile（骨架层）
   └─【二级】model id 正则 fullmatch，priority 最大 →  ModelRule（模型层）
            ├─ 命中   → 非空字段合并 → apply_rule
            └─ 未命中 → 回落 Profile 默认，**不报错**
```

`apply_rule` 的步骤顺序仍是硬约束（读意图 → 纠意图 → 夹档位 → 剔禁参 → 写目标
→ **最后**套 fixed_params → 套 vendor_params）。详见 v1.2 §2。

**v1.5 新增两条数据通道**（都在同一份 `ModelRule` 上，不新造机制）：

- `reject_documents`：该模型是否**一个文档都不吃**（与 `doc_mimes`「能吃哪些」分工互补；
  「一个都不吃」无法用空元组表达 —— 空元组在合并语义里等于「未声明」）。
- `thinking_api`：协议自带的思考 API 形态（`level` / `budget` / `none`）。
  **单独成列而不是靠 `forbid_params` 反推** —— 反推是隐式耦合，改一处禁参会静默改掉判定。

---

## 3. 回传拆分器（v1.3 引入）

```
provider.complete(...)
   └─ 事件流： content / reasoning / tool_call_delta / tool_calls
   └─ 收尾帧： {"done": true, "usage": <厂商原始>, "stats": <统一字段>}
```

`usage` 保留原始字段（向后兼容）；`stats` 是跨协议归一的稳定字段，**新代码只读 `stats`**。

统一口径：

```
input_tokens = 非缓存输入
total_tokens = input + cache_read + cache_write + output
```

v1.5 补了两个归一入口：

- `usage_from_gemini`：`promptTokenCount` **含缓存命中**，要减掉 `cachedContentTokenCount`
  才是非缓存输入（官方原文口径）；思考 token 单列在 `thoughtsTokenCount`。
- `mark_finish_tool_calls(stats)`：有工具调用时把 `finish_reason` 归为 `tool_calls`，
  原值存进 `extra.finish_reason_vendor`。**不归一的后果是工具静默不执行** ——
  调用方按 `finish_reason` 分支是常态，而 Ollama 在工具调用时仍报 `stop`、Gemini 报 `STOP`。

计时拆四段：`ttack_ms` / `ttft_ms` / `ttfa_ms` / `total_ms`，派生 `tpot_ms` / `ntpot_ms` /
`itl_p50` / `itl_p90` / `tps` / `tps_total` / `cache_hit_rate`。

---

## 4. 工具路径（v1.4 补全）

四个环节与四条通道的落点：

| 环节 | openai_compat | anthropic | ollama | gemini |
|---|---|---|---|---|
| 声明 | `Tool.normalize` → `tools` | `parameters` → `input_schema` | `Tool.normalize` → `tools` | → `functionDeclarations` |
| 选择 | `tool_choice` + `parallel_tool_calls` 透传 | `required`→`any`；具名→`{"type":"tool"}`；**互斥时降级 + 记账** | **不下发**（原生无此字段） | `ANY` / `NONE` / `AUTO` + `allowedFunctionNames`；**无并行开关**（记账不假装） |
| 流式分片 | 按 `index` 累加，拿到名字即下发 | `content_block_start` 即下发 | 原生一次给完整调用 | `functionCall` part 即下发 |
| 结果回填 | `role="tool"` + `tool_call_id` + `name` | → user + `tool_result`（含 `is_error`） | `tool_name`（无 id）、`arguments` 转**对象** | → `functionResponse`（带 `error` 标志） |
| 文本降级 | ✅ `tooltext` | ✅ `tooltext` | ✅ `tooltext`（★ 收尾帧也必须过过滤器） | ✅ `tooltext`（★ 也吃 `functionDeclarations` 形状） |

### 4.1 原生优先，文本兜底

```
端点实现原生 function calling  →  走 tool_calls 字段（权威通道）
端点不实现（自定义 GGUF / 网关）→  模型把调用写进正文 → tooltext 按五族约定抠出
```

三条安全阀（未声明工具 / name 不在声明集 / 区域非 JSON → 一律原文放行）与流式保真
（扣尾不丢字）见 `文本工具调用降级_v1.0.md`。
v1.5 修了安全阀 1 的一个真 bug：`declared_names` 原先只认两种声明形状，
**不认识 Gemini 的 `functionDeclarations`** → 导致整条文本降级被静默关闭。

### 4.2 一个反直觉的约束：文本降级必须是**纯函数**

`tooltext.text_tool_events(flt, ev)` 是纯函数就地过滤，**不是**一层异步生成器包装。
理由：各 provider 的事件循环都受「调用方 `break` 早退时不重复 `aclose`」约束，
多嵌一层会让已修复的重入问题回来。非流式路径用 `filter_events(events, names)`
复用**同一份**路由逻辑，不做第二套实现。

---

## 5. 能力矩阵前置拦截（v1.5 新增）

```
调用方 ── Message(images / files) ──> [ capability.check_capabilities ] ──> 组 payload ──> HTTP
                                              │
                                       已知不支持 → CapabilityError（零网络往返）
```

三条设计铁律（详见 `能力矩阵前置拦截_v1.0.md`）：

1. **只拦「已知不支持」**。`generic` / ollama 档位模型名不固定，`capabilities_known=False`，
   一律放行并记一条 `capability_unknown` —— 硬拦会把本机 `llava` 这类合法用法打死。
2. **只看 `Message`，不看 payload**。payload 是各家组装后的产物，形态已经漂移。
3. **报错要能照着改**：第几条消息、什么类型、超了多少、支持什么、该换什么、命中哪条规则。

文档附件在三家的落地：OpenAI `{"type":"file","file":{"filename","file_data"}}`（**Chat
Completions 官方只认 `.pdf`**）、Anthropic `{"type":"document","source":{...}}`、
Gemini 与图片同构的 `inlineData`。

---

## 6. 目录结构（`palm_llm` 包，29 文件 / 6918 行）

```
palm_llm/
├── models.py                 数据模型（Message 含 images + files / Tool / ModelParameters / ProviderConfig）
├── providers/
│   ├── base.py               Provider 基类 + 事件契约 + 共享件（含 normalize_tool_calls）
│   ├── openai_compat.py      通用通道 + 三级容错降级
│   ├── anthropic.py          Anthropic 原生通道（传输 + 思考配置 + 工具选择降级）
│   ├── anthropic_wire.py     内核 ↔ Anthropic 线格式双向转换
│   ├── ollama.py             Ollama 原生通道（think 一等参数、tool_name 回填）
│   ├── gemini.py             ★ v1.5：Gemini 原生传输（thinkingConfig 两套 API + 夹取）
│   ├── gemini_wire.py        ★ v1.5：内核 ↔ generateContent 线格式双向转换
│   ├── capability.py         ★ v1.5：能力矩阵前置拦截（视觉 / 文档 / 体积）
│   ├── tooltext.py           正文文本工具调用降级（五族形态 + 三条安全阀）
│   ├── profiles.py           两级匹配引擎
│   ├── profiles_data.py      10 家 Profile 规则数据（含视觉/文档能力字段）
│   ├── telemetry.py          回传拆分器（字段 + 口径归一 + finish_reason 归一）
│   └── multimodal.py         多模态内容块（openai / anthropic；含文档块）
├── server/                   FastAPI 入口、对话调度、配置、存储、指标
└── cli/                      命令行、TUI、基准
```

四条 `complete()` 统一事件契约见 `providers/base.py` 文档字符串。

---

## 7. 测试状态（实测）

| 套件 | 结果 |
|---|---|
| `tests/test_profiles_matching.py` | **18/18 OK** |
| `tests/test_openai_compat_degrade.py` | **11/11 OK** |
| `tests/test_telemetry.py` | **19/19 OK**（v1.5 +6） |
| `tests/test_anthropic_provider.py` | **15/15 OK** |
| `tests/test_reasoning_echo.py` | **18/18 OK** |
| `tests/test_tool_text_fallback.py` | **40/40 OK** |
| `tests/test_gemini_provider.py` | **★ 32/32 OK**（v1.5 新增） |
| `tests/test_capability.py` | **★ 27/27 OK**（v1.5 新增） |
| `tests/test_ollama_provider.py` | **ALL PASS**（13 例，含实机联调） |
| **unittest 合计** | **180 OK** |

运行（`.bench_venv` 无 pytest，一律用 unittest）：

```
RAG/.bench_venv/Scripts/python.exe -m unittest discover -s tests -t tests -p "test_*.py"
# ollama 套件是模块级函数，unittest 采集不到，须直接跑：
RAG/.bench_venv/Scripts/python.exe tests/test_ollama_provider.py
```

**对照实验**（WSL2 + Docker，单次会话内跑完）：

```
cd bench/gateway
RESDIR=results_zero bash run_bench.sh 500 50          # 零延迟：纯开销
RESDIR=results_load ACK_MS=300 CHUNK_MS=5 MAXTOK=32 bash run_bench.sh 80 10   # 拟真
python3 report.py --zero results_zero --load results_load --out ../../docs/网关对照实验_v1.0.md
```

实测结论（详细数据见 `网关对照实验_v1.0.md`）：本内核净开销 **+0.83 ms/次**，
同语言四个实现里最轻（LiteLLM +18.72 ms、OpenAI SDK +5.85 ms）；
跨语言参照组 Bifrost +2.73 ms、Portkey +30.45 ms（**不与内核并列排名**）。
拟真延迟（477 ms 回合）下，除 Portkey 外**所有差异被淹没**。

---

## 8. 现状缺口（诚实清单，按优先级）

1. ⚠️ **工具执行环不在内核**：内核只负责下发 `tool_calls` 与接收回填，**谁执行、谁构造
   `role="tool"` 消息在应用层**。因此多轮工具闭环只做了字段级验证，端到端未跑过。
2. ⚠️ **文本降级仍未实机验证**：需要「模板不含工具解析」的自定义 GGUF；本地两个模型都已被
   ollama 模板处理。保真性目前由 40 项用例保证，**非实机保证**。
3. ⚠️ **除 ollama 外无实机验证**：Anthropic / Gemini / openai_compat 通道均为 MockTransport
   用例，未对真实端点发过请求（无可用 Key）。Gemini 的载荷形状有官方文档逐项对照 +
   32 项用例，但**没有真机回包**这一层证据。
4. ⚠️ **能力矩阵的数据有覆盖盲区**（已如实标在数据里，不在代码里猜）：
   - Doubao「文档理解」仅标 Supported，**扩展名/上限未查到** → 不设闸门，只记账；
   - Kimi 文档走独立 `file-extract` 通道，**大小上限未查到**；
   - GLM-5.3-Flash 的文件体积上限**未查到**，暂沿用 50 MB 作保守闸门（注释已标「非官方值」）；
   - MiniMax / xAI Grok 官方文档抓取失败，**全字段未查到** → 未建 Profile。
5. ⚠️ **能力闸门是「发请求前」的静态判断，不是服务端权威**：厂商会静默改限制；
   闸门放行 ≠ 服务端一定接受（反之亦然）。它省的是白跑一趟与模糊 400，不是替代错误处理。
6. ⚠️ **对照实验的量化结论有前提**：回环、无 TLS、并发 1、host 网络（见该文第七节）。
   净开销数字应读作**下界**，不能外推到高并发或跨区链路。
7. ⚠️ **既有超规范债（非本次引入）**：`palm_llm/cli/chat.py` 598 行（限 500）、
   `handle_command` 127 行、`cli/chat_tui.py::send` 109 行、`server/chat.py::run_chat` 107 行（限 50）。
   本次新增/改动的文件全部合规（最大 `profiles_data.py` 435 行）。
8. **内核仍不接主工程**：`app/` 下零 `palm_llm` 引用。
9. **内核不受 git 保护**（`.gitignore` 忽略 `1_Demo_LLM/`），删除前必须先备份。

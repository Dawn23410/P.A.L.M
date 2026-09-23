# palm_llm 内核架构 v1.4（三通道 + 工具全路径版）

> 版本：v1.4　｜　日期：2026-09-23　｜　来源：**逐文件实读 + 115 项单元测试实测 + ollama 实机联调**
> 取代：`LLM内核架构_v1.3.md`（v1.3/v1.2/v1.1/v1.0 保留作历史版本）
> 关联：`适配层决策说明_v1.0.md`、`Anthropic原生通道_v1.0.md`、`回传拆分器字段说明_v1.0.md`、
> 　　　`各供应商各模型支持能力_v2.0.md`、`同功能异字段差异矩阵_v1.0.md`、`各模型思考强度调研_v1.0.md`、
> 　　　`思考块回传契约_v1.0.md`、`工具原生支持审计_v1.1.md`、`文本工具调用降级_v1.0.md`

> **v1.4 增补（2026-09-23，原文保留）**：工具路径四面打通 —— 声明 / 选择 / 回传 / **结果回填**，
> 并新增**正文文本工具调用降级**（无原生 `tool_calls` 时从正文抠调用）。测试数 75 → **115**。
> 新增文件 `providers/tooltext.py`。问题清单与修复见 `工具原生支持审计_v1.1.md`。

---

## 0. v1.3 → v1.4 修订

| 事项 | v1.3 | v1.4 |
|---|---|---|
| 工具路径 | 声明 / 选择 / 回传已通；**结果回填与边角契约 5 条待办** | **5 条全修**（F1–F5）+ 1 条集成缺陷（F6） |
| 无原生 `tool_calls` 时 | 正文里的调用**静默丢弃** | **新增文本降级**：按五族约定从正文抠出调用 |
| 新增文件 | `telemetry.py` / `anthropic.py` / `anthropic_wire.py` | `providers/tooltext.py` |
| 代码量（`palm_llm` 包） | 25 文件 / 4861 行 | **26 文件 / 5607 行** |
| 测试 | 57 + ollama | **115 + ollama 联调** |

---

## 1. 三种协议通道

| `cfg.type` | 端点 | 为什么单独存在 |
|---|---|---|
| `openai_compat` | `{base}/chat/completions` | 国内外绝大多数厂商与网关；**自带三级容错降级** |
| `anthropic` | `{base}/v1/messages` | system 外提、`max_tokens` 必填、块级 SSE、原生缓存 token、`output_config.effort` |
| `ollama` / `ollama_native` | `{base}/api/chat` | 原生 `think` 一等参数、`message.thinking`、分段耗时、消息字段与 OpenAI 不同 |

未实现的 type 一律回落 `openai_compat`（容错，非静默失败）。
**Gemini 原生（`generateContent`）尚未实现**，目前只能走兼容端点。

三通道共享 `base.py`：HTTP 客户端复用、首字节短超时、`to_chat_message` 归一、
**`normalize_tool_calls` 归一**（v1.4 上提，三通道共用一份）、`image_to_b64`。

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

Anthropic 原生通道复用同一份规则做「思考开关 / 档位」决策，只把结果翻成原生形状
（`thinking` 顶层 + `output_config.effort`）—— **同一份厂商知识不写两遍**。
v1.4 新增的 `ModelRule.reject_forced_tool` 也走这条数据通道（Fable5.1 / Mythos5.1 拒强制工具选择）。

---

## 3. 回传拆分器（v1.3 引入）

```
provider.complete(...)
   └─ 事件流： content / reasoning / tool_call_delta / tool_calls
   └─ 收尾帧： {"done": true, "usage": <厂商原始>, "stats": <统一字段>}
```

`usage` 保留原始字段（向后兼容，调用方已依赖某家独有键不会被打断）；
`stats` 是跨协议归一的稳定字段，**新代码只读 `stats`**。

统一口径：

```
input_tokens = 非缓存输入
total_tokens = input + cache_read + cache_write + output
```

计时拆四段：`ttack_ms`（首响应头，纯网络/排队）、`ttft_ms`（首帧，含思考）、
`ttfa_ms`（首**正文**帧）、`total_ms`。派生 `tpot_ms` / `ntpot_ms` /
`itl_p50` / `itl_p90` / `tps`（解码速度）/ `tps_total`（端到端速度）/ `cache_hit_rate`。

字段全表与三个口径坑见 `回传拆分器字段说明_v1.0.md`。

---

## 4. 工具路径（v1.4 补全）

四个环节与三条通道的落点：

| 环节 | openai_compat | anthropic | ollama |
|---|---|---|---|
| 声明 | `Tool.normalize` → `tools` | `parameters` → `input_schema` | `Tool.normalize` → `tools` |
| 选择 | `tool_choice` + `parallel_tool_calls` 透传 | `required`→`any`；具名→`{"type":"tool"}`；并行并入 `disable_parallel_tool_use`；**互斥时降级 + 记账** | **不下发**（原生无此字段） |
| 流式分片 | 按 `index` 累加，拿到名字即下发 | `content_block_start` 即下发 | 原生一次给完整调用 |
| 结果回填 | `role="tool"` + `tool_call_id` + `name` | → user + `tool_result`（含 `is_error`） | **`tool_name`**（无 `tool_call_id`）、`arguments` 转**对象** |
| **文本降级** | ✅ `tooltext` | ✅ `tooltext` | ✅ `tooltext`（★ 收尾帧也必须过过滤器） |

### 4.1 原生优先，文本兜底

```
端点实现原生 function calling  →  走 tool_calls 字段（权威通道）
端点不实现（自定义 GGUF / 网关）→  模型把调用写进正文 → tooltext 按五族约定抠出
```

三条安全阀（未声明工具 / name 不在声明集 / 区域非 JSON → 一律原文放行）与流式保真
（扣尾不丢字）见 `文本工具调用降级_v1.0.md`。

### 4.2 一个反直觉的约束：文本降级必须是**纯函数**

`tooltext.text_tool_events(flt, ev)` 是纯函数就地过滤，**不是**一层异步生成器包装。
理由：三个 provider 的事件循环都受"调用方 `break` 早退时不重复 `aclose`"约束
（ollama 模块文档「单生成器约定」一节），多嵌一层会让已修复的重入问题回来。
非流式路径用 `filter_events(events, names)` 复用**同一份**路由逻辑，不做第二套实现。

---

## 5. 目录结构（`palm_llm` 包，26 文件 / 5607 行）

```
palm_llm/
├── models.py                 数据模型（Message / Tool / ModelParameters / ProviderConfig）
├── providers/
│   ├── base.py               Provider 基类 + 事件契约 + 共享件（含 normalize_tool_calls）
│   ├── openai_compat.py      通用通道 + 三级容错降级
│   ├── anthropic.py          Anthropic 原生通道（传输 + 思考配置 + 工具选择降级）
│   ├── anthropic_wire.py     内核 ↔ 原生线格式双向转换
│   ├── ollama.py             Ollama 原生通道（think 一等参数、tool_name 回填）
│   ├── tooltext.py           ★ v1.4 新增：正文文本工具调用降级（五族形态 + 三条安全阀）
│   ├── profiles.py           两级匹配引擎
│   ├── profiles_data.py      10 家 Profile 规则数据
│   ├── telemetry.py          回传拆分器（字段 + 口径归一）
│   └── multimodal.py         多模态内容块（openai / anthropic 两种模式）
├── server/                   FastAPI 入口、对话调度、配置、存储、指标
└── cli/                      命令行、TUI、基准
```

三条 `complete()` 统一事件契约见 `providers/base.py` 文档字符串。

---

## 6. 测试状态（实测）

| 套件 | 结果 |
|---|---|
| `tests/test_profiles_matching.py` | **18/18 OK** |
| `tests/test_openai_compat_degrade.py` | **11/11 OK** |
| `tests/test_telemetry.py` | **13/13 OK** |
| `tests/test_anthropic_provider.py` | **15/15 OK** |
| `tests/test_reasoning_echo.py` | **18/18 OK** |
| `tests/test_tool_text_fallback.py` | **★ 40/40 OK**（v1.4 新增） |
| `tests/test_ollama_provider.py` | **ALL PASS**（含实机联调） |
| **合计** | **115 OK** |

运行（`.bench_venv` 无 pytest，一律用 unittest）：

```
RAG/.bench_venv/Scripts/python.exe -m unittest discover -s tests -t tests -p "test_*.py"
# ollama 套件是模块级函数，unittest 采集不到，须直接跑：
RAG/.bench_venv/Scripts/python.exe tests/test_ollama_provider.py
```

---

## 7. 现状缺口（诚实清单，按优先级）

1. ✅ **工具路径五条问题已全修（原缺口，2026-09-23 关闭）**：F1 ollama 回填字段名 / F2 非流式
   归一 / F3 Anthropic 强制选择 × 手工思考 / F4 ollama 无据下发 `tool_choice` / F5 缺三个字段；
   另修 F6 ollama 流式收尾帧绕过工具过滤器。见 `工具原生支持审计_v1.1.md`。
2. ⚠️ **工具执行环不在内核**：内核只负责下发 `tool_calls` 与接收回填，**谁执行、谁构造
   `role="tool"` 消息在应用层**。因此 F1 的"多轮工具闭环"只做了字段级验证，端到端未跑过。
3. ⚠️ **文本降级未实机验证**：需要"模板不含工具解析"的自定义 GGUF；本地两个模型都已被
   ollama 模板处理。保真性目前由 40 项用例保证，非实机保证。见 `文本工具调用降级_v1.0.md` §八。
4. **Gemini 原生通道未实现**；`multimodal.py` 也只有 openai / anthropic 两种模式，
   没有 Gemini 的 `inlineData` / `fileData`。
5. **能力矩阵未接进内核**：`各供应商各模型支持能力_v2.0.md` 是文档，
   `Profile.supports_vision` / `doc_mimes` / `max_file_mb` 只有部分家填了值，
   内核**不会**在传图给不支持视觉的模型时提前拦截。
6. **规则数据待复审**：调研发现模型名已变更/下线（`deepseek-v4-flash` → `deepseek-flash`、
   `kimi-k2.5` 下线、Claude `opus-4-5` 不在在售阵容）。差异清单见 v2.0 §11。
7. **除 ollama 外无实机验证**：Anthropic / openai_compat 通道均为 MockTransport 用例，
   未对真实端点发过请求（无可用 Key）。F3 因此只有官方明文 + 用例支撑。
8. **既有超规范债（非本次引入）**：`palm_llm/cli/chat.py` 598 行（限 500）、
   `handle_command` 127 行、`cli/chat_tui.py::send` 109 行、`server/chat.py::run_chat` 107 行（限 50）。
   `tooltext.py`（≈340 行）与本次改动的文件全部合规。
9. **内核仍不接主工程**：`app/` 下零 `palm_llm` 引用。
10. **内核不受 git 保护**（`.gitignore` 忽略 `1_Demo_LLM/`），删除前必须先备份。

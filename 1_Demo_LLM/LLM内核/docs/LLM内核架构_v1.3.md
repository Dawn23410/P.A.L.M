# palm_llm 内核架构 v1.3（三通道 + 回传归一版）

> 版本：v1.3　｜　日期：2026-09-23　｜　来源：**逐文件实读 + 57 项单元测试实测 + ollama 实机联调**
> 取代：`LLM内核架构_v1.2.md`（v1.2/v1.1/v1.0 保留作历史版本）
> 关联：`适配层决策说明_v1.0.md`、`Anthropic原生通道_v1.0.md`、`回传拆分器字段说明_v1.0.md`、
> 　　　`各供应商各模型支持能力_v2.0.md`、`同功能异字段差异矩阵_v1.0.md`、`各模型思考强度调研_v1.0.md`、
> 　　　`思考块回传契约_v1.0.md`

> **v1.3 增补（2026-09-23，原文保留）**：补上跨通道的**思考块回传**能力（原 §6.1 缺口已关闭），
> 测试数 57 → **75**。§6.1 已就地标注；新增内容以 `思考块回传契约_v1.0.md` 为准。

---

## 0. v1.2 → v1.3 修订

| 事项 | v1.2 | v1.3 |
|---|---|---|
| 协议通道 | 2 条（openai_compat / ollama） | **3 条**（+ Anthropic 原生 `/v1/messages`） |
| 回传数据 | 厂商 `usage` 原样透传 | **新增回传拆分器**，`done` 帧携带归一后的 `stats` |
| 新增文件 | `profiles.py` / `profiles_data.py` | `telemetry.py`、`anthropic.py`、`anthropic_wire.py` |
| 代码量（`palm_llm` 包） | 22 文件 / 3873 行 | **25 文件 / 4861 行** |
| 测试 | 28 + ollama | **57 + ollama 联调** |

---

## 1. 三种协议通道

| `cfg.type` | 端点 | 为什么单独存在 |
|---|---|---|
| `openai_compat` | `{base}/chat/completions` | 国内外绝大多数厂商与网关；**自带三级容错降级** |
| `anthropic` | `{base}/v1/messages` | system 外提、`max_tokens` 必填、块级 SSE、原生缓存 token、`output_config.effort` |
| `ollama` / `ollama_native` | `{base}/api/chat` | 原生 `think` 一等参数、`message.thinking`、分段耗时 |

未实现的 type 一律回落 `openai_compat`（容错，非静默失败）。
**Gemini 原生（`generateContent`）尚未实现**，目前只能走兼容端点。

三通道共享 `base.py`：HTTP 客户端复用、首字节短超时、`to_chat_message` 归一、`image_to_b64`。

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

---

## 3. 回传拆分器（本次新增）

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

## 4. 目录结构（`palm_llm` 包，25 文件 / 4861 行）

```
palm_llm/
├── models.py                 数据模型（Message / Tool / ModelParameters / ProviderConfig）
├── providers/
│   ├── base.py               Provider 基类 + 事件契约 + 共享件
│   ├── openai_compat.py      通用通道 + 三级容错降级
│   ├── anthropic.py          Anthropic 原生通道（传输 + 思考配置）
│   ├── anthropic_wire.py     内核 ↔ 原生线格式双向转换
│   ├── ollama.py             Ollama 原生通道
│   ├── profiles.py           两级匹配引擎
│   ├── profiles_data.py      10 家 Profile 规则数据
│   ├── telemetry.py          回传拆分器（字段 + 口径归一）
│   └── multimodal.py         多模态内容块（openai / anthropic 两种模式）
├── server/                   FastAPI 入口、对话调度、配置、存储、指标
└── cli/                      命令行、TUI、基准
```

三条 `complete()` 统一事件契约见 `providers/base.py` 文档字符串。

---

## 5. 测试状态（实测）

| 套件 | 结果 |
|---|---|
| `tests/test_profiles_matching.py` | **18/18 OK** |
| `tests/test_openai_compat_degrade.py` | **11/11 OK** |
| `tests/test_telemetry.py` | **13/13 OK** |
| `tests/test_anthropic_provider.py` | **15/15 OK** |
| `tests/test_ollama_provider.py` | **ALL PASS**（含实机联调） |

运行（`.bench_venv` 无 pytest，一律用 unittest）：

```
RAG/.bench_venv/Scripts/python.exe -m unittest \
  tests.test_profiles_matching tests.test_openai_compat_degrade \
  tests.test_telemetry tests.test_anthropic_provider
# ollama 套件是模块级函数，须直接跑：
RAG/.bench_venv/Scripts/python.exe tests/test_ollama_provider.py
```

---

## 6. 现状缺口（诚实清单，按优先级）

1. ✅ **推理块回传已补（原缺口，2026-09-23 关闭）**：`Message` 增 `reasoning` 与
   `reasoning_echo`，`server.Message.to_kernel()` 与 `server.chat._replay` 改为整条搬运，
   `Profile.needs_reasoning_echo` / `ModelRule.needs_reasoning_echo` 落地为数据。
   OpenAI 兼容通道按 Profile 决定出站 `reasoning_content` 有无；Anthropic 通道
   响应侧产出 `stats.extra.native_blocks`、请求侧原样复活（仅本轮带 tools 时回传）。
   契约分级与官方出处见 `docs/思考块回传契约_v1.0.md`。**实机未验证（无 Key）。**
2. **Gemini 原生通道未实现**；`multimodal.py` 也只有 openai / anthropic 两种模式，
   没有 Gemini 的 `inlineData` / `fileData`。
3. **能力矩阵未接进内核**：`各供应商各模型支持能力_v2.0.md` 是文档，
   `Profile.supports_vision` / `doc_mimes` / `max_file_mb` 只有部分家填了值，
   内核**不会**在传图给不支持视觉的模型时提前拦截。
4. **规则数据待复审**：调研发现模型名已变更/下线（`deepseek-v4-flash` → `deepseek-flash`、
   `kimi-k2.5` 下线、Claude `opus-4-5` 不在在售阵容）。差异清单见 v2.0 §11。
5. **除 ollama 外无实机验证**：Anthropic / openai_compat 通道均为 MockTransport 用例，
   未对真实端点发过请求（无可用 Key）。
6. **既有超规范债（非本次引入）**：`palm_llm/cli/chat.py` 598 行（限 500）、
   `handle_command` 127 行、`cli/chat_tui.py::send` 109 行、`server/chat.py::run_chat` 107 行（限 50）。
   本次新增/改动的文件全部合规。
7. **内核仍不接主工程**：`app/` 下零 `palm_llm` 引用。
8. **内核不受 git 保护**（`.gitignore` 忽略 `1_Demo_LLM/`），删除前必须先备份。

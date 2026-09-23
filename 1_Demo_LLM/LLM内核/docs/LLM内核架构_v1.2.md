# palm_llm 内核架构 v1.2（两级匹配版）

> ⚠️ **本版已被 `LLM内核架构_v1.3.md` 取代**（新增 Anthropic 原生通道与回传拆分器，
> 协议通道 2 → 3 条）。本文件保留作历史版本，两级匹配与 `apply_rule` 步骤顺序的说明仍适用。
>
> 版本：v1.2　｜　日期：2026-09-23　｜　来源：**逐文件实读 + 38 项单元测试实测**
> 取代：`LLM内核架构_v1.1.md`（v1.1 保留作历史版本）
> 关联：`供应商协议差异与特化通道方案_v1.2.md`（已落码）、`同功能异字段差异矩阵_v1.0.md`、
> 　　　`各模型思考强度调研_v1.0.md`、`各供应商各模型支持能力_v1.0.md`

---

## 0. v1.1 → v1.2 修订

| 事项 | v1.1 | v1.2 |
|---|---|---|
| 供应商适配 | 只有两条通道（openai_compat / ollama），未知 type 直接回落 | **新增两级匹配**：端点一级 → Profile；model id 二级 → ModelRule |
| 新增文件 | — | `providers/profiles.py`（188 行）、`providers/profiles_data.py`（315 行） |
| 测试 | 10（降级）+ ollama | **28（降级 10 + 两级匹配 18）** + ollama 联调 |

---

## 1. 两级匹配（本次核心）

```
请求（base_url + cfg.type + model）
   │
   ├─【一级】cfg.type ＞ 端点/域名特征 ＞ generic   →  Profile（骨架层）
   │       例：open.bigmodel.cn → glm；api.moonshot.cn → kimi
   │
   └─【二级】model id 正则 fullmatch，多条取 priority 最大  →  ModelRule（模型层）
            │
            ├─ 命中    → 合并覆盖（只覆盖非空字段）→ apply_rule
            └─ 未命中  → 回落 Profile 默认，**不报错**（= 现状）
```

**合并语义**：`ModelRule` 只对**非空字段**覆盖 `Profile`，其余继承。
→ 新增一个模型只需加一条数据，**不加类、不加分支**。

---

## 2. `apply_rule` 的执行顺序（顺序本身是正确性的一部分）

```
1  读意图：从 payload 里消费掉调用方任一种思考写法（think/enable_thinking/reasoning_effort/thinking）
2  纠意图：命中 thinking="always_on" 而调用方要关 → 降级为 enabled + effort="low"（官方迁移口径）
3  夹档位：过 effort_map 映射，再收敛到 effort_allowed
4  剔禁参：rule.forbid_params（如 Anthropic 的 budget_tokens、Gemini 的 thinking_budget）
5  写目标：按 thinking_param 写该模型的思考字段；档位另写 reasoning_effort
6  套固定：rule.fixed_params **最后**覆盖（如 GLM-5.3 的 thinking.enabled、k2.7-code 的 temperature=1.0）
7  套厂商：profile.vendor_params
```

⚠️ 第 6 步必须在第 5 步**之后**：若 fixed 先写，会被第 1 步当成"调用方意图"再消费一遍。
（这是落码时实测踩到的 bug，已修。）

---

## 3. 已建档的规则（10 家 Profile）

| Profile | 一级命中 | 典型模型规则 |
|---|---|---|
| `glm` | `open.bigmodel.cn` | glm-5.3 强制思考（关不掉→low）、glm-5.2 档位映射、4.5~5.x 可关、4.4- 不支持 |
| `kimi` | `api.moonshot.cn` | k3 始终思考（禁 thinking 参数）、k2.7-code 锁 temperature=1.0、k2.6/2.5 可关 |
| `deepseek` | `api.deepseek.com` | v4-pro `xhigh→max`、v4-flash `xhigh→high`（**同厂商不同模型映射相反**） |
| `openai` | `api.openai.com` | gpt-5/o 系走 reasoning_effort、gpt-4 系不支持 |
| `anthropic` | `api.anthropic.com` | Opus4.7/5 等必须 `adaptive` + 禁 budget_tokens；Sonnet4.5/4-5 系反之 |
| `gemini` | `generativelanguage.googleapis.com` | 3.1 Pro 不可关且无 minimal；3 系列禁 thinking_budget；2.5 系列禁 thinking_level |
| `qwen` | `dashscope` / `maas.aliyuncs.com` | `-thinking` 后缀不可关、omni-flash 禁 thinking_budget、omni-turbo 不支持 |
| `doubao` | `volces.com` / `volcengineapi.com` | seed-character 系列不支持思考 |
| `hunyuan` | `tokenhub.tencentmaas.com` | 2.0-instruct 不支持、hy*-preview 强制开；**stop 语义 after** |
| `generic` | 兜底 | 无规则，原样透传 |

---

## 4. 三级容错全貌（与 v1.1 的降级通道叠加）

```
① 二级匹配后的完整 OpenAI 格式
      │ 400/404/415/422
      ▼
② 降级：基础字段子集（model/messages/stream/temperature/top_p/max_tokens）+ 纯文本消息
      │ 再失败
      ▼
③ 抛 RuntimeError
```
> 401/403/429/5xx 不降级；已产出 chunk 后不降级。

---

## 5. 测试状态（实测）

| 套件 | 结果 |
|---|---|
| `tests/test_profiles_matching.py` | **18/18 OK** |
| `tests/test_openai_compat_degrade.py` | **10/10 OK** |
| `tests/test_ollama_provider.py` | **ALL PASS**（含 ollama 实机联调） |

运行：`RAG/.bench_venv/Scripts/python.exe -m unittest tests.test_profiles_matching tests.test_openai_compat_degrade`

---

## 6. 现状缺口（诚实清单）

1. 🔴 **`Message.to_openai()` 不携带 `reasoning_content`**（`models.py:39-65`），`server.Message.to_kernel()` 也丢弃 `reasoning`。
   → `Profile.needs_reasoning_echo` 数据已就位，但**内核仍做不到回传**。这是上 Anthropic / Gemini 原生通道的硬门槛。
2. **二级匹配只做「参数卫生 + 思考翻译」**，不做**协议骨架转换** —— Anthropic / Gemini 仍走 openai_compat。
3. **降级通道救不了「参数值被锁」以外的问题**，也救不了能力缺失（如给不支持 vision 的模型传图片）。
4. 规则基于官方文档，**除 ollama 外无实机验证**；档位会随厂商迭代变（规则已带 `as_of`，需定期复审）。
5. **内核仍不接主工程**：`app/` 下零 `palm_llm` 引用。
6. **内核不受 git 保护**（`.gitignore` 忽略 `1_Demo_LLM/`），删除前必须先备份。

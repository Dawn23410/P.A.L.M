# palm_llm 内核架构 v1.1（纯 API 版）

> 版本：v1.1　｜　日期：2026-09-23　｜　来源：**逐文件实读 + 单元测试实测**
> 取代：`LLM内核架构_v1.0.md`（v1.0 保留作历史版本）
> ⬆️ **已被 v1.2 取代**：v1.2 新增两级匹配（Profile + ModelRule）。本文件保留作历史版本。
> 范围：`D:\P.A.L.M\1_Demo_LLM\LLM内核`（22 个 .py，3873 行）
> 关联：`各模型思考强度调研_v1.0.md`、`供应商协议差异与特化通道方案_v1.1/_v1.2.md`

---

## 0. v1.0 → v1.1 修订

| 事项 | v1.0 | v1.1 |
|---|---|---|
| Web 前端 | 含 `server/web.py`（766 行零依赖 WebUI）+ `cli/push_answer.py` | **已删除**，转**纯 API 内核**，HTTP 入口只剩 `api.py`（FastAPI） |
| 通用通道 | 只按标准 OpenAI 格式发一次 | **新增降级通道**：完整格式 400/404/415/422 → 自动降级为基础字段子集重试一次 → 再失败才抛 |
| 代码量 | 24 文件 4432 行 | 22 文件 3873 行 |
| 测试 | 仅 ollama 用例 | 新增 `test_openai_compat_degrade.py`（10 用例，MockTransport 无网络） |

> ⚠️ **删除前已备份**：`.workbuddy/backup/20260923_web_removal/`（`web.py`、`push_answer.py`，MD5 已校验一致）。
> 原因：`.gitignore` 忽略 `1_Demo_LLM/`，内核**不受 git 保护**，删除不可恢复。

---

## 1. 分层架构（纯 API 版）

```
┌─ ① 调用方 ────────────────────────────────────────────────────────┐
│  CLI(chat / chat_tui / benchmark) │ 外部 HTTP 客户端 │ Python import │
└──────────────────────────────┬────────────────────────────────────┘
┌─ ② 应用层 palm_llm.server ───┴────────────────────────────────────┐
│  models.py   应用 pydantic 模型 ★to_kernel 边界                      │
│  config.py   config.json 读写（PALM_LLM_HOME）                      │
│  storage.py  会话 JSON 持久化 CRUD                                   │
│  chat.py     run_chat SSE 调度                                      │
│  discovery.py / metrics.py / api.py（FastAPI，唯一 HTTP 入口 :10083）│
└──────────────────────────────┬────────────────────────────────────┘
                    to_kernel() 显式转换
┌─ ③ 内核 palm_llm ────────────┴────────────────────────────────────┐
│  models.py / providers/base.py                                      │
│  providers/openai_compat.py  ★通用通道 + ★降级通道                   │
│  providers/ollama.py         原生通道                                │
└──────────────────────────────┬────────────────────────────────────┘
┌─ ④ 外部端点 ─────────────────┴────────────────────────────────────┐
│  /v1/chat/completions │ /api/chat（127.0.0.1:11434）                 │
└───────────────────────────────────────────────────────────────────┘
```

**原 `web.py` 承载的静态前端、代码沙箱、蜜罐审计、网络策略、emoji 统计一并移除**——它们与 LLM 调用无关，是该文件膨胀到 766 行的主因。

---

## 2. ★ 通用通道 → 降级通道（本次核心改动）

```
payload = 完整 OpenAI 格式（model/messages/stream/采样 + tools + extra_body）
   │
   ├─ 200 → 正常产出
   │
   └─ HTTP 400 / 404 / 415 / 422（多为"厂商不认识某个字段"）
         │
         ▼
      payload = 基础字段子集 + 纯文本消息   ← 降级，只做一次
         │
         ├─ 200 → 正常产出（降级成功）
         └─ 再失败 → 抛 RuntimeError（带"已降级"标记）
```

**基础字段白名单**（各家 OpenAI 兼容端点必定实现）：

```
model   messages   stream   temperature   top_p   max_tokens
```

**降级时剥离**：

| 剥离项 | 理由 |
|---|---|
| `reasoning_effort` / `thinking` / `enable_thinking` / `thinking_budget` / `extra_body` 全部键 | **存在性或档位枚举逐家逐模型不同**（见 `各模型思考强度调研_v1.0.md`）：MiniMax 完全没有；豆包/混元只有开关；GLM-5.3 强制开启；xAI grok-4.3 与 4.5 默认值相反 |
| `tools` / `tool_choice` | DeepSeek 思考模式下 `supportsToolChoice=false`；部分老端点不支持 |
| `stream_options` | 部分网关不认 |
| `stop` | 混元语义与 OpenAI 相反（停在匹配内容**之后**） |
| `response_format` / `logprobs` / `n` / `seed` / `user` / `logit_bias` | 支持度参差 |

**消息降级规则**：一律降为 `{"role": ..., "content": <string>}`；多模态 blocks → 抽取 text 拼接；**带 `tool_calls` 的 assistant 与 `role="tool"` 消息整体丢弃**（否则会因缺少 tool 响应被再次判为非法请求）。

**不降级的错误**：401/403（鉴权，降了无用）、429（限流）、5xx（服务端）—— 降级只会掩盖真实原因。

**为什么用「失败驱动」而不是「厂商白名单」**：厂商实现子集会随版本变化（本次调研即发现 GLM-5.3 收窄为三档、xAI 两代默认值相反），为每家维护字段白名单必然腐烂。让失败本身来判定更稳。

---

## 3. 模块清单（v1.1）

| 文件 | 行数 | 职责 |
|---|---:|---|
| `providers/openai_compat.py` | 278 | 通用通道 + 降级通道（本次重写） |
| `providers/ollama.py` | 304 | Ollama 原生通道 |
| `providers/base.py` | 173 | 基类 + `get_client` + 共享时序件 |
| `models.py` | 127 | 内核 dataclass |
| `providers/multimodal.py` | 61 | 多模态 blocks |
| `server/api.py` | 153 | FastAPI 唯一 HTTP 入口 |
| `server/chat.py` | 146 | SSE 调度 |
| `server/models.py` | 116 / `storage.py` 120 / `metrics.py` 80 / `discovery.py` 72 / `config.py` 70 | 应用层 |
| `cli/chat.py` 598 / `chat_tui.py` 484 / `benchmark.py` 419 | CLI |
| `tests/test_openai_compat_degrade.py` | ~130 | 降级通道 10 用例 |
| `tests/test_ollama_provider.py` | 297 | Ollama 用例（含联调） |

已删除：`server/web.py`（766）、`cli/push_answer.py`（49）。

---

## 4. 测试状态（实测）

| 套件 | 结果 |
|---|---|
| `tests/test_openai_compat_degrade.py` | **10/10 OK**（降级成功 / 两次都失败 / 401 不降级 / 非流式降级 / 纯逻辑 4 项） |
| `tests/test_ollama_provider.py` | **ALL PASS**（含 ollama 实机联调，非 mock） |

运行：`RAG/.bench_venv/Scripts/python.exe -m unittest tests.test_openai_compat_degrade`
（ollama 那套是 pytest 风格的模块级函数，直接 `python tests/test_ollama_provider.py`）

---

## 5. 现状缺口（诚实清单）

1. 🔴 **`Message.to_openai()` 不携带 `reasoning_content`**（`models.py:39-65`），`server.Message.to_kernel()` 也丢弃 `reasoning`。
   → 思维链**单向流出、回不去下一轮**。v1.1 §3 那四条"多轮必须回传"硬规则（DeepSeek / Kimi K3 / Anthropic / 腾讯云）在当前内核上**做不到**。这是上 Anthropic / Gemini 通道的硬门槛。
2. **只有两条通道**：anthropic / gemini 原生适配已移除；v1.2 的「端点一级匹配 + 模型二级匹配」**尚未落码**，
   目前 `get_provider_instance` 只认显式 `cfg.type`，未知 type 直接回落 openai_compat。
3. **降级通道只解决"字段不支持"**，解决不了**参数值被锁**（如 kimi-k2.7-code 的 `temperature` 必须 1.0）——那属于模型级二级匹配范畴。
4. **内核尚未接入主工程**：`app/` 下零 `palm_llm` 引用，也无外部调用 `:10083` / `/api/chat/stream`。
5. 无 `pyproject.toml`，定位为**内嵌目录**（`README.md` 亦标注"内嵌，无需安装"）；`.gitignore` 忽略 `1_Demo_LLM/`，**内核不受 git 保护**。

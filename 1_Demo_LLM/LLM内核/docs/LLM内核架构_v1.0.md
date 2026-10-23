# palm_llm 内核架构 v1.0

> 版本：v1.0　｜　日期：2026-09-23　｜　来源：**逐文件实读**（非推测）
> ⬆️ **已被 v1.1 取代**：v1.1 起 Web 前端已删除（纯 API 内核），通用通道新增降级通道。本文件保留作历史版本。
> 范围：`D:\P.A.L.M\1_Demo_LLM\LLM内核`（24 个 .py，4432 行）
> 关联：`供应商协议差异与特化通道方案_v1.1.md`（端点一级匹配）、`_v1.2.md`（模型级二级匹配）、`Ollama原生适配_v1.0.md`

---

## 1. 一句话概括

`palm_llm` 是一个**四层**的流式 LLM 调用栈：**内核只做「发请求 + 解流」，应用层只做「状态 + HTTP」，两者用 `to_kernel()` 显式转换隔开**。
内核**零框架依赖**（httpx + pydantic），应用层才引入 FastAPI / 磁盘状态。

---

## 2. 分层架构

```
┌─ ① 调用方 ─────────────────────────────────────────────────────────┐
│  CLI(chat/chat_tui/benchmark/push_answer) │ WebUI 前端 │ Python import │
└──────────────────────────────┬─────────────────────────────────────┘
                               │ （Python import 可绕过应用层直连内核）
┌─ ② 应用层 palm_llm.server ───┴─────────────────────────────────────┐
│  models.py   应用 pydantic 模型（AppConfig/ChatRequest/...）★to_kernel 边界 │
│  config.py   config.json 读写；数据目录 PALM_LLM_HOME（默认 ~/.palm-llm）   │
│  storage.py  会话 JSON 持久化 CRUD + 导入导出                              │
│  chat.py     run_chat：SSE 调度（落盘走 asyncio.to_thread）                │
│  discovery.py 远端模型列表发现（ollama 走 /api/tags，其余走 /models）      │
│  metrics.py  进程内开销监控（计数器 + 可选 psutil）                        │
│  web.py      零依赖 WebUI 服务端（http.server，766 行）                    │
│  api.py      FastAPI 生产入口（:10083）                                    │
└──────────────────────────────┬─────────────────────────────────────┘
                    to_kernel() 显式转换（非 duck-type）
┌─ ③ 内核 palm_llm ────────────┴─────────────────────────────────────┐
│  models.py      dataclass：ProviderConfig / Message / Tool / ModelParameters │
│  providers/base.py  BaseProvider + get_client + 共享时序件                   │
│  providers/openai_compat.py   OpenAI 兼容通道（/v1/chat/completions）        │
│  providers/ollama.py          Ollama 原生通道（/api/chat）                   │
│  providers/multimodal.py      多模态 content blocks（openai / anthropic）    │
│  providers/__init__.py        get_provider_instance 按 cfg.type 工厂分发      │
└──────────────────────────────┬─────────────────────────────────────┘
┌─ ④ 外部端点 ─────────────────┴─────────────────────────────────────┐
│  /v1/chat/completions（智谱·DeepSeek·Kimi·Qwen·豆包…） │ /api/chat（127.0.0.1:11434）│
└────────────────────────────────────────────────────────────────────┘
```

---

## 3. 模块清单

| 文件 | 行数 | 职责 | 备注 |
|---|---:|---|---|
| `models.py` | 127 | 内核 dataclass 数据模型 | `Message.to_openai()` 是消息归一唯一出口 |
| `providers/base.py` | 173 | 基类 + 客户端缓存 + 共享时序件 | `get_client()` / `FIRST_BYTE_TIMEOUT` / `chain()` / `to_chat_message()` / `prewarm()` |
| `providers/openai_compat.py` | 178 | OpenAI 兼容通道 | 流式 SSE + 非流式；原生 Tool Calling |
| `providers/ollama.py` | 304 | Ollama 原生通道 | `think` 一等参数、`message.thinking`、分段耗时 |
| `providers/multimodal.py` | 61 | 多模态 blocks | 纯逻辑无 IO；保留 anthropic 分支 |
| `providers/__init__.py` | 34 | 工厂分发 | `openai_compat` / `ollama` / `ollama_native` |
| `server/chat.py` | 146 | SSE 调度 | 事件产出 + 落盘 + 埋点 |
| `server/api.py` | 153 | FastAPI 入口 | `:10083`，含 `/health`、`/metrics` |
| `server/web.py` | 766 | 零依赖 WebUI | http.server；**内含沙箱/蜜罐/网络策略等超范围功能** |
| `server/models.py` | 116 | 应用层模型 | `to_kernel()` 边界转换 |
| `server/storage.py` | 120 | 会话 JSON CRUD | 每会话一个文件 |
| `server/config.py` | 70 | config.json 读写 | `PALM_LLM_HOME` 可覆盖 |
| `server/discovery.py` | 72 | 模型发现 | 两条端点 |
| `server/metrics.py` | 80 | 开销监控 | 线程安全计数器 |
| `cli/chat.py` | 598 | 交互式 CLI | argparse 纯标准库 |
| `cli/chat_tui.py` | 484 | Textual TUI | 可选依赖 |
| `cli/benchmark.py` | 419 | 基准测试 | 矩阵 + 进阶用例 |
| `tests/test_ollama_provider.py` | 297 | Ollama 用例 | 纯逻辑 + 联调（无服务自动跳过） |

---

## 4. 两条 provider 通道对比

| 维度 | openai_compat | ollama（原生） |
|---|---|---|
| 端点 | `{base}/chat/completions` | `{root}/api/chat`（自动剥掉误写的 `/v1`） |
| 流式格式 | SSE `data:` 行，`[DONE]` 收尾 | NDJSON 逐行，`obj.done=true` 收尾 |
| 思维链字段 | `reasoning_content` **双读** `reasoning` | `message.thinking` |
| 思考开关 | 靠 `extra_body` 透传（各家写法不一） | `_resolve_think()` 把 4 种写法归一为原生 `think` |
| 采样参数 | 顶层直传 | 塞进 `options`（`max_tokens`→`num_predict`） |
| 凭证 | 强制校验 `_check_key()` | 主动跳过（本地无需 key） |
| usage | 原样透传 | 转换 + 附加 `load_ms/prompt_eval_ms/eval_ms/total_ms` |
| tool_calls | 流式**分片**，按 index 追加拼接 | 原生给**完整**调用，arguments 序列化为 JSON 串 |
| 预热 | `GET /models` | `GET /api/tags`（只热连接，不加载模型） |

---

## 5. 关键机制（都有实测/踩坑背书）

| 机制 | 位置 | 要点 |
|---|---|---|
| **事件循环安全的客户端复用** | `base.get_client()` | 以**事件循环对象本身**为键缓存（不用 `id(loop)`，避免 GC 后 id 复用串号）；每次取用清理已关闭循环。HTTP/2 优先，未装 h2 时降级 HTTP/1.1 并告警一次 |
| **首字节专用超时 + failover** | 两通道 `complete()` | `FIRST_BYTE_TIMEOUT=15s`；死连接快速失败而非挂到 300s read 超时。**仅在尚未产出任何 chunk 时重试一次**，已产出则直接抛（否则重复生成） |
| **单生成器约定** | `ollama.py` | `complete` 内部不再嵌套异步生成器；非流式走返回 list 的 `_fetch_once`。避免调用方 `break` 早退时内层 httpx stream 被重复 aclose（`RuntimeError: aclose(): asynchronous generator is already running`） |
| **消息归一单一出口** | `base.to_chat_message()` | system / 多模态 / tool_calls / role=tool 回填全走 `Message.to_openai()`，避免多处转换漂移 |
| **应用层→内核显式转换** | `server/models.py` | pydantic 模型经 `to_kernel()` 转 dataclass，不依赖内核字段隐式 duck-type |
| **请求级端点覆盖** | `chat.run_chat()` | `req.base_url` / `req.api_key` 优先级高于 config.json 且**不落盘**；两者皆空且无 provider 时凭请求构造 `__request__` |
| **埋点** | `metrics.record_request()` | `run_chat` 的 `finally` 里执行，成功失败都记；per-provider 聚合 + 最近 20 次 |

---

## 6. 事件契约（前端/CLI 实际消费的东西）

`run_chat` 产出的 SSE 事件序列：

| 事件 | 时机 | 载荷 |
|---|---|---|
| `meta` | 会话确定后 | `conversation_id` / `title` |
| `reasoning` | 思维链增量（多帧） | `content` |
| `token` | 正文增量（多帧） | `content` |
| `tool_call_delta` | 拿到工具名即发 | `index` / `id` / `name` |
| `tool_calls` | 流末 | 完整调用数组（arguments 已拼成合法 JSON） |
| `done` | 流结束 | `usage` |
| `error` | 异常 | `message` |
| `meta(finished)` | 落盘后 | 收尾帧 |

---

## 7. 数据落点

```
$PALM_LLM_HOME（默认 ~/.palm-llm）
  config.json              提供方配置（api_key 明文，前端回写时靠 "********" 遮罩回填）
  data/conversations/*.json  每会话一文件
  data/uploads/*             上传图片
```

---

## 8. 现状缺口（诚实清单）

1. 🔴 **`Message.to_openai()` 不携带 `reasoning_content`**（`models.py:39-65` 只输出 role/content/images/tool_calls/tool_call_id/name）。
   且 `server.Message.to_kernel()` 也**丢弃** `reasoning` 字段。
   → **v1.1 §3 那四条"多轮必须回传"硬规则（DeepSeek / Kimi K3 / Anthropic / 腾讯云）在当前内核上做不到**。这是做 P2（Anthropic/Gemini 通道）的硬门槛。
2. **只有两条通道**：`anthropic` / `gemini` 原生适配已按需求移除，目前一律走 `openai_compat`（v1.1/v1.2 的通道方案尚未落码）。
3. **一级匹配仅靠显式 `cfg.type`**，尚无端点/域名自动识别（`get_provider_instance` 未知 type 直接回落 openai_compat）。
4. **内核尚未接入主工程**：全仓 grep 显示 `app/` 下没有任何 `palm_llm` 引用，也无外部调用 `:10083` / `/api/chat/stream`。目前是**独立可运行**状态。
5. **`web.py` 职责溢出**：766 行里含代码沙箱、蜜罐审计、网络策略、emoji 统计等与 LLM 调用无关的功能，是该文件膨胀的主因。
6. 无 `pyproject.toml` / `setup.py`，定位为**内嵌目录**而非可安装包（`README.md` 亦标注"内嵌，无需安装"）。

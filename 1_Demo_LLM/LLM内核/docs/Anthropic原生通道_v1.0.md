# Anthropic 原生通道 v1.0

> 落码：`palm_llm/providers/anthropic.py`（传输 + 思考配置，295 行）
> 　　　`palm_llm/providers/anthropic_wire.py`（线格式双向转换，299 行）
> 用例：`tests/test_anthropic_provider.py`（15 个）
> 启用方式：`ProviderConfig(type="anthropic", base_url="https://api.anthropic.com")`

## 一、为什么不复用 openai_compat

Anthropic 提供 OpenAI 兼容端点，但差异是**结构级**的，靠字段映射表翻不出来：

| 维度 | Anthropic 原生 | OpenAI 兼容层 |
|---|---|---|
| system 提示词 | **顶层 `system` 参数**，messages 里没有 system 角色 | messages 里的一条 `role:"system"` |
| `max_tokens` | **必填**，缺了直接 400 | 可选 |
| 工具声明 | `{name, description, input_schema}` | `{type:"function", function:{name, parameters}}` |
| 工具选择 | `{type:"any"}` 表示必须调某个工具 | `"required"` |
| 流式粒度 | **块级生命周期**：`message_start` → `content_block_start/delta/stop` → `message_delta` → `message_stop` | 每帧一个 `choices[0].delta` |
| 思考签名 | `signature_delta` 事件，**必须原样回传** | 兼容层拿不到 |
| 缓存 token | `cache_read_input_tokens` / `cache_creation_input_tokens`，且 `input_tokens` **不含**缓存 | 多为聚合后的假数 |
| 思考档位 | `output_config.effort` | 通常是 `reasoning_effort` |

结论：**请求方向结构不同（装不进统一字段集），响应方向粒度不同（不是"换个键名"）**，
故独立成通道，而不是继续叠兼容层。

## 二、端点与鉴权

| 项 | 值 |
|---|---|
| URL | `POST {base}/v1/messages` |
| 鉴权 | `x-api-key: <key>`　（**不是** `Authorization: Bearer`） |
| 版本头 | `anthropic-version: 2023-06-01`（可用 `cfg.extra.anthropic_version` 覆盖） |
| `base_url` 容错 | 自动剥掉误写的 `/v1`、`/v1/messages`、`/messages` 后缀再拼接 |

## 三、请求映射

| 内核结构 | 原生结构 |
|---|---|
| `Message(role="system")` | 顶层 `system`（多条用 `\n\n` 拼接） |
| `role="user"` + `images` | `{type:"text"}` + `{type:"image", source:{type:"base64", media_type, data}}` |
| `role="assistant"` + `tool_calls` | `{type:"tool_use", id, name, input}`（`arguments` 字符串 → 对象） |
| `role="tool"` | **user 消息** + `{type:"tool_result", tool_use_id, content}` |
| 连续同角色消息 | 合并为一条（原生要求 user/assistant 严格交替） |
| `Tool.parameters` | `input_schema` |
| `tool_choice="required"` | `{type:"any"}` |
| `extra_body.stop` | `stop_sequences`（字符串自动包成数组） |

图片只认 base64：data URI 直接解析，http(s) URL 会先下载（复用 `BaseProvider.image_to_b64`）。

## 四、思考配置

开关与档位是**两条独立通道**，规则级常量由 `profiles` 二级匹配提供，provider 只翻形状：

| 模型代际 | 规则产出 | 原生下发 |
|---|---|---|
| Opus 4.7 / 4.8 / 5、Sonnet 5、Fable 5、Mythos 5 | `fixed_params={"thinking":{"type":"adaptive"}}` | `thinking:{type:"adaptive"}`，**禁带** `budget_tokens`（带了 → 400） |
| Sonnet 4.5 / Opus 4.5 / Haiku 4.5 及更早 | `thinking="toggle"` | `thinking:{type:"enabled", budget_tokens:N}`（缺则补 8192，且保证 < `max_tokens`） |
| 档位 | `reasoning_effort` 或 `output_config.effort` | `output_config:{effort:"low|medium|high|xhigh|max"}` |

三条硬约束：

1. **规则锁死优先于调用方意图** —— `adaptive` 是硬性约束不是偏好，调用方说"关思考"也照发。
2. **调用方没表达开关时不下发 `thinking`** —— 一旦下发就要连带省略 `temperature`/`top_p`，
   等于静默改了采样行为。宁可不下发。
3. **思考开启时省略 `temperature` / `top_p`** —— 原生在思考模式下只接受默认 temperature=1，
   且与 `top_p` 互斥，下发了就是必然 400。服务端默认值即 1，省略等价于正确值。

## 五、流式事件映射

| 原生事件 | 内核动作 |
|---|---|
| `message_start` | 取 `message.usage`（输入侧 token + 缓存）、`message.id`、`message.model` |
| `content_block_start`（`tool_use`） | 分配槽位 + **立刻下发 `tool_call_delta`**（拿到名字即显示"正在调用 X"） |
| `content_block_delta` / `text_delta` | → `{"content": ...}` |
| `content_block_delta` / `thinking_delta` | → `{"reasoning": ...}` |
| `content_block_delta` / `input_json_delta` | 按块 index 累加 `partial_json` |
| `content_block_delta` / `signature_delta` | 累积思考签名（多块用 `\0` 分隔），进 `stats.extra.thinking_signature` |
| `content_block_stop` | 无动作（收尾统一在 `message_stop` 做） |
| `message_delta` | 取 `usage.output_tokens` 与 `stop_reason`（映射为 OpenAI 口径） |
| `message_stop` | 下发完整 `tool_calls`（若有）→ 下发 `done` + `usage` + `stats` |
| `ping` | 忽略 |
| `error` | 抛 `RuntimeError`，内容取 `error.message` |

解析只认 `data:` 行，事件类型从 JSON 的 `type` 字段取 —— `event:` 行与 JSON 必然同值，
多读一处只多一个漂移点。

## 六、容错与降级

| 情况 | 处理 |
|---|---|
| HTTP 4xx / 5xx | 解包 `error.message` 抛 `RuntimeError`（**不重试** —— 换连接没用） |
| 传输层错误 / `FirstByteTimeout` | 仅在**尚未产出任何帧**时换连接重试一次 |
| 已产出后传输中断 | 直接抛（重试会造成重复生成） |
| 流中断但没等到 `message_stop` | 已产出内容有效，补一个收尾帧（不当作错误） |

首字节专用短超时沿用 `base.FIRST_BYTE_TIMEOUT`（15 s），与另两个通道一致。

## 七、本轮**未**实现（明确边界）

- Prompt caching 的显式 `cache_control` 断点写入（只**读**缓存统计，不主动打断点）
- Beta 头（`anthropic-beta`）相关的实验特性
- 服务端工具（web search / code execution / files API）与 Message Batches
- 交错思考的 beta 头（`interleaved-thinking-2025-05-14`）显式声明 —— 原生块序列已能保真
  承载交错形态（见下节），但未主动申请该特性

## 八、思考块回传（已实现）

原生协议要求多轮把上一轮助手消息的思考块原样送回。本通道做一次往返：

- **响应侧**：`on_event` 按原生块索引重建 content 数组，收尾时把整条序列以 JSON 存进
  `stats.extra.native_blocks`（同时保留人可读的 `thinking_signature`）。
- **请求侧**：`to_native_messages(..., echo_reasoning=)` 发现上一轮留下的凭据就**整条复活**，
  不再由内核字段重建。

两条必须说清楚的取舍：

1. **存整条而不是只存思考块**：思考块必须打头，交错思考下还会夹在多个 `tool_use` 之间，
   而官方判定线是"原样、原顺序" —— 只存思考块就丢了位置。
2. **只在本轮带 `tools` 时回传**：官方口径是"带思考用工具时回传才严格必需"，其余场景可
   省略；而 keep-all 模型上回传的历史思考会**持续计入输入 token**，纯聊天场景无条件回传
   等于每轮为旧思考付钱。

另有一条官方保证让实现得以简化：**思考被关时传入思考块不报错**，是"优雅降级：剥离该内容"，
所以无需再做"思考开关状态 → 是否剥离"的模式感知判断。

跨通道的契约分级与出处汇总见 `docs/思考块回传契约_v1.0.md`。

## 九、验证情况

`tests/test_anthropic_provider.py` 15 个用例，覆盖：

- 载荷形状：system 外提、`max_tokens` 必填、`input_schema` 改名、`required → any`
- 思考配置：adaptive 锁死且不带 budget、老代模型补 budget 且小于 max_tokens、
  effort 传递、**普通模型保留 temperature/top_p**
- 消息转换：`tool` → user+tool_result、连续同角色合并、图片 → base64 块、URL 归一
- 流式：块级事件映射、思考签名留存、工具参数分片拼接、缓存 token 进 stats
- 非流式：三类 content block 解析、`chunks`/全文累加非 0（结算时序回归）
- 错误：`error` 体解包后 `RuntimeError` 带原文

思考块回传另见 `tests/test_reasoning_echo.py`（18 个用例，含"通道按 tools 决定回传"与
"凭据原样复活"）。

全量回归：**75 个用例全过**（profiles 18 + degrade 11 + telemetry 13 + anthropic 15 +
回传契约 18），本地 ollama 套件 `ALL PASS`。

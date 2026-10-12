# LLM 内核 × 前端 UI：适配差异与缺失清单

> 生成日期：2026-10-05
> 内核源：`D:\P.A.L.M\核心-检验完成\LLM内核\palm_llm\`（AS_OF 2026-09-23）
> 前端：`C:\Users\24459\Desktop\webui\`
> 证据：内核源码 + `.palm-llm/` 真实运行数据 + 差分测试（51/53 逐字段一致）

---

## 一、内核真实 API 面（9 个端点）

| 方法 | 路径 | 用途 | 前端是否使用 |
|---|---|---|---|
| GET | `/health` | 存活探针 | ✗ |
| GET | `/metrics` | 请求数/错误数/耗时/per-provider/token 累计/RSS/CPU | ✗ |
| GET | `/api/config` | 配置读取（api_key 以 `********` 遮罩） | ✗ |
| POST | `/api/config` | 配置写入（遮罩值自动回填真 key） | ✗ |
| GET | `/api/conversations` | 会话列表 | ✗ |
| GET | `/api/conversations/{cid}` | 会话详情 | ✗ |
| DELETE | `/api/conversations/{cid}` | 删除会话 | ✗ |
| POST | `/api/chat/stream` | SSE 流式对话 | ✓ |
| POST | `/api/models/discover` | 按协议探测上游模型列表 | ✓ |

**前端只用了 2/9。**

### SSE 事件契约（内核 chat.py 实际发出 8 种）

| 事件 | 载荷 | 前端是否处理 |
|---|---|---|
| `meta` | `{conversation_id, title}`；收尾再发一次带 `finished:true` | 部分（只取 conversation_id，**丢弃 title**） |
| `reasoning` | `{content}` 思考链增量 | ✗ **整段丢弃** |
| `token` | `{content}` 回答增量 | ✓ |
| `tool_call_delta` | 工具调用增量 | ✗ |
| `tool_calls` | `{tool_calls}` 完整工具调用 | ✗ |
| `done` | `{usage, stats}` | 部分 |
| `error` | `{message, ...}` | ✓ |
| `[DONE]` | 流终止哨兵 | ✗（未显式处理） |

---

## 二、最严重的适配断裂：配置双轨

| | 内核 | 前端 |
|---|---|---|
| 存储位置 | `~/.palm-llm/config.json` | `localStorage['webui.models']` |
| 结构 | `AppConfig{providers[], active_provider, active_model, system_prompt, parameters, presets[]}` | 扁平数组 `[{id, model, vendor, features}]` |
| 供应商字段 | `{id, name, type, base_url, api_key, models[]}` | `{vendor, model, features, ...}` |

**后果：在「添加模型」弹窗里加模型，对内核没有任何影响。** 前端发起的对话请求体只有：

```js
{ content, conversation_id }
```

→ 内核永远使用 `config.json` 里的 `active_provider` / `active_model`，前端选的模型**完全不生效**。

### 请求体缺口（ChatRequest 支持的字段 vs 前端实际发送）

| 字段 | 内核 | 前端 |
|---|---|---|
| `conversation_id` | ✓ | ✓ |
| `content` | ✓ | ✓ |
| `provider` / `model` | ✓ | ✗ |
| `system_prompt` | ✓ | ✗ |
| `parameters` | ✓ | ✗ |
| `images` / `files` | ✓ | ✗ |
| `provider_type` / `base_url` / `api_key`（请求级覆盖，不落盘） | ✓ | ✗ |

---

## 三、缺失的前端 UI 清单

### A. 配置与模型管理（P0）
1. ~~**模型列表改读写内核 `/api/config`**，废弃 `localStorage['webui.models']`~~
   ✅ **已完成（2026-10-05）**：新增 `pages/kernel-api.js` 作为内核调用的唯一出口；
   `pages/models.js` 改为读内核配置；历史 localStorage 数据一次性迁移（只补不覆盖、
   key 并入、脱敏备份、旧键删除）；内核不可达时渲染重试错误态而非崩溃。
2. ~~**当前生效供应商 / 模型选择器**（`active_provider` / `active_model`）~~
   ✅ **已完成（最小形态）**：点击模型行即设为生效。内核本就按 `config.json` 的
   `active_provider/active_model` 发请求，所以配置统一后这一下点击即可端到端生效，
   **无需改动 `chat.js`**。
3. **系统提示词编辑框**（`system_prompt`）
4. **模型参数面板**：`temperature` / `top_p` / `max_tokens` / `frequency_penalty` / `presence_penalty`
5. **`extra_body` 编辑**（透传参数，如 `{"enable_thinking": false}` 用来压首字延迟）
6. **预设（Preset）管理**：内核有 `Preset{name, prompt}`，前端零 UI
7. **本次对话的思考档位选择**——当前"思考强度"只记录模型**支持**哪些档位，没有"这一轮用哪一档"的入口
8. **请求级端点/KEY 覆盖 UI**（`provider_type`/`base_url`/`api_key`，不落盘）

### B. 会话管理（P0）
9. **会话列表侧栏**（`GET /api/conversations`）
10. **会话切换 / 加载历史**（`GET /api/conversations/{cid}`）
11. **会话删除**（`DELETE /api/conversations/{cid}`）
12. **新建会话**
13. **会话标题展示**（`meta` 事件已带 `title`，当前被丢弃）

### C. 消息渲染（P0）
14. **思考链展示**（SSE `reasoning` + `Message.reasoning`）—— 现在整段丢弃
15. **思考块折叠 / 展开**交互
16. **`reasoning_echo` 回传**——多轮不带回会被上游 400（DeepSeek 带 tools 时、Kimi K3 无条件）。前端目前不持久化该字段
17. **工具调用展示**（SSE `tool_calls` / `tool_call_delta`）
18. **工具结果回显**（`tool_call_id` / `name` / `tool_error`）
19. **图片消息渲染**（`Message.images`）
20. **文件附件渲染**（`Message.files`）
21. **使用内核的 `ts` 时间戳**——前端现在自己造时间

### D. 输入与多模态（P1）
22. **图片上传 / 粘贴**（内核支持 `images`，含 `/uploads/` 本地路径）
23. **文件上传**（内核支持 `files`，有 MIME 与体积硬闸门）
24. **能力矩阵前置提示**——内核会按 `doc_mimes` / `max_file_mb` / `reject_documents` 拦截，前端应提前灰掉不允许的入口

### E. 运行时状态（P1）
25. **健康探针与连接状态指示**（`GET /health`）——现在只有"连不上后端"的报错
26. **指标面板**（`GET /metrics`）
27. **结构化错误展示**（内核 `error` 事件带额外字段）

### F. 内核侧缺口（需内核补，前端做不了）
28. **无 `/api/profiles` 端点**——能力档案（`effort_allowed` 等）没有任何 HTTP 出口，前端只能内嵌镜像（本次已生成 `pages/kernel-profiles.js`，需随内核更新重新生成）
29. **无会话重命名 / 导出端点**
30. **供应商覆盖不全**：内核档案只有 9 家（deepseek/glm/qwen/kimi/doubao/hunyuan/openai/anthropic/gemini）+ generic，前端预设 18 家。xai/mistral/minimax/stepfun/spark/baichuan/非线/ollama/自定义 全部回落 generic，即"思考能力未知"
31. **`Profile` 缺 `reject_forced_tool` 字段**（详见第四节）
32. **`config.json` 明文存 API Key**（详见第四节）

---

## 四、本次测试发现的缺陷

### 内核缺陷 1（崩溃级）
`palm_llm/providers/_profiles.py` 的 `_MERGE_FIELDS` 列了 `reject_forced_tool`，
但 `Profile` 数据类没有该字段：

```
TypeError: Profile.__init__() got an unexpected keyword argument 'reject_forced_tool'
```

触发条件：匹配到设置了该字段的规则（`claude-(fable|mythos)-5\.1`）。
差分测试 53 条里恰好 1 条崩在这里。

修法二选一：给 `Profile` 补 `reject_forced_tool: Optional[bool] = None`，
或从 `_MERGE_FIELDS` 移除它（该字段本就是模型级概念）。

### 内核缺陷 2（安全）
`~/.palm-llm/config.json` 里 `zhipu` 那条 provider 存着**明文可用的 API Key**。
配置接口虽然对 GET 做了 `********` 遮罩，但磁盘上是明文。建议至少做文件权限收敛，
或改为 `api_key_env` 引用环境变量。

### 前端缺陷 1（安全，已修）
`pages/model-modal.js` 把上游返回的模型 id 直接拼进 `innerHTML`：

```js
<div class="mm-mcard" data-model="${id}">   // 属性逃逸
<span class="n">${id}</span>                // 标签注入
```

实测 `<img src=x onerror="...">` 会真的执行（`window.__pwned=1`）。
任意可控制 `/api/models/discover` 响应的一方都能拿到页面执行权。
已加 `esc()` 转义并回归通过。

### 前端缺陷 2（健壮性，已修）
`inferCapability` 用 `VENDOR_BASE[vendor]` 直接取值，供应商传成
`__proto__` / `constructor` / `toString` 时会命中原型链成员，`base.lv.slice()` 抛 TypeError。
198 个非法输入组合中曾崩 55 个，已改用 `hasOwnProperty` 守卫 + 大小写/空白归一，
现 198/198 通过。

---

## 五、本次已完成的适配

| 项 | 内容 |
|---|---|
| 能力数据源 | 废弃手写调研表，改为**从内核源码自动生成镜像** `pages/kernel-profiles.js`（10 Profile / 30 规则，16KB） |
| 匹配语义 | 对齐内核：两级匹配 + `priority` 降序 + `fullmatch` + 非空字段覆盖 |
| 思考档位 | 词汇表由 5 档修正为内核真实全集 **7 档**（none/minimal/low/medium/high/xhigh/max），每模型档位改由内核规则决定 |
| 差分验证 | 53 条样本逐字段比对内核 Python 输出，51 条精确一致，2 条为前端有意补充（非对话模型拦截） |

---

## 六、建议的推进顺序

1. **P0-配置统一**：模型列表改走 `/api/config`，让「添加模型」真正生效（解锁其余一切）
2. **P0-会话**：会话列表 + 历史加载（没有它，刷新即丢上下文）
3. **P0-思考链**：渲染 `reasoning` 事件 + 持久化 `reasoning_echo`（不修会 400）
4. **P1-多模态**：图片/文件上传
5. **P1-运行时**：健康探针 + 指标面板
6. **内核侧**：补 `/api/profiles` 端点（可让前端删掉内嵌镜像）、修 `reject_forced_tool`、收敛 API Key 存储

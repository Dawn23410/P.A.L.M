# P.A.L.M 砖块多维度体检报告（除 agent 外 13 砖）

> 评分基准：联网检索的业界最佳实践（FastAPI 生产模式、LLM 多供应商抽象、文件上传安全、OCR 生产流水线、SM4 密钥生命周期、代码沙箱隔离、Token 计量架构、OPA 策略即代码、本地存储分类、离线网络拦截）。
> 评分维度（每维度 1–5 星）：功能完整性 / 接口设计 / 错误处理 / 安全性 / 持久化 / 模块化 / 可观测性 / 可扩展性。
> ⭐ = 弱，⭐⭐⭐⭐⭐ = 优秀。

---

## 1. file 砖 — 文件上传 + 静态服务

| 维度 | 评分 | 证据与点评 |
|------|:----:|------|
| 功能完整性 | ⭐⭐⭐ | `POST /api/files/upload` 收 `list[UploadFile]`，静态 `/uploads` 交给 FastAPI `StaticFiles`。**无类型/大小/配额校验**。 |
| 接口设计 | ⭐⭐⭐⭐ | 端点干净，上传走 `require_api_token` Bearer 鉴权。 |
| 错误处理 | ⭐⭐ | `save_uploads` 无 try/except，异常直接上抛 500；仅 `os.path.basename` 防路径穿越。 |
| 安全性 | ⭐⭐ | **不校验 MIME/扩展名/体积**；静态目录无逐文件权限（任何人持 token 可读他人文件）；magic bytes 检测缺失。 |
| 持久化 | ⭐⭐⭐ | 委托 storage，但自身无配额/清理策略。 |
| 模块化 | ⭐⭐ | **不导出任何 capabilities**，直接 import `security`，纯端点型。 |
| 可观测性 | ⭐⭐ | 无日志。 |
| 可扩展性 | ⭐⭐ | 无 hook/扩展点。 |

**结论**：基础可用但**安全短板最明显**。建议补：文件类型 allowlist（校验 magic bytes）、大小/数量限制、静态服务逐文件鉴权或改为经应用层读取。

---

## 2. chat 砖 — 流式对话核心（核心砖）

| 维度 | 评分 | 证据与点评 |
|------|:----:|------|
| 功能完整性 | ⭐⭐⭐⭐⭐ | `POST /api/chat` SSE + `/file-support`；取 models 流、用量配额、文件模式分流、usage 兜底估算（`prompt/2, completion/4`）。 |
| 接口设计 | ⭐⭐⭐⭐⭐ | 事件格式 `{id,model,created,delta,reasoning,usage}` + `[DONE]`；503（缺模型）/429（超配额）/400（process 模式拒收）语义清晰。 |
| 错误处理 | ⭐⭐⭐⭐ | 模型能力缺失→503；配额超额→429；流末 usage 缺失降级估算，仅存 provider 字符串防序列化失败。 |
| 安全性 | ⭐⭐⭐⭐ | `direct`/`process` 文件模式门控 + token 鉴权。 |
| 持久化 | ⭐⭐⭐ | 委托 conversations/storage 落盘。 |
| 模块化 | ⭐⭐⭐⭐⭐ | 经 `registry.get("models"/"usage").capabilities[...]` 懒加载取用，**无跨砖 import**。 |
| 可观测性 | ⭐⭐⭐ | 用量可追，但无全链路 trace。 |
| 可扩展性 | ⭐⭐⭐⭐ | 能力化取用，模型/计量可热插拔。 |

**结论**：核心砖设计扎实，是系统 backbone。

---

## 3. models 砖 — 模型供应商后端

| 维度 | 评分 | 证据与点评 |
|------|:----:|------|
| 功能完整性 | ⭐⭐⭐⭐⭐ | 三协议 `MockProvider`/`OpenAIProvider`/`AnthropicProvider`；`POST /api/models/discover` 拉清单；思维链三源兼容（`reasoning_content`/`reasoning`/`thinking`）。 |
| 接口设计 | ⭐⭐⭐⭐⭐ | 协议归一化良好，Anthropic `max_tokens>=2048` 才开 thinking 且禁温度。 |
| 错误处理 | ⭐⭐⭐⭐ | discover 失败 502，httpx 缺失 500，流式异常经 chat 兜底。 |
| 安全性 | ⭐⭐⭐⭐ | API Key 不落明文本地（由用户配置）。 |
| 持久化 | ⭐⭐⭐⭐ | 模型配置持久化。 |
| 模块化 | ⭐⭐⭐⭐⭐ | 导出 `create_stream/is_model_file_capable/file_handling_mode/model_supports_files`。 |
| 可观测性 | ⭐⭐⭐ | 无独立 metrics。 |
| 可扩展性 | ⭐⭐⭐⭐ | Provider 适配器模式，加新供应商成本低。 |

**结论**：多供应商抽象符合 LiteLLM/通用能力层最佳实践。

---

## 4. conversations 砖 — 会话记录落盘

| 维度 | 评分 | 证据与点评 |
|------|:----:|------|
| 功能完整性 | ⭐⭐⭐⭐ | POST/GET/DELETE 齐全，upsert 固定文件名 `<convId>.json`。 |
| 接口设计 | ⭐⭐⭐⭐ | token 鉴权 + 404 校验。 |
| 错误处理 | ⭐⭐⭐⭐ | 损坏 JSON `continue` 跳过，删前 `find_config_file` 校验。 |
| 安全性 | ⭐⭐⭐⭐ | 写/删端点带鉴权。 |
| 持久化 | ⭐⭐⭐⭐⭐ | 复用 storage 单例（`get_store`）避免双实例竞争。 |
| 模块化 | ⭐⭐⭐⭐ | 仅消费 storage 能力，无跨砖 import。 |
| 可观测性 | ⭐⭐ | 无日志。 |
| 可扩展性 | ⭐⭐⭐ | 目录固定「对话记录」分类。 |

**结论**：典型瘦砖，职责清晰。

---

## 5. ollama 砖 — 本地模型全生命周期

| 维度 | 评分 | 证据与点评 |
|------|:----:|------|
| 功能完整性 | ⭐⭐⭐⭐⭐ | health/guide/catalog/library/download（断点续传）/upload/deploy/pull/import-gguf 全齐；GGUF 魔数校验。 |
| 接口设计 | ⭐⭐⭐⭐⭐ | 端点语义清晰，active downloads 可查。 |
| 错误处理 | ⭐⭐⭐⭐ | 统一 `_require_httpx` 缺失 500，代理失败 502，模型不存在 400。 |
| 安全性 | ⭐⭐⭐ | 本地服务，无需额外鉴权；GGUF 魔数校验防错传。 |
| 持久化 | ⭐⭐⭐⭐ | 下载/导入管理良好。 |
| 模块化 | ⭐⭐⭐ | 不导出能力（独立生命周期管理），但经 models 砖 OpenAI 兼容协议串流。 |
| 可观测性 | ⭐⭐⭐ | 下载进度可追踪。 |
| 可扩展性 | ⭐⭐⭐ | 分类扩展需改代码。 |

**结论**：本地模型管理完整度超出一般开源方案。

---

## 6. parse 砖 — 文档解析/OCR

| 维度 | 评分 | 证据与点评 |
|------|:----:|------|
| 功能完整性 | ⭐⭐⭐⭐ | image→OCR+预处理，document/text→doc2struct，文档内嵌图再 OCR。 |
| 接口设计 | ⭐⭐⭐⭐⭐ | 异步 job 模式（202 返回 job_id + 状态/结果端点），**异常码规范**：`UNSUPPORTED_FILE:4001`/`PROCESS_FAILED:5001`/`ENGINE_UNAVAILABLE:5002`。 |
| 错误处理 | ⭐⭐⭐⭐⭐ | 引擎不可用显式区分，OCR 单例 + 单线程 executor 防资源炸。 |
| 安全性 | ⭐⭐⭐ | 不支持类型直接拒（4001）；但缺文件大小上限。 |
| 持久化 | ⭐⭐⭐ | job 结果落地。 |
| 模块化 | ⭐⭐⭐ | 独立封装，tools 走子进程。 |
| 可观测性 | ⭐⭐⭐ | job 状态可查。 |
| 可扩展性 | ⭐⭐⭐ | controller 分发可加新 kind。 |

**结论**：**错误码设计是 13 砖里最规范的**，符合生产级 API 标准。

---

## 7. crypto 砖 — SM4 加解密

| 维度 | 评分 | 证据与点评 |
|------|:----:|------|
| 功能完整性 | ⭐⭐⭐⭐ | SM4-CBC + HMAC-SM3（iv16+cipher+mac32）；主板指纹；恢复密钥 + 校验码；开关持久化。 |
| 接口设计 | ⭐⭐⭐⭐ | 加/解密/开关端点均 `require_api_token`；前端永不显示恢复密钥明文。 |
| 错误处理 | ⭐⭐⭐⭐ | 加密失败返回 None 降级明文；gmssl 缺失注册空砖（`router=None`）。 |
| 安全性 | ⭐⭐⭐⭐ | 硬件绑定 + 恢复密钥不显示 + 校验码比对。但**指纹=单要素（仅主板）**，换主板即失效；状态文件明文 JSON；无密钥轮换。 |
| 持久化 | ⭐⭐⭐⭐ | 恢复校验码独立 `.recovery_checksum` 持久化。 |
| 模块化 | ⭐⭐⭐⭐⭐ | 导出 `encrypt_bytes/decrypt_bytes/is_enabled`，被 storage/settings 消费。 |
| 可观测性 | ⭐⭐ | 无审计日志。 |
| 可扩展性 | ⭐⭐⭐ | 算法固定 SM4。 |

**结论**：国密实现合格，单要素绑定是已知权衡（已在架构记忆记录）。建议补：密钥轮换、状态文件加密、操作审计日志。

---

## 8. storage 砖 — 本地分类存储

| 维度 | 评分 | 证据与点评 |
|------|:----:|------|
| 功能完整性 | ⭐⭐⭐⭐⭐ | 固定 5 分类、pool.json 元信息、加密写盘、stats/breakdown、原语齐全。 |
| 接口设计 | ⭐⭐⭐⭐ | CRUD 干净，写端点带 token 鉴权，`safe_category` 清洗。 |
| 错误处理 | ⭐⭐⭐⭐ | `os.replace` 原子写 + 锁 + `transaction()`；解密失败→404。 |
| 安全性 | ⭐⭐⭐⭐ | 集成 crypto 加密；分类名清洗防注入。 |
| 持久化 | ⭐⭐⭐⭐⭐ | `PoolStore._save` 临时文件 + `os.replace` 原子写，事务持锁。 |
| 模块化 | ⭐⭐⭐⭐⭐ | 暴露 `get_store/store_file/read_file_content/find_config_file/delete_file` 等 8 个能力，被 4+ 砖消费。 |
| 可观测性 | ⭐⭐⭐ | stats/breakdown 端点。 |
| 可扩展性 | ⭐⭐⭐⭐ | 通用原语，可接新分类。 |

**结论**：架构基石，原子写 + 能力化设计是模范。

---

## 9. offline 砖 — 离线模式

| 维度 | 评分 | 证据与点评 |
|------|:----:|------|
| 功能完整性 | ⭐⭐⭐⭐ | GET/POST 开关 + 导入期 `patch_httpx()` 全局拦截外网。 |
| 接口设计 | ⭐⭐⭐⭐ | 端点简单清晰。 |
| 错误处理 | ⭐⭐⭐⭐ | 幂等 patch，仅放 localhost/127.0.0.1/::1/0.0.0.0。 |
| 安全性 | ⭐⭐⭐ | **仅拦 httpx**；requests/urllib/socket 可绕过（自述风险，需配 sandbox 网络策略）。 |
| 持久化 | ⭐⭐⭐ | 开关状态持久化。 |
| 模块化 | ⭐⭐⭐⭐ | 导出 `is_offline`，core/gateway 实现。 |
| 可观测性 | ⭐⭐⭐ | 无拦截日志。 |
| 可扩展性 | ⭐⭐⭐ | 拦截规则固定。 |

**结论**：意图好但覆盖面有限，需与 sandbox 网络策略配合才完整。

---

## 10. settings 砖 — 设置持久化（核心砖）

| 维度 | 评分 | 证据与点评 |
|------|:----:|------|
| 功能完整性 | ⭐⭐⭐⭐ | GET/POST + 一次性迁移旧设置（`_migrate_once`）。 |
| 接口设计 | ⭐⭐⭐⭐ | 非 dict 入参 400。 |
| 错误处理 | ⭐⭐⭐⭐ | 原子写（tmp+`os.replace`），类型校验。 |
| 安全性 | ⭐⭐⭐ | `GET /api/settings` **未挂鉴权**（但本机应用，风险可控）。 |
| 持久化 | ⭐⭐⭐⭐⭐ | `settings.json` 原子写 + crypto 加密联动 + 迁移桥。 |
| 模块化 | ⭐⭐⭐⭐ | 导出 `load_app_settings` 供 usage 读配额。 |
| 可观测性 | ⭐⭐ | 无。 |
| 可扩展性 | ⭐⭐⭐ | 无字段级 schema 校验。 |

**结论**：持久化稳健，建议补字段级校验与 GET 鉴权。

---

## 11. usage 砖 — Token 用量计量

| 维度 | 评分 | 证据与点评 |
|------|:----:|------|
| 功能完整性 | ⭐⭐⭐⭐⭐ | `GET /api/token-usage` 支持 start/end/model/provider/limit 过滤；台账 + 按天/月聚合 + 逐请求明细。 |
| 接口设计 | ⭐⭐⭐⭐⭐ | 过滤维度丰富，符合「成本归因」最佳实践。 |
| 错误处理 | ⭐⭐⭐⭐ | 损坏 JSON 静默返回空；`threading.Lock` + 原子写。 |
| 安全性 | ⭐⭐⭐ | `GET /token-usage` 未挂鉴权（本机应用）。 |
| 持久化 | ⭐⭐⭐⭐⭐ | `tempfile.mkstemp`+`fsync`+`os.replace` 原子写 + 锁，62天/13月/5000条裁剪。 |
| 模块化 | ⭐⭐⭐⭐⭐ | 导出 `check_quota/record_usage`，被 chat 流末调用。 |
| 可观测性 | ⭐⭐⭐⭐ | 逐请求明细 + 聚合，具备 FinOps 雏形。 |
| 可扩展性 | ⭐⭐⭐⭐ | 可加按用户/功能维度。 |

**结论**：计量架构最接近业界「四层 Token 记账 + 网关级计量」标准，是亮点砖。

---

## 12. adjudicator 砖 — 规则驱动裁决引擎

| 维度 | 评分 | 证据与点评 |
|------|:----:|------|
| 功能完整性 | ⭐⭐⭐⭐⭐ | `AdjudicationEngine` 按优先级降序、首条命中即返回；Rule 模型（trigger+conditions+actions）；14 种算子；CRUD + 元数据端点 + 默认规则。 |
| 接口设计 | ⭐⭐⭐⭐⭐ | 端点语义清晰，返回可读拒绝原因。 |
| 错误处理 | ⭐⭐⭐⭐ | `validate_rule` 阈值校验；`ask` 超时默认 deny（fail-closed）。 |
| 安全性 | ⭐⭐⭐⭐⭐ | **无 eval/exec**，正则 `re.search` 已 try/except；`ask` 默认拒绝——对标 OPA「失败默认拒绝」。 |
| 持久化 | ⭐⭐⭐ | 规则加载，默认规则自 yaml。 |
| 模块化 | ⭐⭐⭐⭐⭐ | 导出 `check_action` 被 agent 砖调用，无硬编码依赖。 |
| 可观测性 | ⭐⭐⭐ | 无评估日志（建议补）。 |
| 可扩展性 | ⭐⭐⭐⭐⭐ | 运行时 add/remove 规则。 |

**结论**：**安全性设计最规范**（对标 OPA 策略即代码），是 agent 砖的安全护栏。

---

## 13. sandbox 砖 — 代码沙箱

| 维度 | 评分 | 证据与点评 |
|------|:----:|------|
| 功能完整性 | ⭐⭐⭐⭐ | 多语言 auto/python/node/bash/pwsh/cmd；网络代理拦截；蜜罐诱饵 env。 |
| 接口设计 | ⭐⭐⭐⭐ | `RunRequest`/`AnalyzeRequest` 清晰，`SandboxResponse` 结构完整。 |
| 错误处理 | ⭐⭐⭐⭐ | 空代码/解释器缺失均返回明确错误；fallback 模式标记 `isolation`。 |
| 安全性 | ⭐⭐⭐⭐ | **进程级隔离**（Job Objects/ctypes 强杀）+ 网络代理 + 蜜罐。但**非容器/VM**，共享主机内核，存在逃逸风险；缺 pywin32 降级 `fallback` 隔离更弱。 |
| 持久化 | ⭐⭐ | 临时执行，无需持久化（设计正确）。 |
| 模块化 | ⭐⭐⭐⭐ | 导出 `run_code/analyze_code`。 |
| 可观测性 | ⭐⭐⭐ | `network`/`honeypot` 字段回传。 |
| 可扩展性 | ⭐⭐⭐⭐ | 语言自动检测，`sandbox_mode` 开关。 |

**结论**：比裸 `exec` 强很多，但业界建议容器级隔离（seccomp/read-only/network none/gVisor）。属「够用但有上限」。

---

## 横向总评

### 维度均分排行（越高越好）

| 维度 | 均分 | 整体评价 |
|------|:----:|------|
| 模块化/解耦 | 4.2 | **最强项**——hybrid capabilities 设计贯穿全局，无跨砖硬依赖。 |
| 持久化 | 3.8 | storage/usage/settings 原子写 + 锁，扎实。 |
| 接口设计 | 3.9 | 端点规范，错误码 parse/adjudicator 最标准。 |
| 错误处理 | 3.8 | 多数砖有降级/兜底，file 砖最弱。 |
| 可扩展性 | 3.5 | agent/adjudicator/models 可热插拔，存储类偏固定。 |
| 功能完整性 | 4.0 | 各砖领域覆盖到位。 |
| 可观测性 | 2.4 | **最弱项**——仅 usage/chat 有量化，全局缺结构化日志/trace。 |
| 安全性 | 3.4 | 中上，但 file 无校验、离线可绕过、沙箱非容器、只读端点缺鉴权。 |

### 砖块综合评级

| 砖块 | 综合 | 一句话 |
|------|:----:|------|
| storage | S | 原子写 + 能力化基石 |
| usage | S | 计量架构对标 FinOps 标准 |
| adjudicator | S | 安全设计对标 OPA |
| chat | A+ | 核心 backbone 稳健 |
| models | A+ | 多供应商抽象规范 |
| parse | A | 错误码最标准 |
| ollama | A | 本地模型管理完整 |
| conversations | A- | 瘦砖职责清晰 |
| crypto | A- | 国密合格，单要素绑定是权衡 |
| sandbox | A- | 进程级隔离够用有上限 |
| settings | A- | 持久化稳健 |
| offline | B+ | 意图好但覆盖面有限 |
| file | C+ | **安全短板最明显，需优先补** |

### 跨砖共性短板（建议统一治理）
1. **可观测性**：建议引入统一结构化日志（JSON 日志 + request_id），关键砖补 trace。
2. **只读端点鉴权**：`GET /settings`、`/storage/files`、`/stats`、`/token-usage`、`/offline` 等未挂 `require_api_token`，本机应用风险可控但建议统一。
3. **file 砖**：补类型 allowlist（magic bytes）、大小/数量限制、静态服务鉴权。
4. **offline 砖**：与 sandbox 网络策略联动，覆盖 requests/urllib/socket 旁路。
5. **sandbox 砖**：评估升级容器级隔离（Docker + seccomp + read-only + network none）。

> 总体：13 砖模块化与持久化达生产级；可观测性与部分安全面是主要提升空间。file 砖安全短板最突出，建议优先处理。

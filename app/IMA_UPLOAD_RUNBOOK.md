# P.A.L.M → ima 知识库 上传手册（可复用）

> 本文件记录"把 P.A.L.M 项目文档上传到腾讯 ima 知识库"的标准流程。初版 2026-09-05，同日上传完成后更新。

## 目标知识库（ima App 内，连接器无创建接口，需手动建）

| 库名 | ID | 状态 |
|---|---|---|
| 服务器 | `7500202726421701` | **现用**。2026-08-31 建，2026-09-05 收下全部 92 篇 P.A.L.M 文档 |
| 寂灭·战灵的知识库 | `001a517f53000e3b` | 个人主库，119 条 |
| ~~P.A.L.M~~ | ~~`7495141367512273`~~ | **已删除**。2026-09-05 复查时不在个人库列表内，`add_knowledge` 返回「知识库已删除」（`has_deleted:true`）。已在客户端删除，MCP 无恢复接口 |

> 教训：上传前先 `get_knowledge_base_list` 确认目标库仍在列表内。对已删除的库 `get_knowledge_list` 仍会返回库信息（条目为空），**只有 `add_knowledge` 会报错**，容易白跑一轮。

## 连接器：ima-mcp

- 地址：`https://ima.qq.com/mcp`，类型 `streamableHttp`。
- 若 `disabled: true`：编辑 `C:\Users\Dawn\.workbuddy\connectors\*\mcp.json`，把 `"connector:ima-mcp": { ... "disabled": true }` 改为 `false`（改前先备份）。写 `.workbuddy/connectors/` 需关闭沙箱。
- **关键坑 1**：MCP 工具按**会话启动**时注册。中途才 Trust 连接器，本会话工具集不会热加载，必须开新会话。验证：`DeferExecuteTool` 调 `mcp__ima-mcp__get_knowledge_list` 报 not found 即未加载。
- **关键坑 2**：鉴权头在配置里是 AES-GCM 加密的（`headerOverrides/ima-mcp/Authorization` 的 iv/tag/ct），**无法读出明文去直连 HTTP 批量化**。批量只能靠并行子代理分片跑 MCP 工具，别想着绕。

## 依赖

- `cos-python-sdk-v5` 装在默认 venv：`C:\Users\Dawn\.workbuddy\binaries\python\envs\default\Scripts\python.exe`
- `upload_cos.py`：单文件上传，参数 `<file> <cos_key> <bucket> <region> <token> <secret_id> <secret_key> [content_type]`，成功回显 `UPLOAD_OK <ETag>`
- `batch_cos_upload.py`：批量上传，读 JSON 凭证数组，`python batch_cos_upload.py [creds_json_path]`，默认读 `_batch_creds.json`

## 上传流程（每篇三步，缺一步不算入库）

1. **create_media**：`mcp__ima-mcp__create_media`，传 `knowledge_base_id` / `file_name` / `file_ext` / `file_size` / `content_type`。返回 `media_id` + `cos_credential`（`cos_key`、`bucket_name`、`region`、`token`、`secret_id`、`secret_key`）。凭证有效期约 12 小时。
2. **推 COS**：`batch_cos_upload.py`，凭证数组元素字段：
   `{"name","path","cos_key","bucket","region","token","secret_id","secret_key","content_type"}`
3. **入库**：`mcp__ima-mcp__add_knowledge`，传 `knowledge_base_id` + `media_id`。

**注意**：`media_id` 后缀带知识库 ID，换库必须重新 create_media，旧 media_id 不能复用。

## 大批量做法（90+ 篇）

单篇串行会撑爆上下文（每篇约 1.5k token）。实测可行方案：

1. 先生成 `_worklist.json`：`[{order, name, path, size}]`，`size` 取磁盘实际字节数（清单里的字节数可能与磁盘不符，以磁盘为准）。
2. 按 order 切片，启 3 个 general-purpose 子代理并行跑，每片约 31 篇，每批 8 篇。
3. 每个子代理用**独立的**凭证文件与状态文件（`_creds_A/B/C.json`、`_state_A/B/C.json`），避免互相覆盖。
4. 子代理提示词里必须写明：先 `ToolSearch` 加载工具 schema 再用 `DeferExecuteTool` 调用，否则报 not found。
5. 跑完删掉 `_creds_*.json`（含 STS 临时密钥）。

## 2026-09-05 上传结果

- 清单：`_upload_manifest.json`，92 篇 = 91 篇原始文档（`_all_raw_docs/`）+ 1 篇统一合并文档 `P.A.L.M_全量文档合并_20260905.md`（1,751,741 字节）
- 结果：**92/92 全部入库**，0 失败。3 片各 31 / 31 / 30 篇
- 核验：`get_knowledge_list` 的 `knowledge_total_size` 由 **12 → 104**（+92）
- 解析验收（2026-09-05 16:00 复查）：用 `MEDIA_STATE_FILTER_TYPE` 过滤 `PARSE_ERROR/PARSE_TIMEOUT/INIT/PARSING` **翻完全部游标均为空**，且 `PARSE_SUCCESS` 过滤能返回条目（证明过滤器本身有效）→ 92 篇全部解析成功
- 检索验收：`search_knowledge` 查「好感度系统」命中 100 个标题，含统一文档 `P.A.L.M_全量文档合并_20260905.md` → 已索引、可问答
- 统一文档未被体积限制拒绝，1.75 MB 可正常入库

## 已知缺失（本环境无法补）

- 桌面级 4 个运维 md 已在 2026-09-04 清理中被删：`服务器_架构与运维总览.md`、`服务器_运维凭据与坑速查.md`、`PALM_内网地址清单.md`、`PALM_PVE状态快照_20260831.md`。
  - 注：清单里 `023/024/026/047/048` 号文档标题与这些同名，但内容来自 `docs/` 目录副本，可作为替代。

## 操作口诀

"先查库还在不在 → 连接器 Trust 后开新会话（工具才加载）→ 生成 worklist → 子代理分片 create_media→batch 推 COS→add_knowledge → 删临时凭证 → 用 total_size 增量核验"。

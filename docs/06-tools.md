# 砖块设计文档 - 06 tools 砖（工具注册与语义匹配）

> 版本：v1.0（2026-08-13）
> 路径：`backend/app/bricks/tools/`
> 定位：所有工具的统一注册、调用、语义匹配

---

## 功能支持

tools 砖承载 LLM 可调用工具的注册中心 + 语义匹配引擎 + 沙箱包装。

### 6.1 核心能力

| 能力 | 入口 | 行为 |
|---|---|---|
| 注册工具 | `registry.register(tool)` | 加入工具池 + 重建匹配索引 |
| 列出工具 | `registry.list_tools()` | 返回工具列表 |
| 按名调用 | `registry.call(name, **kwargs)` | 同步调用，返回结果 |
| 流式调用 | `registry.stream(name, **kwargs)` | 流式输出（部分工具） |
| 工具 schema 导出 | `registry.openai_schema()` | 生成 OpenAI functions 格式 |
| 语义匹配 | `matcher.search(query, top_k)` | 按 query 找最相关工具 |
| 工具自动过滤 | `auto_filter(query, k=10)` | 按用户意图缩减工具集 |
| 沙箱执行 | `sandbox.execute(tool, args)` | 经 safety 砖 + 沙箱砖过滤 |
| 工具白名单/黑名单 | `registry.allow / deny` | 硬约束 |

### 6.2 工具分类

| 类别 | 例子 | 风险等级 |
|---|---|---|
| 读取类 | `read_file` / `list_dir` / `search_web` | 低 |
| 写入类 | `write_file` / `edit_file` / `send_email` | 中 |
| GUI 类 | `click` / `type_text` / `screenshot` | 中 |
| 系统类 | `run_command` / `kill_process` | 高 |
| 网络类 | `http_get` / `http_post` | 中 |
| 业务类 | GUI 自动化（自动化执行器） | 中 |
| 安全类 | 加密 / 解密 | 低 |

### 6.3 创新设计

- **统一 spec**：所有工具继承 `ToolSpec`（name / description / parameters / returns / risk_level）
- **语义匹配而非字符串匹配**：`matcher.search` 基于 embedding 找最相关工具
- **沙箱包装**：所有工具调用经 sandbox 砖 + safety 砖双重过滤
- **auto_filter**：根据用户 query 自动过滤不相关工具，节省 token
- **动态索引**：注册新工具时自动重建匹配索引
- **失败 fail-soft**：工具调用失败返回错误信息而非抛异常（Agent 可处理）

---

## 架构组成

```
tools 砖
├── brick.py            # 砖块入口
├── registry.py         # 工具注册表
├── matcher.py          # 语义匹配器
├── spec.py             # 工具规格定义
├── sandbox_wrapper.py  # 沙箱包装
├── builtin/            # 内置工具
│   ├── file_tools.py
│   ├── gui_tools.py
│   ├── web_tools.py
│   └── system_tools.py
└── openai_adapter.py   # OpenAI function calling 格式转换
```

---

## 关键设计决策

### 决策 1：统一 ToolSpec
所有工具继承同一规格（`ToolSpec` 协议），强制约束名称、描述、参数、返回、风险等级。

### 决策 2：语义匹配 + auto_filter
LLM 一次可见工具数 50+ 会爆 token，auto_filter 按 query 过滤到 top 10。

### 决策 3：沙箱双重过滤
所有工具调用先过 sandbox 砖（资源限制），再过 safety 砖（命令黑名单）。

### 决策 4：流式工具
GUI 工具、文件读取大文件等支持流式输出，调用方按 token 增量消费。

### 决策 5：失败 fail-soft
工具调用失败返回结构化错误，AgentCore 据此决定重试 / 换工具 / 放弃。

---

## 依赖关系

| 上游依赖 | 用途 |
|---|---|
| memory 砖 | 工具调用历史 |
| safety 砖 | 命令过滤 |
| sandbox 砖 | 资源限制 |
| models 砖 | Embedding（语义匹配） |

| 下游消费者 | 用途 |
|---|---|
| agent 砖 | 调用工具 |
| gui 工具集 | GUI 自动化 |
| 业务工具集 | 业务能力 |

---

## 性能与边界

- 单次工具调用超时：30s
- 流式工具首 chunk 延迟：< 200ms
- 语义匹配 top_k：默认 5
- auto_filter 默认保留 10 个工具

---

## 未决问题与演进

- 工具调用失败重试策略
- 工具组合（chain / parallel）
- 工具权限分级（基于用户角色）

---

## 相关文档

- `docs/全项目功能支持设计说明书.md`（总文档）
- `backend/app/bricks/tools/brick.py`（砖块入口）

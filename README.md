# P.A.L.M

> 桌面 AI 助手系统的全盘工程仓库 —— 自研微内核 + 可插拔砖块 + 原生前端。

P.A.L.M 不走「一个大框架包打天下」的路子，而是把一个 AI 助手拆成**互相不耦合的内嵌独立项目**：
每个内核件、每块能力都是一个自带源码、可单独拷走的目录，靠 `palm_boot.py` 在运行时挂进 `sys.path`，
不需要 `pip install`，也不存在包版本地狱。

---

## 一、仓库结构

```
P.A.L.M/
├── 1_Demo_LLM/          内核区（内嵌独立项目，各自完整）
│   ├── LLM内核/         palm_llm —— 多厂商流式调用微内核 + 对话服务层
│   ├── 记忆/            palm_memory —— 零依赖记忆层
│   ├── 加解密内核/      palm_cryptokernel —— 统一加解密
│   └── audit_gpt_sovits/ GPT-SoVITS 精简裁剪的代码质量审计基线
├── 2_实验/              砖块实验区（16 个 palm_* 独立包）
├── 3_文档/              开发日志 / 项目文档 / 知识库
├── 4_组件/              非 Python 的独立组件
│   └── 网卡模块/        @palm-ai/netcard —— fail-closed 门面 + 安全管道
├── 4_工具/              运维工具链
│   ├── PALM脚本/        archiver / authsync / palmfs / palmfs3
│   ├── PALM_Backup/     冷备份脚本
│   └── PALM_Mount_Scripts/ SMB 共享挂载脚本（已脱敏）
├── app/                 自举与启动
│   ├── palm_boot.py     sys.path 自举内核
│   ├── P.A.L.M一键启动.bat
│   └── Dockerfile / docker-compose.yml / requirements.txt
├── webui/               前端（原生 ES Modules，无构建步骤）
├── README.md
└── LICENSE              Apache-2.0
```

---

## 二、内核件

### LLM 内核 `palm_llm`

多厂商流式调用的微内核，按 `cfg.type` 分发四种协议，未实现的 type 一律回落 `openai_compat`：

| 协议 | 端点 | 关键差异 |
|---|---|---|
| `openai_compat` | OpenAI 兼容 | 默认通道，覆盖绝大多数厂商与网关 |
| `anthropic` | `/v1/messages` 原生 | system 外提、`max_tokens` 必填、块级 SSE、原生缓存 token、`output_config.effort` |
| `ollama` | `/api/chat` 原生 | `think` 一等参数、思维链在 `message.thinking`、返回分段耗时 |
| `gemini` / `google` | `generateContent` 原生 | 只有 user/model 两角色、`parts[]`、`systemInstruction`、无 `[DONE]` 收尾、3 系列与 2.5 系列思考参数两套并存 |

设计要点：

- **能力矩阵前置拦截**：发请求**前**按模型能力挡掉注定失败的调用。三条铁律 —— 只拦已知不支持、只看内核 `Message` 不看各家方言、报错必须可照着改。
- **文本工具调用降级**：模型不支持原生工具时，走文本协议解析回填。
- **思考块回传契约**：思维链在多轮之间原样回传，避免二次污染。
- 自带 15 个单测与网关对照基准（`bench/gateway/`）。

### 记忆层 `palm_memory`

零依赖实现，刻意不引入向量库与嵌入服务：

- `domain_memory/core_memory.py` —— 核心记忆
- `domain_memory/archived_memory.py` —— 归档记忆
- `domain_memory/memory_writer.py` —— 写入策略
- 附 `selftest.py` / `usability_test.py` / `一键自检.py`，可离线验证

### 加解密内核 `palm_cryptokernel`

按**密码学家族**而不是按算法组织：`aead` / `cipher` / `envelope` / `hash` / `kdf` / `mac` / `pubkey`，
配 `backends.py` 做后端换装、`capabilities.py` 做能力探测，附并发与安全审计基准。

---

## 三、砖块实验区 `2_实验/`

16 个能力砖块，每个都是一个可独立运行的 `palm_*` 包：

| 目录 | 包 | 职责 |
|---|---|---|
| 智能体框架 | `palm_agent` | ReAct 循环 + 计划 + 工具调度 |
| 计划引擎 | `palm_plan` | 任务拆解与推进 |
| 工具集 | `palm_tool` | 工具注册与调用 |
| GUI自动化 | `palm_gui` | 桌面自动化执行器 |
| 显示层 | `palm_display` | 桌面部件与渲染 |
| 存储芯片 | `palm_storage` | 介质层 + 管理芯片 |
| 安全 | `palm_security` | 权限与策略 |
| 沙箱 | `palm_sandbox` | 隔离执行 |
| 模型适配 | `palm_model` | 模型能力与参数适配 |
| Ollama嵌入 | `palm_ollama` | 本地模型管理与嵌入 |
| 词元预算 | `palm_budget` | token 配额分配 |
| 游戏生态 | `palm_game` | 货币 / 道具 / 经验 / 角色卡 |
| 自主进化 | `palm_evolution` | 自主优化 |
| 受控进化 | `palm_evolution_ctl` | 进化过程的约束与审批 |
| 运维服务 | `palm_ops` | 服务编排 |
| IO适配 | `palm_io` | 输入输出通道 |

---

## 四、快速开始

### 前端

```bat
webui\启动WebUI.cmd      :: 后台起服务（端口 5173，内核 10093），自动开浏览器
webui\状态.cmd           :: 查状态
webui\停止WebUI.cmd      :: 停服务
```

页面是原生 ES Module，**没有构建步骤**；但不能直接双击 `index.html`（`file://` 下模块被 CORS 拦），必须走本地 http 服务。

### 后端

```bat
app\P.A.L.M一键启动.bat
```

### 在代码里用内核件

```python
import palm_boot              # 首次 import 即把内嵌项目挂进 sys.path
from palm_llm import ...      # 之后按包名正常导入
```

`palm_boot` 会自动向上逐层探测布局，兼容 `1_Demo_LLM/`、`2_实验/` 数字容器布局，
所以整个目录可以直接拷走，不需要改代码。

### 容器

```bash
docker compose -f app/docker-compose.yml up
```

---

## 五、文档索引

| 位置 | 内容 |
|---|---|
| `1_Demo_LLM/LLM内核/docs/` | LLM 内核架构 v1.0→v1.5、供应商协议差异、能力矩阵、思考块契约、网关对照实验 |
| `1_Demo_LLM/LLM内核/README.md` | 内核能力与用法详解 |
| `1_Demo_LLM/记忆/使用说明.md` | 记忆层接口与自检方法 |
| `1_Demo_LLM/加解密内核/docs/` | 安全与性能审计、C 后端换装基准 |
| `3_文档/项目文档/` | 整体架构、GUI 执行器、世界模型、RAG、全局体检报告 |
| `3_文档/开发日志/` | 逐日开发日志与项目记忆 |
| `3_文档/知识库/` | 结构化知识库（总览 / 演进史 / 架构白皮书 / 模块复刻级解析） |
| `4_组件/网卡模块` | 见 `3_文档/项目文档/网卡模块归档.md` |

---

## 六、安全说明

本仓库为公开仓库，推送前已做脱敏：

- 运维凭据（SMB / PVE / 网关账号口令）已替换为 `[REDACTED_PASSWORD]`、`[REDACTED_ACCOUNT]`；
- 含明文口令的原始文档仅保留脱敏版，真实凭据不入库；
- `.env`、虚拟环境、模型权重、构建产物、缓存、日志均在 `.gitignore` 中排除；
- 归档区（`8_归档/`，含历史 `.env` 与基准数据集）不入库。

若需实际部署，请自行以 `app/.env.example` 为模板填写本地凭据。

---

## 七、许可证

Apache License 2.0，见 [LICENSE](LICENSE)。

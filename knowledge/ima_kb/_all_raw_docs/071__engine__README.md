# AI 对话（多模型 · 终端 UI 客户端）

一个本地运行的 AI 对话程序，基于 Python + `backend` 后端实现。**默认以命令行（CLI）方式使用**，可选**终端 UI（`--tui`，基于 [Textual](https://textual.textualize.io/)）**。支持流式输出与**单次提问**。

可接入**国内外大多数大模型 API**，所有配置与对话历史以 **JSON 文件**持久化。

> **Web UI 已加入**：`web.py`（零额外依赖的 stdlib 服务端）+ `frontend/`（原生 HTML/JS）。原 `app.py` 与旧 `frontend/` 仍归档在 `_webui_backup/` 以备参考。

## 功能特性

- **广覆盖的模型接入**：以 OpenAI 兼容协议为主（覆盖绝大多数国内外厂商），并为 Anthropic(Claude)、Google Gemini 提供原生适配。
- **可选终端 UI（`--tui`）**：消息气泡（用户=青、AI=品红并渲染 Markdown、系统=黄/红）、流式逐字渲染、可滚动历史；`Ctrl+C` 中断生成、`Ctrl+Q` 退出。
- **命令行交互（默认）**：流式打字机式输出；斜杠命令管理会话、切换模型、调节参数。
- **多会话管理**：多个对话并行，历史持久化于 JSON。
- **多模态 / 附件**：通过 `/image` 为下一条消息附加本地图片，调用视觉模型（GPT-4o、通义 VL、Gemini、Claude 等）。
- **对话导出 / 导入**：导出为 JSON 或 Markdown，便于备份与迁移。
- **纯本地、无鉴权**。

## 目录结构

```
ai-chat/
├── chat.py                # 入口：默认命令行交互，--tui 启动终端 UI，位置参数为单次提问
├── web.py                 # ★ Web UI 服务端（stdlib http.server，SSE 流式 + 静态托管）
├── chat_tui.py            # Textual 终端 UI 实现（可选，--tui 启用）
├── config.json            # 长期存储：提供方、模型、参数、系统提示词
├── requirements.txt
├── start.bat              # Windows 一键启动（自动建 venv + 装依赖）
├── backend/
│   ├── models.py          # Pydantic 数据模型
│   ├── config.py          # config.json 读写
│   ├── storage.py         # 会话 CRUD + 导出/导入
│   ├── chat.py            # 消息组装、流式调度、落盘
│   └── providers/         # OpenAI兼容 / Anthropic / Gemini 适配器
├── frontend/              # ★ Web UI 前端
│   ├── index.html / style.css / app.js
│   └── vendor/            # marked / DOMPurify / highlight.js（离线可用）
└── data/
    ├── conversations/     # 会话历史 JSON
    └── uploads/           # 图片附件
```

## 快速开始

### Windows
双击 `start.bat`（会自动创建 `.venv` 并安装依赖），即可进入终端 UI。

### 手动运行（任意平台）
```bash
python -m venv .venv
.venv/Scripts/activate        # Windows
# source .venv/bin/activate   # macOS / Linux
pip install -r requirements.txt
python chat.py                # 启动命令行交互（默认）
python chat.py --tui          # 启动终端 UI（可选）
```

### 常用用法
```bash
python chat.py                       # 启动命令行交互（默认）
python chat.py --tui                # 启动终端 UI（可选）
python chat.py "用一句话解释量子纠缠"  # 单次提问后退出
python chat.py --config              # 打印当前配置
python chat.py --list                # 列出会话
python chat.py --provider ollama --model llama3.1 "hi"   # 临时指定提供方/模型
```

### Web UI（浏览器对话 + Markdown 渲染）★

无需额外安装（仅用 Python 标准库），启动后浏览器打开即可对话，助手回复按 **Markdown 渲染**（标题/列表/代码块/表格/引用 + 代码高亮）。

```bash
python web.py                 # 默认 http://127.0.0.1:8080
python web.py --port 9000     # 自定义端口
```

打开页面后：
- 左侧新建 / 切换会话；右上角 ⚙ 设置提供方、模型、API Key、系统提示词与参数（Key 明文存于 `config.json`，GET 接口自动遮罩）。
- 输入框 Enter 发送、Shift+Enter 换行；🖼 可上传图片走多模态。
- 助手消息实时流式渲染为 Markdown；`data/conversations/seed_md_01.json` 是一条内置的 Markdown 渲染演示会话，可在侧栏点击查看效果。

> 即开即用：`web.py` 直接驱动 `backend` 包调用**真实 API**（默认 `zhipu / glm-4.6v`，Key 已在 `config.json`）。
> 注意：本程序无鉴权，请勿在公网直接暴露端口。

## 引导式配置提供方（推荐）

新增一个提供方最简单的方式是交互式命令 `/addprovider`（或别名 `/connect`）：

1. 输入 `id`（如 `deepseek`）、显示名、类型（`openai_compat`/`anthropic`/`gemini`）；
2. 输入 `base_url`（请求地址，如 `https://api.deepseek.com/v1`）与 `api_key`；
3. 程序**自动检测连通性**并向远端拉取**模型列表**（OpenAI 兼容走 `/models`，Anthropic/Gemini 走各自端点）；
4. 列出所有模型，由你**选择要保留的模型**（序号 / 逗号分隔 / 区间 `1,3-5` / `all`）；
5. 自动保存，并设为当前提供方与默认模型。

若检测失败（地址/密钥问题），会给出可读错误并允许你改为手动输入模型名；若无需联网探测（如本地 Ollama），留空地址/密钥即可手动填写模型。

> 非交互场景（管道 / TUI）也可用 `/addprovider <id> <type> <key> [models_csv]` 直接传参。

## 终端 UI 操作（仅 --tui 模式）

- 底部输入框直接打字，`Enter` 发送，空行忽略。
- 以 `/` 开头的输入视为命令（如 `/help`、`/config`、`/exit`）。
- `Ctrl+C`：中断当前正在生成的回复。
- `Ctrl+Q`：退出程序。

## 交互 / TUI 命令

| 命令 | 说明 |
|------|------|
| `/help` | 显示帮助 |
| `/new` | 新建会话 |
| `/list` | 列出所有会话 |
| `/switch <id>` | 切换到指定会话 |
| `/delete <id>` | 删除会话 |
| `/config` | 显示当前配置 |
| `/provider <id>` | 切换当前提供方 |
| `/model <model>` | 切换当前模型 |
| `/system <prompt>` | 设置系统提示词（省略参数查看当前） |
| `/param <k> <v>` | 设置参数（temperature/top_p/max_tokens/frequency_penalty/presence_penalty） |
| `/addprovider` 或 `/connect` | 引导式添加提供方：输入 key + 地址后**自动检测连通性、拉取模型列表**，由你选择模型后保存 |
| `/setkey <id> <key>` | 设置某提供方的 API Key |
| `/export [id] [fmt]` | 导出会话到 `<id>.<fmt>`（fmt=json\|md，默认 json） |
| `/import <file>` | 从文件导入会话 |
| `/image <path...>` | 为下一条消息附加图片（可多个） |
| `/clearimg` | 清除待发送的图片 |
| `/exit`、`/quit` | 退出 |

## 配置模型

首次使用前需配置 API Key（密钥仅保存在本地 `config.json`）：

- 交互中：用 `/addprovider` 添加提供方，用 `/setkey <id> <key>` 填写密钥；
- 或直接编辑 `config.json` 的 `providers` 中对应条目的 `api_key`。

### 各厂商接入要点

绝大多数国产 / 海外模型都提供 **OpenAI 兼容** 端点，只需在 `config.json` 的 `providers` 中把 `type` 设为 `openai_compat` 并填写 `base_url`、`api_key`、`models` 即可，**无需改代码**。常见示例：

| 提供方 | type | base_url | 备注 |
|--------|------|----------|------|
| OpenAI | openai_compat | `https://api.openai.com/v1` | |
| DeepSeek | openai_compat | `https://api.deepseek.com/v1` | |
| 通义千问 | openai_compat | `https://dashscope.aliyuncs.com/compatible-mode/v1` | |
| 智谱 GLM | openai_compat | `https://open.bigmodel.cn/api/paas/v4` | |
| 豆包/火山 | openai_compat | `https://ark.cn-beijing.volces.com/api/v3` | |
| Kimi | openai_compat | `https://api.moonshot.cn/v1` | |
| Ollama(本地) | openai_compat | `http://localhost:11434/v1` | api_key 填 `ollama` |
| Claude | anthropic | `https://api.anthropic.com/v1` | 原生适配 |
| Gemini | gemini | `https://generativelanguage.googleapis.com/v1beta` | 原生适配 |

新增厂商：在 `config.json` 的 `providers` 追加一条即可（兼容型无需改代码；若需全新协议，参考 `backend/providers/` 下的适配器新增一个类）。

## 说明

- 本程序为本地工具，未做任何鉴权。
- 对话历史位于 `data/conversations/`，可直接用文本编辑器查看或备份。
- 终端 UI 需要支持 ANSI/真彩的终端（Windows Terminal、现代 macOS/Linux 终端均可）。

---

## 代码沙箱（物理隔离 + 透明网络拦截）

> 启用后 `/api/run` 会真实执行 python/node/bash，并执行前先经 **AST 静态分析**；
> 所有出网流量默认**断网**，经由本地拦截代理**挂起**等待用户裁决，且具备**流量配额熔断**。

### 架构

```
AI 生成代码
   │  (经受限账户 + Job Objects 隔离执行，见 sandbox_run.py)
   ▼
进程注入 HTTP(S)_PROXY=127.0.0.1:18100
   ▼
sandbox_net.NetInterceptor（透明代理）
   ├─ 新目标  → 挂起连接 + 推入待审队列（不拒绝/不超时）
   ├─ 用户裁决 → allow_once / allow_session / allow_permanent（白名单）
   └─ 配额超限 → 熔断，切断全部连接
```

- **默认断网**：沙箱进程所有出网默认关闭；仅代理回环放行（防火墙规则 best-effort）。
- **透明拦截**：应用层代理捕获遵循代理协议的流量（pip / requests / urllib / curl 等）。
  原始 socket 直连由防火墙默认拒绝（无法「挂起」，但仍默认断网）。真正 L3/L4 全量拦截
  需 WFP 驱动，已在 `FirewallManager` 预留扩展点。
- **用户授权交互**：`/api/net/pending` 暴露待审请求（目标 IP、域名、端口、PID），
  UI（见 `frontend/sandbox_console.html`）弹窗让用户对具体 IP/域名做三种裁决：
  - `allow_once`：仅本次连接放行；
  - `allow_session`：本次会话内该目标始终放行（进程内，重启清零）；
  - `allow_permanent`：**写入持久白名单** `sandbox/net_allow.json`，重启后仍生效。
- **白名单策略**：未知目标持续断网并挂起待审；命中 `allow_permanent` 白名单的目标
  直接放行且无需用户确认。白名单为默认安全兜底之外的「永久放行」例外集。
- **流量配额与熔断**：`/api/net/quota` 设置硬上限（默认 20MB），超限自动切断所有连接。
- **扩展接口**：
  - `sandbox_ast.analyze(lang, code)` —— 执行前 AST 预分析，提取网络地址/危险系统调用。
  - `sandbox_threat.check(host, ip)` —— 可插拔目标威胁评分（默认本地规则库，
    可 `set_backend()` 接入外部 API）。
  - `sandbox_threat.check_url(url)` —— **URL 沙箱异常检测**（见下），可 `set_url_backend()` 覆盖。

### 启动

```bash
# 仅代理拦截 + 降级隔离（无需管理员，推荐先验证）
.venv/Scripts/python.exe web.py --port 8080 --sandbox

# 真实物理隔离（需管理员 + pywin32，新建受限账户 sandbox_runner）
# 以管理员运行：
set SANDBOX_USER=sandbox_runner
pip install pywin32
.venv/Scripts/python.exe web.py --port 8080 --sandbox
```

> 本机为 Windows 10/11 **非 Hyper-V / 无 Windows Sandbox**，故选用「受限独立账户 + Job 对象」
> 作为物理隔离方案（该环境不可得 VM 级隔离）。`sandbox_run.py` 在无 pywin32/非管理员时
> 自动降级为「当前用户 + 超时 + 代理出网」，网络拦截仍然生效。

### 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/api/net/pending`   | 当前待审网络请求列表 |
| POST | `/api/net/decision`  | `{"id","verdict"}` 裁决（allow_once/allow_session/allow_permanent） |
| GET  | `/api/net/policy`    | 配额/策略快照（含白名单 allow_permanent、会话允许 allow_session、防火墙状态） |
| POST | `/api/net/quota`     | `{"limit": 字节}` 设置流量硬上限 |
| POST | `/api/sandbox/analyze` | `{"lang","code"}` 执行前 AST 预分析 |
| GET  | `/api/net/threat`    | `?host=&ip=` 威胁评分 |
| GET  | `/api/net/url-check` | `?url=` URL 沙箱异常检测（明文凭据/内网IP/可疑TLD/同形字符/非标准端口等） |
| POST | `/api/run`           | 隔离执行代码（proxy 出网 + 附 AST 分析） |

### URL 沙箱异常检测

`sandbox_threat.check_url(url)` 解析完整 URL 并检测以下异常项（每项贡献风险评分，
最终 level：high ≥ 70 / medium ≥ 40 / low < 40）：

| 异常 | 检测项 | 触发示例 |
|------|--------|----------|
| `credentials_in_url` | URL 含明文 `user:pass@` | `http://user:pass@host/` |
| `private_ip_literal` | 直接使用内网/保留 IP 字面量 | `http://192.168.1.1/` |
| `loopback_ip` | 回环地址 | `http://127.0.0.1/` |
| `private_resolved` | 域名解析到内网地址 | 解析 IP ∈ RFC1918 |
| `internal_tld` | 内网域名后缀 | `.local` / `.internal` / `.lan` |
| `suspicious_tld` | 高风险 TLD（钓鱼/垃圾站常见） | `.tk` `.top` `.xyz` `.zip` 等 |
| `homoglyph` | 同形字符（西里尔字母伪装） | `exаmple.com`（а 为西里尔） |
| `tracker` | 追踪/遥测域名特征 | `analytics.` `cdn-cgi` 等 |
| `unusual_port` | 非标准端口 | `http://host:9999/` |
| `long_host` | 超长域名（>40 字符，混淆/随机） | — |

前端 `frontend/sandbox_console.html` 底部「URL 沙箱检测」面板可实时输入 URL 调用
`/api/net/url-check` 查看评分与命中异常项。

### 验证

```bash
.venv/Scripts/python.exe test_sandbox_net.py   # 无头验证：挂起→裁决→转发→配额熔断→AST/威胁
```

### 诱饵蜜罐（Honeypot 系统）

在沙箱中放置多种**高仿真陷阱文件**（SSH 私钥 / AWS 凭证 / Shell 历史 / .netrc / GCP / Git /
Postgres / .env …），内容格式正确但明显为假（含 `HONEYPOT-DECOY` 标记），绝不会被当作真实密钥。
当 AI 生成的代码触碰这些文件时，按四种策略触发不同等级的响应：

| 策略 | 名称 | 触发条件 | 响应 | 用户感知 |
|------|------|----------|------|----------|
| 一 | 静默替换 | 读取诱饵文件 | 返回高仿真假内容 + 后台记录审计事件 | **零感知**（进程不终止、不弹窗，完美处理误报） |
| 二 | 绑定网络动作 | 读取诱饵 **且** 发起网络外联 | 自动拒绝连接 + 生成升级告警；用户确认后终止进程 + IP 进永久黑名单 | 🚨 高危弹窗（默认已自动拒绝，待确认重拳） |
| 三 | 批量遍历阈值 | 5 秒内访问 ≥3 个不同诱饵路径 | 判定批量数据收割，暂停并终止进程 | 弹警告（默认拒绝） |
| 四 | 写入/删除保护 | 写/删诱饵文件 | 立即返回 Permission Denied + 终止进程 | 弹警告并终止 |

**诱饵清单**（落地于 `sandbox/decoys/`，并镜像 `C:/home/user`、`C:/Users/sandbox_runner` 以支持绝对路径命中）：

| 类别 | 路径签名（命中其一即触发） |
|------|----------------------------|
| SSH 私钥 | `.ssh/id_rsa` `.ssh/id_dsa` `.ssh/id_ecdsa` `.ssh/id_ed25519` `.ssh/id_rsa.pub` `.ssh/id_ed25519.pub` |
| AWS 凭证 | `.aws/credentials` `.aws/config` |
| Shell 历史 | `.bash_history` `.zsh_history` `.history` |
| .netrc 凭证 | `.netrc` `_netrc` |
| GCP 凭证 | `application_default_credentials.json` `credentials.json` |
| Git 凭证 | `.git-credentials` |
| Postgres 口令 | `.pgpass` |
| 密钥/变量 | `.env` `secrets.json` `credentials.yaml` `.env.local` |

**注入机制（Windows 非管理员 / 无 VM 隔离适配）**：

- **应用层 shim**（非 `LD_PRELOAD`/`seccomp`，后者为 Linux 机制且本机无 VM 级隔离）：
  - Python：经 `PYTHONPATH` 注入 `sandbox_honeypot_shim/sitecustomize.py`，劫持
    `builtins.open` / `os.remove` / `pathlib.Path` / `shutil.rmtree` 等 I/O 入口。
  - Node：经 `NODE_OPTIONS=--require` 注入 `honeypot_node.js`，劫持 `fs` 的读/写/删接口与 `fs.promises`。
  - shim 仅在 `HONEYPOT_ACTIVE=1` 时激活（仅注入沙箱子进程，**不污染 web.py 宿主**）。
- **物理假文件兜底**：只读（0o444）假文件落地到隔离位置，bash / cat 等无用户态 hook 的程序也能命中策略一/四。
- **`~` 重定向**：沙箱子进程的 `HOME`/`USERPROFILE` 指向诱饵根，故 `open("~/.ssh/id_rsa")` 直接命中。
- **跨进程事件日志**：shim（受限子进程，受防火墙限制无法回连）把读/写事件以 JSON 行追加到
  共享文件 `sandbox/honeypot_events.log`；web 进程（代理所在）读取该文件做策略二关联。

**策略二关联流程**：代理在挂起新连接时，用来源 PID 反查（`resolve_pid` → `netstat`/`psutil`）
该进程是否近期读过诱饵（关联窗口 120s）；若命中则连接被**立即自动拒绝**（403），
并生成升级告警（红色 🚨）留存于审计；用户在控制台「蜜罐升级告警」面板点击确认后，
进程被终止、该外传目标写入**永久黑名单** `sandbox/net_deny.json`（重启后仍生效）。

> 局限：bash 等无用户态 hook 的程序仅依赖物理只读假文件兜底，无法做到「读诱饵 + 外联」
> 的进程级关联（策略二对 bash 退化为策略一/四的物理文件保护）。

**端点**

| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/api/honeypot/audit`   | 蜜罐审计汇总（按策略/按 PID 统计 + 最近事件 + 升级告警） |
| GET  | `/api/honeypot/decoys`  | 诱饵清单（类别 / 路径签名 / 部署根） |
| POST | `/api/honeypot/deploy`  | 重新部署（刷新）诱饵陷阱文件 |
| POST | `/api/honeypot/ack`     | `{"id"}` 确认升级告警：终止进程 + 目标进永久黑名单 |
| GET  | `/api/net/pending`      | 待审请求现含 `honeypot_risk` / `honeypot_category` 字段（策略二标记） |
| GET  | `/api/net/policy`       | 策略快照现含 `deny_permanent`（永久黑名单，由策略二升级写入） |

前端控制台 `frontend/sandbox_console.html` 底部新增「蜜罐升级告警 / 诱饵清单 / 蜜罐审计」面板。

### 验证

```bash
.venv/Scripts/python.exe test_sandbox_net.py   # 无头验证：挂起→裁决→转发→配额熔断→AST/威胁
.venv/Scripts/python.exe test_honeypot.py      # 无头验证：四策略触发 + 代理升级 + 拉黑（19 项）
```

前端控制台：`frontend/sandbox_console.html`（待审授权面板 + 配额设置 + AST 预览 + 诱饵蜜罐）。

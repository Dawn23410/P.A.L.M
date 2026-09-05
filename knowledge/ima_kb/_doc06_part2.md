
# P.A.L.M 从零复刻指南（续：装配/心智核心/前端/启动/验收）

> 承接《从零复刻指南》第一篇（Phase 0-4）。本篇覆盖 Phase 5-8：装配层与后端网关、心智核心装配、前端 12 页、配置与启动、测试与验收、风险清单。

---

## 第七部分 Phase 5：装配层与后端网关

### 7.1 bootstrap/app.py（140 行规范）

按《架构白皮书》第四部分实现 build_app()：
1. 幂等检查：container.names() 非空直接返回。
2. 适配器层注册（try/except 降级）：storage → settings → crypto → models → gui。
3. 服务层注册：usage → usage_ledger → scheduler → conversations → game → affinity → roleplay → memory → evolution → agent。
4. 返回 ContainerProxy。

验收：重复调用不重复注册；任一依赖缺失时仅打印降级、不崩溃；container.get("storage") 等 14 个服务名均可取。

### 7.2 后端网关（FastAPI）

- 路由：/api/chat、/api/characters、/api/affinity、/api/usage、/api/events（SSE）、/api/stt/status、/api/system 等（以端点全量扫描 163 个为质量基线）。
- CORS：允许 5173/8000 等来源。
- 事件流：SSE 推送 text/thought/tool_call/ask_user/verdict 事件。
- 错误处理：所有端点捕获异常（不裸崩），依赖缺失降级 503。
- 验收：端点扫描脚本全量探测，无 500。

---

## 第八部分 Phase 6：心智核心装配（mentalcore）

### 8.1 安装与配置

```bash
cd mentalcore
pip install -e .          # 可编辑安装（--no-deps）
cp .env.example .env      # 填 MENTALCORE_API_KEY（非推理模型端点）
python -m mentalcore.selftest   # 离线自检（mock 零落盘）
```

### 8.2 心智魔方装配

```python
from mentalcore.config import load_config
from mentalcore.core import build_core
from mentalcore.persona_card import default_persona

core = build_core(load_config(), default_persona())
packet, manifest, emotion = core.send_message("你好呀")
core.receive({"mood": "开心"}, "外部上下文")
core.control(30000)          # 查好感度
core.get_model_info()
```

### 8.3 外骨骼装配（Boss + Worker）

```python
from mentalcore import build_core, build_exo, default_persona

boss = build_core(load_config(), default_persona())
exo = build_exo(config)          # 一键装配 Worker + 5 小魔方
boss.exo_broker = exo.make_broker(boss)   # 注入委派钩子
# 对话中模型可自发 ||EXO|| 委派后台执行；完成经 boss.receive() 回传
```

### 8.4 验收

- `python -m mentalcore.exo.selftest`（4 测全过）。
- EXO 协议：||EXO|| 委派 → Worker 执行 → 结果回传 Boss 加工。
- 控制码：18 条码全部可用；30300 单值改、40300 单字段改。
- mock 零落盘验证：跑完对话后无新文件。

---

## 第九部分 Phase 7：前端 12 页

### 9.1 页面清单

1. shell.html（外壳）+ ui/（共享组件）+ 11 screens：
2. 对话页（核心：SSE 流式 + 思维链时间线 + 工具调用实时计时 + ask_user 应答）。
3. 系统总览中枢（服务状态/砖块调度）。
4. 存储面板（quota/lifecycle/audit/health）。
5. 用量面板（Token 明细，provider 口径）。
6. 商城面板（星砂/道具）。
7. 保险库面板（vault 管理）。
8. 设置页（模型/语音/STT/角色/游戏开关）。
9-12. 其余 screen（会话管理、角色管理、进化状态、部件）。

### 9.2 关键实现

- 原生 ES Modules，无构建链（开发期 Vite 5173 代理）。
- 事件流：EventSource / fetch stream 接收 SSE。
- ask_user：弹窗按 id 应答 → POST 回填。
- 桥接层：pywebview 中 window.pywebview.api 封装后端调用。
- 部件（widget）：glass_clock 等经桥接层取数。

### 9.3 验收

- 12 页可加载、对话全流程（文字流/工具调用/ask_user/完成结算）可视化正确。
- 总览中枢显示 14 服务状态。

---

## 第十部分 Phase 8：配置、启动、测试与验收

### 10.1 .env 配置

```ini
HOST=127.0.0.1
PORT=8005
CORS_ALLOW_ORIGINS=http://localhost:5173,...
# 模型：base_url/api_key（tokenhub → DeepSeek）
# 语音：QWEN_TTS_*（可选）；STT_*（可选）
```

### 10.2 启动

```bash
python dev.py        # 依赖幂等安装 + 实时日志
# 或 python -m uvicorn ...（后端） + npm run dev（前端 Vite 5173）
```

注意：dev.bat 用 rem 注释（非 ::）；文件 CRLF 换行（LF 会被 cmd 误执行）。

### 10.3 测试矩阵

| 层级 | 方式 | 基线 |
|---|---|---|
| 单元 | pytest（14 服务相关） | 7/8 通过（修复 1 项遗留） |
| 冒烟 | 启动 + 核心端点探测 | 全绿 |
| 端点 | 全量扫描脚本 | 163 端点无 500 |
| e2e | e2e 客户端（8012） | 全链路无业务 bug |
| 心智核心 | selftest / exo.selftest | 全过 |
| GUI | patch _storage_cap → None 隔离 | 不污染真实数据 |

### 10.4 验收对照（与《模块深度解析》模块十七清单一致）

逐项勾选 17 项复刻检查清单；重点验收：对话全链路、工具安全链、ask_user 闭环、记忆只存事实、好感度档位、游戏结算、进化裁决、GUI fail-closed、Token 账本真实性。

---

## 第十一部分 风险与常见坑

### 11.1 架构级风险

1. **越层依赖**：domain import services → lint 拦截；复刻时保持依赖单向。
2. **全局状态泄漏**：业务模块不得自行注册/持有全局；一切经容器。
3. **缺失归一遗漏**：container.get 返回 None 未判空 → 运行时崩溃；编码规范强制判空。

### 11.2 Windows 工程坑

1. bat 换行 LF/CRLF（cmd 误执行）。
2. :: 注释解析（改 rem）。
3. 文件锁竞争（settings 保存失败）。
4. 路径硬编码（统一 paths.py）。
5. uiautomation import 顺序（须先 CoInitializeEx(STA)）。

### 11.3 模型与推理坑

1. thinking 模型续轮缺 reasoning_content → 400。
2. 空 thought 事件未归一 → NoneType 崩溃。
3. token 估算量混入账本 → 用量虚增。
4. Blackwell（sm_120）需 torch cu128 + bf16；onnx 强制 CPU；transformers 5.x KV-cache 掩码坍塌需补丁；wetext==0.0.4。

### 11.4 安全风险

1. 裁决 AI 档无回调必须 fail-closed（不默认放行）。
2. 出网必须走 net 门面（不裸 requests）。
3. 删除必须走 vault 拦截（可恢复）。
4. 联网工具必须进裁决（ChineseDictTool 教训）。
5. ask_user 事件缺 id → 死锁（必须携带 id + 即时推送）。

### 11.5 数据风险

1. 测试污染真实数据（GUI 测试须 patch 存储能力）。
2. mock 模式意外落盘（persist=False + sem=None 双保险）。
3. 记忆写入角色语气（污染检测必须常开）。

---

## 第十二部分 复刻完成判定

复刻完成的标准（全部满足才算 1:1 等价）：

1. 目录结构与 palm/ 分层完全一致（差异仅在业务代码实现细节）。
2. 15 Port 契约 + 14 服务装配 + container 机制通过契约测试。
3. 对话全链路（含工具/规划/反思/压缩）在 mock 与 live 双模式跑通。
4. 角色扮演 + 好感度双线 + 游戏结算端到端可用。
5. 记忆分层 + 只存事实 + 衰减基准达标。
6. 进化（闲置推测/每日简报/主动推送）可触发且过裁决。
7. GUI automate 入口 + L0-L3 执行器 + fail-closed 可用。
8. mentalcore 心智魔方 + 外骨骼双链装配成功，18 控制码可用，4 测全过。
9. 前端 12 页加载且对话可视化完整。
10. 端点全量扫描无 500；单元测试 8/8（含修复遗留 1 项）；e2e 无业务 bug。

按此标准完成即视为"可 1:1 完整复刻"。

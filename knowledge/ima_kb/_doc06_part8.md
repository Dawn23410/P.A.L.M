# P.A.L.M 从零复刻指南（深度扩充五：依赖脚本/验收模板/附录）

> 承接扩充章 T-Y。本部分给出：完整依赖安装脚本、验收报告模板、常见问题对照、以及复刻全过程时间预算。

---

## 扩充章 Z：完整依赖安装脚本（Windows）

### Z.1 主运行时（venv_runtime）

```bat
@rem 主运行时依赖安装（幂等）
python -m venv venv_runtime
call venv_runtime\Scripts\activate.bat

pip install fastapi uvicorn[standard]
pip install pydantic pyyaml httpx
pip install openai                       @rem OpenAI 兼容客户端
pip install -e palm                      @rem palm 库
pip install -e mentalcore --no-deps      @rem 心智核心（跳过依赖）
```

### Z.2 语音引擎（可选）

```bat
@rem CosyVoice（Blackwell sm_120 需 cu128）
python -m venv venv_cosyvoice
call venv_cosyvoice\Scripts\activate.bat
pip install torch --index-url https://download.pytorch.org/whl/cu128
pip install soundfile wetext==0.0.4
@rem vendored cosyvoice/matcha 源码进 site-packages

@rem GPT-SoVITS（自包含，7-Zip 解包）
python -m venv venv_gsv
call venv_gsv\Scripts\activate.bat
@rem 模型包用 7-Zip 解包（启动即拉起）
```

### Z.3 本地 TTS/STT（可选）

```bat
@rem Qwen3-TTS（.venv-qwen-tts，serve.py 自动拉起）
python -m venv .venv-qwen-tts
call .venv-qwen-tts\Scripts\activate.bat
pip install -r requirements-tts.txt

@rem STT（.venv-stt，独立子进程）
python -m venv .venv-stt
call .venv-stt\Scripts\activate.bat
pip install onnxruntime silero-vad sherpa-onnx
@rem 模型放 Data/stt_models/{vad,kws,asr}/
```

### Z.4 向量与检索（可选）

```bat
pip install chromadb          @rem 向量库（live 记忆）
pip install onnxruntime       @rem bge INT8 语义检索
@rem bge-m3 经 Ollama（localhost:11434）
```

---

## 扩充章 AA：验收报告模板

### AA.1 端点扫描报告

```markdown
# 端点扫描报告
- 日期：____
- 端点总数：____
- 无 500 数：____
- 降级 503 数：____（依赖缺失）
- 异常列表：____
- 结论：通过 / 不通过（附修复）
```

### AA.2 基准报告（对话）

```markdown
# 对话基准报告
- 模式：mock / live
- 轮数：____
- TTFB 中位数：____s / P95：____s
- 协议遵守率：____%
- 错误轮：____（重试恢复）
- 伪像标注：____（如端点排队）
- 结论：____
```

### AA.3 安全审计报告

```markdown
# 安全审计报告
- 审计项：注入/越权/逃逸/泄漏/控制码/进化滥用
- 每项：预期防御 → 实测 → 结论
- 外部引用核实：库名/函数名/写法（网络核实）
- 红队样例：____
- 修复项：____
- 结论：____
```

---

## 扩充章 BB：常见问题对照（复刻者 FAQ）

| 问题 | 答案 |
|---|---|
| 找不到 container | 确认 palm._core.container 导入路径 |
| capability 返回 None | 服务未注册或方法不存在，检查 bootstrap |
| 裁决全 deny | 检查 Profile（默认 STRICT）+ 规则 |
| 出网全部失败 | 网卡未注册（register_card） |
| 删除没进 vault | delete_file 未走冗余链 |
| ask_user 卡住 | 事件缺 id / 未即时推送 |
| 记忆不写入 | pollution_guard 拦截（检查内容） |
| 好感度不动 | 吝啬制（小数步进）+ 档位 |
| mock 落盘 | persist 误开（False + sem=None） |
| Worker 不执行 | exo_broker 未注入 |
| 控制码无效 | 码值错误（对照 CONTROL_USAGE） |
| 前端收不到流 | CORS / SSE 端点 |
| 语音不可用 | 引擎未配置（优雅降级） |
| GUI 不动 | 档位 fail-closed / assistive_mode |
| 端点 500 | 未捕获异常（修 try/except） |

---

## 扩充章 CC：复刻全过程时间预算

| 阶段 | 时长（单人工） | 说明 |
|---|---|---|
| 环境/骨架 | 0.5-1 天 | venv/目录/配置 |
| _core 基础设施 | 1-1.5 天 | 容器/裁决/网卡/事件 |
| ports 契约 | 0.5 天 | 15 ABC |
| 适配器 | 1 天 | storage/crypto/models/io |
| 领域层 | 1.5-2 天 | roleplay/memory/planning/evolution |
| 服务层 | 2 天 | agent/chat/ops/evolution |
| 装配+网关 | 1 天 | bootstrap + FastAPI |
| 对话联调 | 1 天 | mock 验证全链路 |
| mentalcore | 1-1.5 天 | 魔方 + 外骨骼 + 控制码 |
| 前端 | 1.5-2 天 | 12 页 + SSE |
| 游戏/进化/语音接入 | 1-2 天 | 可选 |
| 安全+验收 | 1-1.5 天 | 审计/扫描/基准 |
| **合计** | **13-17 天** | 单人工（含 AI 协作） |

---

## 扩充章 DD：附录——本系列文档索引

| 篇 | 标题 | 内容 |
|---|---|---|
| 00 | 项目总览与产品说明 | 定位/技术栈/功能/目录/运行/数据/FAQ |
| 01 | 发展路径与版本演进史 | 87 条提交逐条详解/阶段/规律 |
| 02 | AI 与个人贡献分析 | 贡献矩阵/案例复盘/协作模式 |
| 03 | 系统架构白皮书 | 分层/容器/契约/安全/数据流/端点 |
| 04 | 模块深度解析（复刻级） | 逐模块实现细节/算法/数据模型 |
| 05 | 心智核心与外骨骼深度解析 | 六面/控制码/Boss/Worker/基准 |
| 06 | 从零复刻指南 | 分步手册/模板/验收/FAQ |

**使用建议**：
1. 先读 00（总览）建立全局。
2. 再读 03 + 04（架构 + 模块）理解实现。
3. 复刻时对照 06（操作手册）。
4. 演进史（01）与贡献（02）用于理解"为什么"。

---

## 扩充章 EE：结语

P.A.L.M 从 2026-07-31 的克隆仓库起步，21 天 90+ 次提交，形成"终极架构 palm 库 + 心智核心 mentalcore + 12 页前端 + 四引擎语音 + 游戏生态 + 自主进化"的完整桌面 AI 管家。本系列 7 篇 10 万+ 字文档以 1:1 复刻颗粒度完整记录了这一切——从架构到模块、从历史到贡献、从设计到操作。按本系列复刻，即可重建功能等价的 P.A.L.M。

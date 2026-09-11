# P.A.L.M 容器化与 Linux 扩展指南

## 目标
把 P.A.L.M 微内核做成可移植的运行镜像，为后续在 Linux（含 中国台湾/中国香港/中国澳门 等跨平台）扩展做准备。核心原则：**内核轻、依赖懒加载、重型/平台专属部分可插拔**。

## 架构边界
| 组件 | 是否进镜像 | 说明 |
|---|---|---|
| `palm/ mentalcore/ llm/ security/ memory/ tool/ plan/ gui/ sandbox/` | ✅ 进镜像 | 纯 Python 微内核，仅 `pydantic` 为硬依赖 |
| `torch / vosk / chromadb / playwright` | ✅ 进镜像（CPU 版） | 全部懒加载，缺失则降级，不影响装配 |
| `speech/`（GPT-SoVITS ~17GB + Windows 内嵌 python） | ❌ 不进镜像 | 通过卷挂载或独立服务接入 |
| `gui/adapters_gui`（uiautomation/pyautogui） | ⚠️ 不启用 | Windows 桌面自动化，容器内默认降级跳过 |

## 构建与运行
```bash
# 构建（在 Linux 机器上）
docker build -t palm:0.1.0 .

# 仅内核，装配自检
docker run --rm palm:0.1.0

# 运行任意入口脚本（tests / GSV / agent 任务）
docker run --rm -v "$PWD/speech:/opt/palm/speech:ro" palm:0.1.0 \
  python tests/mentalcore_selftest.py

# 带持久化数据卷启动常驻容器
docker compose up -d palm
```

## Linux 扩展要点
1. **路径**：全部配置路径已改为 `os.environ` / `expanduser("~/...")` 可覆盖，避免 Windows 绝对路径硬编码（已修复 `api_snapshot.py`/`prompt_cache_probe.py`/`bench_50.py`/`honeypot.py`）。
2. **编码**：容器 `LANG=C.UTF-8`；代码内仅 ASCII 引号用于语法，自然语言引号随 locale。
3. **Windows 专属**：`gui/adapters_gui`、`sandbox/run.py` 的 Job Objects 隔离为 Windows 专属，Linux 下由 `bootstrap/app.py` 的 try/except 自动降级，不会崩。
4. **GSV 语音**：Linux 无 Windows 内嵌 python，需在本镜像基础上额外准备 Linux torch 环境后启动 GPT-SoVITS 服务（端口 `:9880`）。建议后续做成独立 service（compose 已预留）。
5. **联网策略**：内核默认 fail-closed（无网卡即拒绝外网），由 `palm._core.net` 守卫；容器内可通过环境变量控制离线/在线。

## 已知风险
- 镜像未激活 MCP / hook；需在对应平台打开连接器管理页手动 Trust。
- 当前沙箱无法 build（无 docker daemon）；以上配置需在 Linux/Docker 环境实际验证。
- `automations` 数据存于 `~/.workbuddy/workbuddy.db`，不在镜像内。

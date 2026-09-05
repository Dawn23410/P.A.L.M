# P.A.L.M 全局检查报告（2026-08-28）

> 范围：`C:\Users\Dawn\Desktop\P.A.L.M\`（约 9500+ 文件，混合 Python / TS / JS）
> 方法：结构映射 + 配置/入口核验 + 技术债务扫描 + Git 卫生检查（排除 `.venv` / `node_modules` / `__pycache__` / 内嵌语音运行时）

---

## 一、项目定位与技术栈

| 层 | 目录 | 说明 |
|---|---|---|
| 微内核 | `palm/`（180 文件） | Python 包，仅硬依赖 `pydantic`；其余依赖懒加载、优雅降级 |
| 心智核心 | `mentalcore/`（148 文件） | Boss/Worker 双链架构、guardrail 5-tier 仲裁、execution engine |
| 运营控制台（前端） | `ui/migrated-frontend/` | React 18 + Ant Design 5 + React Router + Vite + TS |
| 后端 | `engine/web.py`（:8080）+ `palm/bootstrap/app.py` | FastAPI/Web 服务 |
| 语音子系统 | `speech/`（约 5.2 万文件 / 17GB 级） | GPT-SoVITS / CosyVoice / Vosk，本地内嵌运行时，**不入库** |
| 桌面自动化 | `gui/`（46 文件） | uiautomation 适配器（桌面控制），独立于 Web 控制台 |
| 编排 | `P.A.L.M一键启动.bat` + `docker-compose.yml` | 主控拉起 9 个隐藏服务；compose 编排内核 + 可选 GSV |

架构形态：典型"microkernel + 多独立服务"，各 domain（engine/ui/speech/tool/knowledge/…）从各自目录启动，不在 setuptools 里互相爬行（`pyproject.toml` 显式限定只装内核包）。

---

## 二、可运行性 / 构建就绪度 ✅

- **前端**：`ui/migrated-frontend/package.json` 含 `dev` / `build`(tsc -b && vite build) / `preview`；`node_modules`（231 包）已装、`dist` 已存在 → 可构建可预览。
- **后端入口**：`engine/web.py`、`palm/bootstrap/app.py` 均存在。
- **编排链路完整**：一键启动器引用的 9 个 `.bat`（backend / frontend / packages / voice / cosy / vosk / mentalcore-bridge / weave）全部存在。
- **容器化**：`Dockerfile` + `docker-compose.yml` 就绪；compose 注释自带 `docker compose run --rm palm python tests/mentalcore_selftest.py`。

---

## 三、Git 健康度 ⚠️

- 实际**跟踪文件仅 438 个**；`speech/` 下 **0 个被跟踪** → 无仓库膨胀，远端干净。
- 最近提交：`2026-08-20`（约 8 天前）。
- **工作树有 177 处未提交改动：105 删除 / 18 修改 / 54 新增。**
  - 105 处删除 = 旧 `frontend/*.html`（原生 ES Modules 静态页）。`frontend/` 目录现已不存在 → **前端已迁至 `ui/migrated-frontend`（React），迁移在本地完成但未提交**。
  - 风险：大量未提交改动易丢失、`git status` 噪声大。

---

## 四、结构 / 健康风险清单

| 严重度 | 问题 | 建议 |
|---|---|---|
| 🟠 中 | 177 处改动未提交（含整次前端迁移） | 尽快 commit 本次迁移，避免丢失 |
| 🟠 中 | 根目录散落未跟踪分析产物：`archive_data.js`(2.7MB)、`archive_index_fixed.json`(3.1MB)、`frontend_compare.json`、`frontend_comparison.html`、`storage_audit_report.html`、`run50_voice_gpu_report.html`、`refer_audio_tmp.wav` | 移入 `outputs/` 或 `reports/`，或在 `.gitignore` 加规则（`gsv_server.log` 已被忽略） |
| 🟡 低 | `tool/_legacy_tools/`（939 文件，命名 legacy）仍被启动器引用（packages 服务） | 评估能否隔离/精简，仅保留 packages 服务 |
| 🟡 低 | `archive -> /d/P.A.L.M_archive` 符号链接依赖 D: 盘 | 外部依赖；D 盘未挂载时归档功能失效，需在文档中标注 |
| 🟡 低 | 测试设施薄弱：`tests/` 有文件（`mentalcore_selftest.py` + benchmarks/integration/redblue/engine_legacy），但**无 pytest 配置/依赖/conftest/CI** | 引入 pytest 配置与 `npm test`，建立质量门禁 |
| ⚪ 提示 | `mentalcore/mentalcore/__main__.py` 缺失 | 若需 `python -m mentalcore` 则补上；当前不影响启动器 |
| ✅ 正面 | 源码（排除语音运行时）未检出 TODO/FIXME/HACK/XXX 标记 | 标准技术债务标记少 |

---

## 五、可立即执行的"检查"项（可选，需你确认后我再跑）

- 前端类型/构建校验：`cd ui/migrated-frontend && npm run build`
- mentalcore 自测：`python tests/mentalcore_selftest.py`（或经 docker compose）
- 我也可以直接帮你：提交前端迁移、把根目录杂物归档/清理、补 pytest 配置。

---

### 一句话结论
**P.A.L.M 结构清晰、可运行性良好、远端仓库干净；当前唯一实质性风险是"前端迁移已完成但未提交"（177 处未跟踪/删除改动），以及根目录散落的分析产物需要归档。建议优先提交迁移、清理根目录杂物。**

# P.A.L.M 全局体检报告（2026-09-16）

> 范围：`D:\P.A.L.M\`（唯一工作树）
> 方法：结构映射 + 配置/入口核验 + 技术债务扫描 + Git 卫生 + 密钥暴露面核查
> 排除：`.venv` / `node_modules` / `__pycache__` / vendored 语音运行时
> 基线对照：《P.A.L.M全局检查报告_2026-08-28.md》

---

## 一句话结论

**工程卫生相比 08-28 大幅改善（177 处未提交改动 → 0，根目录杂物 → 清空），但发现 1 个必须立刻处理的高危项：真实 API Key 以明文形式提交入库并已推送到 GitHub 远程仓库。**

---

## 一、仓库概览

| 项 | 值 |
|---|---|
| 工作树 | `D:\P.A.L.M\`（桌面旧副本已不存在） |
| 分支 / 远程 | `main` → `git@github.com:Dawn23410/12345.git`，本地与上游同步（0 待推送） |
| Git 跟踪文件 | **932**（全部在 `app/` 下） |
| 最新提交 | `926e4ab` 2026-09-11 17:11「仓库结构净化 —— 应用源码并入 app/」 |
| 近 7 天提交数 | 2 |

### 顶层目录与入库策略

| 目录 | 文件数 | 入库 | 说明 |
|---|---:|---|---|
| `app/` | 1,503 | ✅ | 主应用（唯一入库区） |
| `1_Demo_LLM/` | 59,332 | ❌ 刻意 ignore | 11 个功能内核；体量来自 vendored 运行时 |
| `8_归档/` | 1,385 | ❌ ignore | 归档区 |
| `3_文档/` | 226 | ❌ ignore | 文档库（四层结构） |
| `2_实验/` | 222 | ❌ ignore | 15 个实验子系统 |

> `1_Demo_LLM/` 的 5.9 万文件里，真实源码占比很低：GPT-SoVITS 47,390 / RAG 6,589 / VOSK 4,751，绝大部分是 `runtime/Lib/site-packages`、`venv`、`.bench_venv`。**这是磁盘占用的真正大头**，与代码规模无关。

### `app/` 二级结构（入库主应用）

| 目录 | 文件数 | 目录 | 文件数 |
|---|---:|---|---:|
| `engine/` | 621 | `security/` | 14 |
| `palm/` | 202 | `tool/` | 12 |
| `ui/` | 78 | `sandbox/` | 8 |
| `tests/` | 46 | `memory/` | 8 |
| `gui/` | 46 | `llm/` | 8 |
| | | `plan/` | 5 |

---

## 二、可运行性 ✅

| 检查项 | 状态 |
|---|---|
| 编排链路引用文件（`palm_boot.py` / `run_backend.bat` / `start.bat` / `tray_app.py` / `web.py` / `package.json` / `docker/entrypoint.sh`） | ✅ 7/7 全部存在 |
| 后端 Python 环境 `app/.venv` | ✅ 存在，`Scripts/python.exe` 可用 |
| 前端 `ui/migrated-frontend` | ✅ `node_modules` + `dist` 均在；`dev`/`build`/`preview` 脚本齐备 |
| 容器化 | ✅ `Dockerfile` + `docker-compose.yml` |
| **测试设施** | ⚠️ **薄弱**：36 个测试文件，但无 `pytest.ini` / `conftest.py` / CI；且 `.venv` 内**未安装 pytest**（`ModuleNotFoundError`）→ 测试当前无法一键运行 |

---

## 三、Git 卫生 ✅（较 08-28 显著改善）

| 指标 | 08-28 | 09-16 |
|---|---|---|
| 未提交改动 | 177 处（105 删 / 18 改 / 54 增） | ✅ 0 修改 / 0 删除 |
| 未跟踪文件 | 54 | 1（`app/engine/_nul`，0 字节垃圾） |
| 顶层散落分析产物 | 7 个（含 2.7MB / 3.1MB 大文件） | ✅ 已清空 |
| 入库文件数 | 438 | 932（重构后全量并入 `app/`） |

- `.gitignore` 有意排除 6 个顶层目录，注释说明了理由（避免污染主仓库）——策略清晰。
- `app/.env` 已被 `app/.gitignore:25` 正确忽略 ✅（未入库）。

---

## 四、风险清单

| 严重度 | 问题 | 证据 | 建议 |
|---|---|---|---|
| 🔴 **P0** | **真实 API Key 明文入库且已推送远程**。`app/engine/config.json` 中智谱 GLM 的 `api_key` 为真实值（`8d1357…`，32 位 hex + `.` + 16 位），该文件被 git 跟踪，且 `b3db64e`(08-28)、`926e4ab`(09-11) 两次提交均含此值；本地与上游 0 差异 → **远程已有** | `git ls-files --error-unmatch app/engine/config.json` 通过 | ① 立刻到智谱控制台**吊销并重建**该 Key（删文件不足以补救，历史里还在）；② 把 `config.json` 加入 `.gitignore`，另存 `config.example.json` 只留空 key；③ 如需彻底清史再评估 `git filter-repo` |
| 🟠 P1 | `.env` 中 `SOVITS_ROOT` 指向已不存在的 C 盘旧路径：`C:/Users/24459/Desktop/P.A.L.M/语音合成 (GPT-SoVITS)/src/gpt_sovits`；C 盘该路径与 `C:\tts` 均已不存在 | 第 4 行；`ls` 确认路径消失 | 改指 `D:\P.A.L.M\1_Demo_LLM\语音合成_GPT-SoVITS\...`，或直接删除该行走代码内默认值（否则 GSV 语音合成会降级/失败） |
| 🟠 P1 | 测试设施不可运行（见第二节） | 无 pytest 配置 + 无 pytest 包 | 补 `pytest.ini` + 装 pytest，纳入质量门禁 |
| 🟠 P1 | 文档库位置发生迁移但未同步：`D:\3_文档` 已不存在，文档实际落在 `D:\P.A.L.M\3_文档\`（226 文件），其中 `开发日志/` 最新仅到 `2026-08-16.md` | `ls` 确认 | 确认文档库主副本新位置并写进约定；补齐 08-16 之后的日志 |
| 🟡 P2 | `app/engine/_nul` 0 字节垃圾文件（2026-08-24 产生），系 Windows `>nul` 重定向被 shell 当文件名 | 未跟踪、0 字节 | 直接删除 |
| 🟡 P2 | `app/.workbuddy/`（450 文件）是**旧工作区的残骸**（含 `backup/faces_rewire/`、`backup/indep_modules/`、`memory/` 日志、`tmp/`、`tools/`），混在入库主应用目录内 | `git ls-files app/.workbuddy` = 0，已被 ignore | 未被污染仓库；建议整体挪进 `8_归档/` 或删除，避免与工作区实况混淆 |
| 🟡 P2 | `palm_boot.py:20` 注释仍写「主工程留在 `Desktop/P.A.L.M -1/`」，与实际 `D:\P.A.L.M` 不符 | 仅注释，无功能影响 | 顺手更正 |
| ⚪ 提示 | 源码内检出 5 处旧盘路径引用，**全部是注释**（`palm/services/chat/core.py`、`engine.py`、`palm_boot.py`） | grep 全量 | 无执行风险，可择机随文档更新 |
| ✅ 正面 | 排除运行时后，源码技术债标记（TODO/FIXME/HACK/XXX）**仅 9 行** | `grep --exclude-dir=.venv/node_modules/__pycache__/dist` | 工程注释纪律良好 |

---

## 五、当前主线状态

`1_Demo_LLM/桌宠/`（数字生命桌宠）仍在活跃开发：09-12 之后 `life/`（内核）与 `live2d_pet/`（表现层）、`docs/` 三篇文档均有改动，`data/palm-pet/events.jsonl` 持续写入 → 运行痕迹新鲜。
⚠️ 结构核对：实际只有 `life/` + `live2d_pet/`，**没有 `adapters/` 目录**（此前记录有误）。

---

## 六、可执行项（需你确认后我再动手，本报告未改动任何文件）

1. **【最高优先】** 吊销并重建智谱 GLM Key → 我改 `.gitignore` + 拆出 `config.example.json`
2. 修 `app/.env` 的 `SOVITS_ROOT` 为 D 盘实际路径
3. 清理 `app/.workbuddy/`（450 文件旧工作区残骸）→ 归档进 `8_归档/` 或删除
4. 删除 `app/engine/_nul`，更正 `palm_boot.py` 过时注释
5. 补 pytest 配置并安装 pytest，让 36 个测试文件真正跑起来
6. 复核 `D:\P.A.L.M\3_文档\项目文档\` 是否接纳本报告为新基线

---

*生成时间：2026-09-16 · 全程只读操作，未修改任何项目文件*

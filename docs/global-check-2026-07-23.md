# 全局检查：语法错误 / 脏文件 / 脏代码（2026-07-23 18:36）

范围：后端 Python（backend/ + main.py）、前端 TS/JS（frontend/src）、工作树与忽略文件。
方式：静态编译/类型检查 + 标记扫描 + git 状态，未做运行时导入（本机 WDAC 拦截编译型扩展）。

## 结论
- **语法错误：无** ✅ 后端 compileall 全过、前端 tsc --noEmit 全过、md-ui-kit 三个 .js 经 node --check 全过。
- **脏文件：有，但均已被 .gitignore 覆盖，不会误提交** ⚠️ 物理磁盘上残留调试/构建产物，可清理。
- **脏代码：无实质性残留** ✅ 源码中无 debugger / pdb / breakpoint / TODO / FIXME / HACK；仅有一处调试脚手架（main.py `_debug`）在每次启动落盘 `webview_debug.log`。

---

## 1. 语法检查（全绿）
| 检查 | 命令 | 结果 |
|---|---|---|
| 后端 Python | `python -m compileall backend` | PY_COMPILE_ALL_OK |
| 前端 TypeScript | `tsc --noEmit -p tsconfig.json` | TSC_OK |
| 前端纯 JS | `node --check` md-renderer/md-link-guard/md-sandbox.js | 三个均 OK |

---

## 2. 脏文件（磁盘残留，已 gitignore）
| 文件 / 目录 | 大小 | 来源 | gitignore 规则 | 提交风险 |
|---|---|---|---|---|
| `webview_debug.log`（根目录） | 5.6KB / 147 行 | main.py `_debug()` 每次启动追加 | `*.log`（.gitignore:30） | 无 |
| `frontend/.build_1784774075/` | 2.2MB | vite 时间戳构建产物 | `.build_*/`（.gitignore:14） | 无 |
| `__pycache__/`（多处） | — | Python 字节码 | `__pycache__/`（.gitignore:2） | 无 |
| `backend/uploads/`、`backend/parse_workspace/` | — | 运行时产物 | 对应规则（.gitignore:42/50） | 无 |
| `error.log`（根目录） | 不存在 | main.py 出错时才创建 | `*.log` | 无 |

说明：`git status --short` 干净，未跟踪项 `backend/app/bricks/ollama/`、`docs/`、`MaskLayer.tsx`、`ModelSelect.tsx`、`open-external.ts` 均为本次工作新增的预期文件，非脏文件。已删除的 `test.tsx`/`test.html` 也已在状态中体现为 D（预期清理）。

---

## 3. 脏代码（源码扫描）
- 后端扫描 `pdb|breakpoint\(|TODO|FIXME|XXX|HACK|print\(`：命中全部位于 **CLI 工具/测试脚本**（`tools/img_preprocess.py`、`tools/img_ocr.py`、`tools/doc2struct.py`、`smoke_test.py`），属正常 CLI 输出，**非脏代码**。
- 前端扫描 `debugger|TODO|FIXME|XXX|HACK|console\.log|@ts-ignore|@ts-nocheck`：唯一命中为 `md-sandbox.js:25` 中**字符串字面量** `'console.log(...)'`，非真实调试语句。
- **唯一可称“脏代码”的**：`main.py:47-53` 的 `_debug()` 在**每次启动无条件**向 `webview_debug.log` 追加并 `print("[debug] ...")`，是遗留的调试脚手架，产生上方的脏文件。建议：用环境变量（如 `PALM_DEBUG=1`）门控，或正式发布时移除。

---

## 建议清理（确认后执行）
1. 删除 `webview_debug.log`（可再生成，低风险）。
2. 删除 `frontend/.build_1784774075/`（可经 `npm run build` 重建，低风险）。
3. （可选）将 `main.py` 的 `_debug()` 改为受环境变量门控，避免无意义的日志落盘与 stdout 噪音。

# GPT-SoVITS 代码质量审计 v1.0

- 审计时间：2026-09-27
- 审计对象：`C:\Users\24459\Desktop\GPT-SoVITS-1007-cu128`（v1007 cu128 整合包）
- 工具：palm-metrics · `codequal.py`（静态质量）/ `dynprobe.py --kind security`（静态安全）
- 证据产物：`audit_gpt_sovits/`（4 个 JSON + 1 个文本，全部可复跑）
- 等级口径：A≥90 / B≥75 / C≥60 / D≥45 / E<45

---

## 1. 审计口径（先说清楚测了什么）

整合包里塞了内嵌 Python 环境（`runtime/`，含 CPython 完整 stdlib + 测试套件）和第三方权重/库，直接全扫会得出无意义的数字。所以划了两层口径：

| 口径 | 范围 | 文件 | 代码行 | codequal 总分(core) |
|---|---|---|---|---|
| **全仓** | 排除 `runtime/` `pretrained_models/` `__pycache__` | 184 | 39,582 | **75.8 / B** |
| **自研核心（主口径）** | 再排除 vendored：BigVGAN(NVIDIA) / eres2Net / f5_tts / feature_extractor(whisper) / uvr5 / AP_BWE_main / denoise-model / tools/asr | **113** | **29,675** | **75.4 / B** |

**关键观察**：剔除第三方后总分几乎没变（75.8 → 75.4）。说明拖分的不是第三方，是 GPT-SoVITS 自研代码本身。

主口径跑两套维度集：

- **core 口径**（6 核心维加权）：**75.4 / B**
- **all 口径**（再纳入死代码/命名/克隆，权重和 125 归一）：**76.7 / B**

后续判读以 all 口径为主（维度更全），core 口径用于横向对比历史基线。

---

## 2. 语义拆解（"代码质量"在这个语境 = 什么）

按判读框架先把定性词拆成可量化属性，声明如下假设（如你的"质量"指别的，纠正我，我只改解释不改数据）：

| # | 属性 | 映射指标 | 权重取向 |
|---|---|---|---|
| 1 | 结构混乱（绕不清） | `complexity` | 高 |
| 2 | 堆叠臃肿（复制粘贴、大函数） | `unit_size` + `duplication` + `clones` | **最高**（决定二次开发成本） |
| 3 | 牵一发动全身 | `coupling` | 中 |
| 4 | 无人能读 | `readability` + `naming` + `dead_code` | 中 |
| 5 | 暗藏风险 | `dynprobe security`（独立轴） | 高（你要把它接进 P.A.L.M） |
| 6 | 跑得动吗（延迟/RTF/首字） | **本次未测** | 不参与定级 |

---

## 3. 轴 1 · 结构质量：各维度得分

| 维度 | 权重 | 得分 | 等级 | 关键原始值 |
|---|---|---|---|---|
| 复杂度 | 25% | 86.3 | **B** | 最大 CC 73 / 最大认知 140 / 最大嵌套 6 |
| 单元规模 | 20% | 76.3 | **B**（临界 C） | 1145 函数中 116 超长 / 249 多参数 |
| **重复率** | 15% | **31.5** | **🔴 E** | **38.82%（阈值 2.0%，超 19 倍）** |
| 耦合度 | 10% | 92.7 | **A** | 平均扇出 5.8 |
| 可读性 | 15% | 77.3 | **B** | 注释占比 6.1%（健康带 8–35%，**欠下限**） |
| 效率风险 | 15% | 86.5 | **B** | 循环内 IO/拼接 73 处 |
| 死代码 | 10% | 98.1 | **A** | 未用 import 8 / 私有死代码 0 |
| 命名一致性 | 5% | 88.7 | **B** | 违规 135（函数 98% 已是 snake） |
| 近似克隆 | 10% | 62.1 | **🟡 C** | 159 组 / 435 函数 / 562 对边 |

**轴 1 定级：🔴 红**（依据：`duplication` 落 E 档 = D/E 红灯源，且 `clones` C 档共振，两条独立信号 + 逐文件证据）

---

## 4. 轴 1 证据链（拖红的具体坏点）

### 4.1 重复率 38.82% —— 不是统计伪像，有明确结构

逐文件 `dup_lines` 合计 8405 行，Top 集中点：

| dup 行数 | 文件 | LOC |
|---|---|---|
| 881 | `webui.py` | 1983 |
| 842 | `GPT_SoVITS/train_util.py` | 1303 |
| 734 | `AR/models/t2s_model.py` → `models.py` | 1433 |
| 626 | `models_onnx.py` | 1087 |
| 545 | `inference_webui.py` | 1353 |
| 523 | `data_utils.py` | 1071 |
| 316 | `api.py` | 1395 |

克隆配对（去重对边 117 组，Top）：

| 组数 | 配对 | 性质 |
|---|---|---|
| 20 | `train_util.py` ↔ `webui.py` | **整条 GUI 流水线被复制成两份** |
| 18 | `transformer.py` ↔ `transformer_onnx.py` | ONNX 导出变体 |
| 17 | `api.py` ↔ `inference_webui.py` | 推理入口复制 |
| 12 | `models.py` ↔ `t2s_model_onnx.py` | ONNX 导出变体 |
| 12 | `data_utils.py` ↔ 自身 | 文件内复制粘贴 |
| 12 | `chinese.py` ↔ `chinese2.py` | 两代中文前端共存 |
| 11 | `num.py` ↔ 自身 | 文件内复制粘贴 |
| 6×3 | `s2_train.py` / `s2_train_v3.py` / `s2_train_v3_lora.py` 互克隆 | 三代训练脚本并存 |

**判读**：重复不是"乱写"，是有因的重复——ONNX 导出副本、多代版本并存、GUI 与训练管线各存一份。**但事实仍是：改一处要同步 2–3 处**，这就是二次开发的真实成本。其中 `webui.py` ↔ `train_util.py`（20 组、1700+ 重复行）是 ROI 最高的靶点。

### 4.2 复杂度与单元规模：坏点高度具体

| CC | 认知 | 行 | 参数 | 位置 |
|---|---|---|---|---|
| **73** | 112 | 383 | 2 | `TTS_infer_pack/TTS.py:985 run()` |
| **63** | **140** | 251 | 16 | `inference_webui.py:751 get_tts_wav()` |
| **61** | 75 | 416 | **26** | `AR/modules/patched_mha_with_cache.py:13` |
| **56** | 129 | 239 | 13 | `api.py:830 get_tts_wav()` |
| 49 | 67 | 210 | 9 | `AR/modules/activation.py:204 forward()` |
| 36 | 125 | 124 | 2 | `text/LangSegmenter/langsegmenter.py:90 getTexts()` |

最长函数：`text/tone_sandhi.py:23 __init__()` **466 行**（CC=1，属大表初始化，可接受）；`patched_mha_with_cache.py:13` **416 行 / 26 参数**是真坏点。

其余：116 个函数超 50 行、249 个函数超 4 参数（最多 26 参）。

### 4.3 可读性

- 注释占比 **6.1%**，低于健康带下限 8%。最差：`inference_gui.py` 0.0%（316 行）、`transforms.py` 0.0%（205 行）、`modules.py` 0.7%（897 行）、`webui.py` 0.8%（1983 行）
- 模糊命名 **318 处**，高频：`value` 17 / `data` 16 / `item` 16 / `p` 15 / `result` 13
- 超长行（>120）125 处

### 4.4 最该处理的文件 Top 10

| 得分 | 等级 | 文件 | LOC | 最大CC | MI |
|---|---|---|---|---|---|
| **36.2** | **E** | `GPT_SoVITS/s2_train.py` | 684 | 26 | 6 |
| 49.3 | D | `AR/modules/patched_mha_with_cache.py` | 428 | 61 | 8 |
| 51.6 | D | `GPT_SoVITS/s2_train_v3.py` | 467 | 16 | 15 |
| 55.3 | D | `AR/modules/activation.py` | 413 | 49 | 13 |
| 58.0 | D | `GPT_SoVITS/train_util.py` | 1303 | 27 | 0 |
| 58.2 | D | `AR/modules/patched_mha_with_cache_onnx.py` | 85 | 2 | 33 |
| 58.4 | D | `webui.py` | 1983 | 27 | 0 |
| 61.7 | C | `GPT_SoVITS/s2_train_v3_lora.py` | 379 | 18 | 15 |
| 64.1 | C | `AR/models/t2s_model.py` | 935 | 26 | 4 |
| 64.1 | C | `TTS_infer_pack/TTS.py` | 1637 | 73 | 0 |

平均可维护性指数 MI **33.2**（<65 属红色区）。

---

## 5. 轴 2 · 安全面：59 HIGH / 0 MED / 2 LOW（独立轴）

扫描 115 文件，命中 61。**命中 = 可疑面，不是已定罪**。按语境分桶并逐条代码级复核后：

### 🔴 确认高危（生产代码 / 网络可达）

| 位置 | 问题 | 复核结论 |
|---|---|---|
| `gsvi.py:333` | `shutdown_password = "wYdjEHnnjrNAahFsQ0yVmv1TEeUU9Z8A"` 硬编码 | **已读码确认**。整合包自带的 FastAPI 服务，`POST /shutdown` 明文口令写死在源码 |
| `gsvi.py:19` | `origin = ["*"]` CORS 全开 | **已读码确认**。任意站点可跨域调用该服务（含 `/shutdown`、`/outputs`） |
| `gsvi.py:341` | `FileResponse(f"outputs/{result_path}")` 路径未归一化 | **人工补，工具未覆盖**。`result_path` 直接拼进路径，存在穿越面（实际可利用性取决于路由对 `/` 与编码斜杠的处理，建议显式校验后再定级） |
| `tools/my_infer.py:631/638` | `subprocess.run(f"...aria2c ... {model_url} -o cache/{categroy}-{lang}-{model_name}.zip", shell=True)` | **已读码确认**。模型下载链接与模型名来自外部，直拼进 shell |

> 归属说明：`gsvi.py` / `tools/my_infer.py` 是**本整合包作者**的封装，不是上游 GPT-SoVITS 的代码——但它就在你的部署目录里。

### 🟡 本地 GUI 面（危害有限，但模式本身危险）

`webui.py` 25 处 + `train_util.py` 15 处 `subprocess.Popen/Run(shell=True)`，污点链显示命令串由 Gradio 输入（`asr_inp_dir` / `denoise_opt_dir` / `path_list` / `pid` …）拼接而成。

- 例：`webui.py:239` → `cmd = "taskkill /t /f /pid %s" % pid; subprocess.run(cmd, shell=True)`
- 判读：这是**本地桌面工具**，输入方就是使用者本人，攻击者与受害者同一人 ⇒ 落地风险打折；但模式本身是 A03，一旦有人把它改成网络可达服务就是真漏洞。

### ⬇️ 人工复核降级（工具判 HIGH，实为误报/低危）

| 位置 | 工具判定 | 复核后 |
|---|---|---|
| `webui.py:609` / `train_util.py:609` / `TTS.py:365` | yaml.load 未显式 SafeLoader [A08] HIGH | **降级**：三处均已显式 `Loader=yaml.FullLoader`，非 `UnsafeLoader`，不落 CVE-2017-18342。属"字面不含 SafeLoader"的误判 |
| `inference_webui.py:87/90`、`..._fast.py:48/52`、`prepare_datasets/*.py`×4、`subfix_webui.py:423` | `eval(非常量)` HIGH | **降级为坏味道**：实为 `eval(os.environ.get("is_share","False"))`，读环境变量，非外部请求数据。该用 `ast.literal_eval` |
| `text/english.py:213/226`、`text/g2pw/g2pw.py:120` | `pickle.load` HIGH | **降级**：加载的是随包分发的 cmudict / g2pw 词典，来源可信 |
| `text/cleaner.py:37/72` | `__import__(language)` HIGH | **降级**：`language` 是内部枚举流转 |

### 正面结论

- 网络面主入口 `api.py` / `api_v2.py` **未检出**任何 `shell=True` / `eval` / `exec` / `os.system` / `yaml.load` / `pickle` 命中 —— 上游的 HTTP 推理接口比 GUI 干净。

**轴 2 定级：🔴 红**（依据：存在已读码确认的生产代码硬编码密钥 + 网络可达面命令注入 + CORS 全开）

---

## 6. 合议定级

| 轴 | 等级 | 依据 |
|---|---|---|
| 轴1 结构质量 | 🔴 **红** | `duplication` 31.5 = E 档（阈值 19 倍），`clones` 62.1 = C 档共振，8405 重复行有逐文件落点 |
| 轴2 安全面 | 🔴 **红** | 已确认硬编码密钥 + CORS 全开 + 下载链接入 shell；排除误报后仍有 4 类确认项 |
| 轴3 运行时性能 | ⚪ 未测 | 无延迟/RTF/首字样本，不参与定级 |

> **整体：🔴 红**（规则：任一轴红 → 红）

---

## 7. 但对你当前的用法，结论要分层看 🔎

整体红 ≠ 不能用。关键看红在哪、你要动哪：

| 你的用法 | 涉及代码 | 该代码质量 | 结论 |
|---|---|---|---|
| **TTS_infer_pack 直调合成**（P.A.L.M 现用法） | `TTS.py`(64.1/C)、`text/` 前端、AR/BigVGAN 模型 | 中等偏上；`TTS.py:985 run()` CC=73 是唯一硬伤 | ✅ **可用**。重复集中在 GUI/训练管线，不在推理热路径 |
| **微调训练**（s1/s2） | `s2_train*.py`(36.2/E)、`train_util.py`(58.0/D) | 最差的一档 | ⚠️ **能用但别改**。要改就接受"改一处同步三代脚本" |
| **webui / train_util GUI** | `webui.py`(58.4/D) ↔ `train_util.py`(58.0/D) | 1700+ 行互为副本 | ⚠️ **别在这对双胞胎上做二次开发** |
| **gsvi.py 服务（整合包自带）** | 硬编码口令 + CORS `*` + 路径未校验 | 安全面最差 | 🔴 **别暴露到公网/局域网**，仅本机回环用 |

---

## 8. 未覆盖信号（显式声明，不用相邻指标冒充）

| 缺失信号 | 现状 |
|---|---|
| 测试覆盖率 | 仓库**无自有测试**（仅 vendored 的 `BigVGAN/tests` 3 个）；无 `.github/workflows`，CI 缺失 |
| 依赖/供应链漏洞 | 未做 CVE 库比对（工具无此能力） |
| 跨函数/跨模块污点分析 | 工具只做函数内轻量污点标注（本次已据此给出 6 条污点链），跨文件调用链未跟踪 |
| 运行时性能（延迟/RTF/首字/显存） | 本次未采集样本 |
| 模型精度/音质 | 不属代码质量轴 |

工程卫生的正面项：有 `.pre-commit-config.yaml`（ruff lint + format，line-length 120 / py310）——说明上游**有意在做**风格统一，只是执行面还没铺到存量代码（这解释了 `naming` 88.7 与 125 处超长行的来源）。

---

## 9. 建议（按 ROI 排序）

1. **不碰就不要改** —— 若只在 P.A.L.M 里直调 `TTS_infer_pack`，当前质量足够，重复与安全坏点都不在你的调用链上。
2. **若部署 `gsvi.py`**：把 `shutdown_password` 挪到环境变量/配置、`origin` 改成回环白名单、`/outputs/{result_path}` 加路径归一化校验。三处改动 < 20 行。
3. **若要二次开发**：先消 `webui.py` ↔ `train_util.py` 的 20 组克隆（1700+ 行），合并为单一实现；预计 `duplication` 从 E 档拉回 C 以上，并顺带压掉 `unit_size` 的超长计数。
4. **拆分靶点**：`TTS.py:985 run()`（CC 73 / 383 行）、`inference_webui.py:751 get_tts_wav()`（认知 140 / 16 参）、`patched_mha_with_cache.py:13`（416 行 / 26 参）。
5. **低成本清理**：8 处未用 import（`api.py:542` `chinese`、`train_util.py:63` `css/js/top_html` 等）；`yaml.load` 改 `safe_load`；`eval(os.environ...)` 改 `ast.literal_eval`。

---

## 附：复跑命令

```bash
SK=~/.workbuddy/skills/palm-metrics
EX='runtime/|pretrained_models/|__pycache__|f5_tts/|eres2net/|BigVGAN/|feature_extractor/|uvr5/|AP_BWE_main/|denoise-model/|tools/asr/'

# 结构质量（core / all 两口径）
python $SK/scripts/codequal.py 'C:/Users/24459/Desktop/GPT-SoVITS-1007-cu128' \
  --dims all --exclude "$EX" --top 20 --json audit_gpt_sovits/codequal_all_selfdev.json

# 安全静态扫描（注意：--exclude 是单参数，多条要用 | 合并成一个正则，重复传会互相覆盖）
python $SK/scripts/dynprobe.py --kind security \
  --path 'C:/Users/24459/Desktop/GPT-SoVITS-1007-cu128' --exclude "$EX" \
  --json audit_gpt_sovits/dynprobe_sec_selfdev.json
```

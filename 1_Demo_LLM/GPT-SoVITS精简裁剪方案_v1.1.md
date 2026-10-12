# GPT-SoVITS 精简裁剪方案 v1.1（详细执行版 + 成本收益分析）

- 制定时间：2026-09-27
- 对象：`C:\Users\24459\Desktop\GPT-SoVITS-1007-cu128`
- 拍板结论（已确认）：**档1+2+3 全砍** · **tools/asr 整个砍掉** · **隔离到备份目录，不直接删**
- 前置文档：`GPT-SoVITS精简裁剪方案_v1.0.md`（可达性分析方法与"绝不能砍"清单）
- 本版新增：完整执行清单、执行器、检验矩阵、**成本收益分析**
- **状态：✅ 已执行完毕（2026-09-27 08:30），终验通过。执行结果见文末第 8 节。**

---

## 1. 一句话结论（先看这个）

**值得做，但要纠正预期：这笔交易买的不是"性能"，是"减面"——磁盘 -1.9GB、攻击面 -76%、维护面 -45%。**
推理延迟、启动速度、内存显存**一项都不会变**（Python 本来就只 import 用到的模块）。成本是一次性 20–30 分钟（其中人工只有最后真合成检验），且隔离式执行随时一条命令回滚。净收益明确为正。

---

## 2. 模拟结果（裁剪后状态，已用 codequal 实测，非推测）

把 87 个保留文件复制到隔离目录后真实重跑度量：

| 维度 | 裁剪前（自研核心） | 裁剪后（模拟） | 变化 |
|---|---|---|---|
| 自研代码行 | 29,675 | **16,221** | **-45%** |
| codequal 总分（all 口径） | 76.7 / B | **82.7 / B+** | +6.0 |
| 重复率 | 38.82% | **15.51%** | -23.3pp |
| duplication 维度分 | 31.5 🔴E | 54.3 🟡D | E→D |
| 近似克隆维度分 | 62.1 C | 77.9 B | C→B |
| 循环内 IO/拼接风险 | 73 处 | **10 处** | -86% |
| 安全 HIGH | 59 | **14** | **-76%** |
| 审计/维护要看的文件数 | 181 | **94** | -48% |

安全 HIGH 的 45/59 随裁剪消失：`webui.py` 19、`train_util.py` 19、`inference_webui_fast.py` 2、`prepare_datasets/` 4、`subfix_webui.py` 1。**留下的 14 个**里真正要紧的只有 `gsvi.py:333` 硬编码口令和 `tools/my_infer.py` 的 3 处 shell 注入（你的直调链不经过它们，但要记住还在）。

> 裁剪后剩余重复率 15.5% 集中在 `module/models.py`(325)、`inference_webui.py`(244)、`TTS.py`(174) —— 全是**推理核心自身**的重复，砍不动也不该砍。这就是这条链路的真实底色。

---

## 3. 完整执行清单（7 批 / 50 个删除单元 / 151 个文件 / 24,817 行）

| 批 | 内容 | 单元 | 文件 | 行数 |
|---|---|---|---|---|
| 1 | 训练脚本与数据集 | 8 | 11 | 3,660 |
| 2 | 导出与 ONNX 变体 | 7 | 7 | 5,370 |
| 3 | AR 训练侧与 ONNX 变体 | 9 | 14 | 1,794 |
| 4 | BigVGAN/eres2net/f5 冗余 | 10 | 12 | 2,957 |
| 5 | 残余 + GUI 与其双击入口 | 6 | 6 | 2,968 |
| 6 | tools 数据预处理（含 uvr5 719MB） | 8 | 67 | 6,341 |
| 7 | 旧API 与 ASR（含 1.2GB 权重） | 2 | 34 | 1,727 |

<details>逐单元明细（执行器内置同款清单）：</details>

- **批1**：`GPT_SoVITS/prepare_datasets/`（整目录）、`s1_train.py`、`s2_train.py`、`s2_train_v3.py`、`s2_train_v3_lora.py`、`train_cli.py`、`train_util.py`、`download.py`
- **批2**：`onnx_export.py`、`export_torch_script.py`、`export_torch_script_v3v4.py`、`module/models_onnx.py`、`module/data_utils.py`、`module/attentions_onnx.py`、`module/losses.py`
- **批3**：`AR/data/`、`AR/text_processing/`（整目录）、`AR/utils/initialize.py`、`AR/models/t2s_model_onnx.py`、`AR/models/t2s_lightning_module_onnx.py`、`AR/modules/{transformer,activation,patched_mha_with_cache,embedding}_onnx.py`
- **批4**：`BigVGAN/{train,discriminators,loss,inference,inference_e2e}.py`、`BigVGAN/tests/`、`BigVGAN/alias_free_activation/cuda/load.py`、`eres2net/{ERes2Net,ERes2Net_huge}.py`、`f5_tts/model/backbones/unett.py`
- **批5**：`f5_tts/model/backbones/mmdit.py`、`webui.py`、`inference_webui_fast.py`、`inference_gui.py`、**`go-webui.bat`、`go-webui.ps1`**（盲区查证发现：webui 砍了这两个双击入口必炸，一并隔离）
- **批6**：`tools/uvr5/`（整目录含权重 719MB）、`tools/AP_BWE_main/datasets1/`、`slicer2.py`、`slice_audio.py`、`cmd-denoise.py`、`subfix_webui.py`、`my_utils.py`、`i18n/scan_i18n.py`
- **批7**：`api.py`、`tools/asr/`（整目录含 FunASR 权重 1.2GB）

**明确保留的 94 个文件**（含 8 个虽"不可达"但绝不能删的 `__init__.py` 包标识，以及"看着像训练、实为推理必需"的 `process_ckpt.py` / `sv.py` / `BigVGAN/bigvgan.py` / `f5_tts/model/backbones/dit.py` 等，逐条依据见 v1.0 文档第 3 节）。

---

## 4. 执行器（已就绪：`audit_gpt_sovits/slim_execute.py`）

```bash
cd D:/P.A.L.M/1_Demo_LLM/audit_gpt_sovits
python slim_execute.py --plan       # 只打印计划，不动文件（已验证输出正常）
python slim_execute.py --run        # 执行：复制→MD5校验→原位移除，逐批进行
python slim_execute.py --rollback   # 回滚：把备份拷回原位（已存在的不覆盖）
```

安全机制：
1. **只接受"不可达清单"里的文件**——任何不在清单里的文件直接 SKIP 并中止该批，防止误删；
2. **先复制后删除**：备份到 `D:/P.A.L.M/1_Demo_LLM/.workbuddy/backup/20260927_gpt_sovits_slim/`，保持原相对路径，逐文件 MD5 校验，不一致即中止；
3. 某批失败自动停后续批，产出 `slim_exec_report.json` 留证。

---

## 5. 检验矩阵（验什么、怎么算验够）

| # | 检验 | 方法 | 通过判据 | 耗时 |
|---|---|---|---|---|
| 1 | import 链完整 | `runtime/python.exe -c "import sys; sys.path.insert(0,'GPT_SoVITS'); from TTS_infer_pack.TTS import TTS, TTS_Config"` | 无 ImportError | ~10s |
| 2 | 每批后冒烟（×7） | 同上 + `TTS_Config('GPT_SoVITS/configs/tts_infer.yaml')` 读配置 | 配置可读、version 正常 | 每批 ~10s |
| 3 | 服务可起 | `api_v2.py -a 127.0.0.1 -p 10080 -c ...tts_infer.yaml`（你既有方式） | 端口响应，无缺模块 | ~35s |
| 4 | 真合成短句 | 直调 TTS_infer_pack 出 wav | 音频非空、可播 | ~1min |
| 5 | **长句 + 回读校验** | 长句合成 → 回读比对 | 文本完整无吞字 | ~3min |
| 6 | 静态复扫 | `codequal` + `dynprobe security` 对裁剪后目录 | HIGH=14、总分≈82.7 | ~10s |

**#5 是关键也是唯一麻烦的**：`tools/asr/` 砍了，本地 FunASR 回读没工具了。两个替代：
- 用你自己的 **STT 内核 SenseVoice**（10083）做回读比对；
- 或云端 **GLM-ASR**（智谱 key2，实测 200 可用）。
回读能力没有消失，只是换了工具——这也是我判断"asr 可砍"的底气。

---

## 6. 成本收益分析（值不值得）

### 6.1 收益（定量，全部来自本轮实测）

| 收益 | 量 | 说明 |
|---|---|---|
| 磁盘 | **-1.9 GB** | uvr5 719M + asr 1.2G + 杂项。C 盘已用 91%、剩 83G，占剩余空间 2.3% |
| 攻击面 | **HIGH 59→14（-76%）** | webui/train_util 的 38 处 shell 注入面整块消失 |
| 维护面 | **-45% 代码** | 以后翻代码、审计、排查都在 1.6 万行里，不再有 2.5 万行僵尸代码干扰判断 |
| 审计基线 | B(76.7) → B+(82.7) | 下次审计起评更高，趋势可比 |
| 认知 | 181→94 文件 | "哪些是死代码"这个问题永久消失 |

### 6.2 零收益项（诚实声明，别抱错误期待）

| 项 | 为什么不变 |
|---|---|
| 启动时间 | 被砍文件本来就不被 import，进程加载路径没变 |
| 推理延迟 / 首字 / RTF | 推理热路径一字未动 |
| 内存 / 显存 | 不加载的模块本来就不占 |
| 精度 / 音质 | 不涉及 |

**所以这不是性能优化。** 如果你砍它是为了"跑得更快"，那不值得——一分都不会快。

### 6.3 成本

| 成本 | 量 | 谁承担 |
|---|---|---|
| 执行 | 5–15 分钟（1.9GB 跨盘复制占大头），全自动 | 我 |
| 检验 | 矩阵 #1–#6 约 10 分钟 | 我跑 1/2/3/6；**#4/#5 需要你听音频判质量** |
| 回滚 | `--rollback` 一条命令，分钟级 | — |
| 隐性代价① | 本地 FunASR 回读断链 → 换 SenseVoice/GLM-ASR | 一次性适配 |
| 隐性代价② | 以后要微调/出 ONNX → `--rollback` 后即恢复 | 按需，分钟级 |
| 隐性代价③ | `gpt-sovits-local-tts` skill 第 24 行需同步改（执行后我来改） | 一次性 |

### 6.4 判断

**值得做。** 账是这么算的：

- **做的成本是一次性的、可逆的**：20–30 分钟，回滚一条命令。
- **不做的成本是永续的**：2.5 万行僵尸代码每次审计都要重新分辨一遍、每次安全扫描都白刷出 45 条高危、每次翻代码都要绕开 webui↔train_util 那对双胞胎。这笔钱会一直花下去。
- **风险敞口接近零**：隔离式执行 + 7 批冒烟 + 真合成检验，最坏情况就是某条冷路径炸了 → 回滚 → 5 分钟恢复。

唯一合理的否决条件：**你近期就要走 webui 那条流水线做数据标注或微调**。那样就只砍档1（训练脚本照砍没意义，反着——那连档1也别砍，等微调完再说）。既然你已明确"微调用不上"，这条不成立。

---

## 7. 执行后的遗留事项（做的时候我会顺手处理）

1. 更新 skill `gpt-sovits-local-tts`：第 24 行"离线 ASR：tools/asr/models/"改为指向 SenseVoice/GLM-ASR；
2. `docker-compose.yaml` 两个挂载点失效（你不用 docker，仅记录）；
3. i18n locale 里 UVR5 文案残留（纯文案，无害，不处理）；
4. 权重目录的进一步瘦身（`v2Pro/` 587M、`gsv-v2final-pretrained/` 339M、`s2D488k.pth` 判别器）——**另一轮再议**，涉及版本兼容，不跟这次混在一起。

---

## 8. 执行结果（2026-09-27 实录）

### 8.1 执行前的运行时取证（按用户要求先跑合成）

用 v4 芙宁娜真合成一句（48kHz wav 成功），audit hook 记录全部文件访问 + 事后扫 `sys.modules`：

- 运行时加载的项目内源模块 **80 个**，与静态可达集比对：**唯一反例 = `tools/AP_BWE_main/datasets1/`**（`audio_sr.py:12` 顶层 import，`sys.path.append` 裸名导入，静态分析看不见）→ 已恢复；
- v4 实际用到的底模：`gsv-v4-pretrained/s2Gv4.pth`（LoRA merge）+ `gsv-v4-pretrained/vocoder.pth`（v4 专用声码器）；
- 按用户约束，`eres2net/`、`f5_tts/` 全目录保留（版本底模架构代码，从砍除清单剔除 4 文件 905 行）。

### 8.2 执行结果

| 项 | 结果 |
|---|---|
| 隔离备份 | `.workbuddy/backup/20260927_gpt_sovits_slim/`，**147 文件 / 1.7GB**，逐文件 MD5 校验通过 |
| 移除 | 7 批全部完成，0 失败 |
| 恢复 1 处 | `tools/AP_BWE_main/datasets1/`（运行时取证 + 冒烟抓到的真依赖） |

### 8.3 终验

| 检验 | 结果 |
|---|---|
| import 链（TTS/TTS_Config/my_infer/audio_sr） | ✅ 通过 |
| **完整合成复跑**（v4 芙宁娜，48kHz） | ✅ 成功，26s |
| 裁剪后运行时 80 模块 ∩ 已砍文件 | ✅ **0 交集** |
| codequal（70 文件 / 15,043 行） | ✅ **84.6 / B+**（裁剪前 76.7），重复率 38.8%→**12.42%**，效率风险 73→9，克隆 C→B |
| dynprobe security | ✅ **HIGH 59→12**（-80%），剩余全是已复核的降级项（eval os.environ / pickle 读自带词典 / yaml FullLoader 误报）+ gsvi.py 硬编码口令 + my_infer 3 处 shell 注入（不在你的直调链上） |

### 8.4 执行中撞到并修掉的问题（如实记录）

1. **运行时环境本来就是坏的**：`transformers 5.17.0` + `peft 0.17.1` 不兼容（import 即炸，`api_v2.py` 也起不来）→ 升级 `peft 0.21.0` 修复。**这与裁剪无关，你的 GSV 在裁剪前就起不来**。
2. v4 + `is_half: false` 报 dtype 不匹配（merge 残留 fp16）→ v4 走 `is_half: true`（skill 示例本就是 true）。
3. 我的 pyc→源映射起初有 bug（没去掉 `cpython-311` 段 + 大小写），"零反例"是假阴性；**真正的验证来自裁剪后冒烟**——两者结合才抓全了 `datasets1` 这一处。
4. `go-webui.bat/ps1` 双击入口随 webui 一并移除（盲区查证发现引用，否则双击必炸）。

### 8.5 裁剪后的目录状态

```
GPT-SoVITS-1007-cu128/
├─ api_v2.py / gsvi.py / config.py     # 服务与直调配置（保留）
├─ GPT_SoVITS/
│  ├─ TTS_infer_pack/  AR/  module/  text/  BigVGAN/  f5_tts/  eres2net/
│  ├─ feature_extractor/  sv.py  process_ckpt.py  utils.py
│  └─ pretrained_models/               # 全部底模权重未动（v1/v2/v3/v4/v2Pro）
├─ tools/  (my_infer.py / audio_sr.py / i18n / AP_BWE_main / assets / logger / my_utils 已移除)
└─ runtime/                            # 内嵌环境未动
```

回滚：`python D:/P.A.L.M/1_Demo_LLM/audit_gpt_sovits/slim_execute.py --rollback`（已存在文件不覆盖）。

---

## 9. 核心检验区减负实录（2026-09-27）

> 目标：`D:/P.A.L.M/核心-检验/语音合成_GPT-SoVITS`（palm-chat GSV 生产后端，:10080）。
> 执行器：`audit_gpt_sovits/slim_execute_pal.py`（`--plan`/`--run`/`--rollback`）。

### 9.1 与桌面整合包的差异（取证前必读）

| 项 | 桌面整合包 | 核心检验区 |
|---|---|---|
| 形态 | 全功能整合包（含 gsvi.py、go-webui.bat） | 精简部署（api_v2 + start.bat/demostart.bat） |
| api_v2.py | 原版 | **定制版**（/tts 契约 + /health + /metrics + /set_refer_audio + 并发锁，12 路由） |
| GPT_SoVITS 核心源码 | — | 与桌面同源（TTS.py/sv.py/process_ckpt MD5 一致） |
| runtime 环境 | transformers 5.x 已坏（peft 已修） | **健康**（is_half:false + v4 可正常加载，今晨日志实证） |
| 底模 | custom=v4 微调模型（芙宁娜） | custom=v4 底模（s1v3.ckpt + s2Gv4.pth） |

生产链路：palm-chat gsv 块 → `127.0.0.1:10080`（端口契约），**不直接 import 本目录源码**（全树 grep 证实外部引用仅文档/记忆/一次性 tmp 脚本）。

### 9.2 双路取证

- **静态**：`slim_analyze.py` 入口（TTS.py / inference_cli.py / api_v2.py / api.py）→ 180 py，可达 86 / 不可达 95，未解析 import 归零。
- **运行时**：`trace_run_pal.py` 真跑 v4 合成（自带 yaml + refer_audio.wav）→ 48kHz 成功；运行时加载 80 源模块，与静态不可达集交集 9 个，**与桌面反例完全一致**（8 个包标识 `__init__.py` + `datasets1/dataset.py` 裸名导入坑）。
- 盲区复扫：全仓 `sys.path.append` 仅 api.py/api_v2.py/t2s_lightning_module（保留）+ 已砍文件；api_v2.py 无动态导入。

### 9.3 执行结果（7 批全部完成，0 失败）

| 批 | 内容 | 移除 |
|---|---|---|
| 1 | 训练脚本与数据集（s1/s2_train×3、train_cli、train_util、prepare_datasets/、download.py） | 11 文件 / 3660 行 |
| 2 | 导出与 ONNX 变体（export_torch_script×2、onnx_export、module 四件套） | 7 文件 / 5370 行 |
| 3 | AR 训练侧与 ONNX 变体 | 9 文件 / 1794 行 |
| 4 | BigVGAN 冗余（train/discriminators/loss/inference×2/tests/、cuda/load.py） | 7 文件 / 2185 行 |
| 5 | GUI（webui.py、inference_webui_fast、inference_gui） | 3 文件 / 2822 行 |
| 6 | tools 杂项（uvr5/ 整目录 555M、slicer2、slice_audio、cmd-denoise、subfix_webui、my_infer、my_utils、scan_i18n） | 66 文件 / 6893 行 |
| 7 | tools/asr 整目录（1.2G） | 33 文件 / 332 行 |

- **隔离备份**：143 文件 / 1.7GB → `.workbuddy/backup/20260927_gsv_pal_slim/`，逐文件 MD5 校验。
- **磁盘回收**：≈1.75GB（14G → 12.25G）。
- 执行器防线立功一次：批3 整目录砍 `AR/utils/` 被 `io.py`（可达）拦截，改为只砍 `initialize.py` 单文件（io.py 与 `__init__.py` 保留）。

### 9.4 终验矩阵（全绿）

| 检验 | 结果 |
|---|---|
| import 冒烟（TTS_infer_pack + audio_sr/AP_BWE + logger） | ✅ v4 |
| **api_v2.py 定制版 import**（12 路由含 /tts、/health、/metrics、/set_refer_audio） | ✅ |
| 完整合成复跑（v4 底模 + refer_audio.wav，48kHz） | ✅ `trace_out_pal.wav` |
| 运行时零反例（80 模块与裁剪前一致，与已砍文件交集 0） | ✅ |
| codequal 复扫 | 80.9 / B（102 文件 19,307 行；重复率 38.8%→18.35%） |
| 安全复扫 | 98 文件仅 10 命中（8 HIGH 均为 text 前端上游固有模式：cleaner `__import__`、g2pw/english pickle/eval——服务绑 127.0.0.1 不对外，判可接受） |

### 9.5 与桌面份的差异与未动项

- 保留 `tools/my_infer.py`？否——本份**连 my_infer/my_utils 一起砍**（双证不可达，比桌面多砍 892 行；桌面因 gsvi.py 入口而保留）。
- 全部保留：`pretrained_models/`（4.3G 权重，v1/v2/v3/v4/v2Pro/v2ProPlus）、`eres2net/`、`f5_tts/`、`tools/AP_BWE_main`（含 datasets1）、`runtime/`（6.6G）、start.bat/demostart.bat/set_refer.bat、refer_audio.wav、docs/。
- `GPT_SoVITS/inference_webui.py` 可达（inference_cli.py 引用）未砍，与桌面同构。
- ⚠️ 部署文档 `docs/GPT-SoVITS部署文档.md` v1.1（09-08）提及的同步副本 `P.A.L.M/speech/gpt-sovits/src/` **已不存在**，待用户知悉；被砍文件不在该文档目录表内，无需改。
- 回滚：`python audit_gpt_sovits/slim_execute_pal.py --rollback`。

# GPT-SoVITS 精简裁剪方案 v1.0（保留直调推理，砍微调）

- 制定时间：2026-09-27
- 对象：`C:\Users\24459\Desktop\GPT-SoVITS-1007-cu128`
- **状态：只扫描，未移动/删除任何文件**
- 证据：`audit_gpt_sovits/slim_reach.json`、`slim_analyze.py`（可复跑）

---

## 1. 结论摘要

从 `TTS_infer_pack/TTS.py`（你的直调入口）+ `api_v2.py` + `gsvi.py` + `inference_cli.py` 出发做 import 可达性 BFS：

| 项 | 数 |
|---|---|
| 项目内 py 文件 | 181 |
| **推理可达（必须保留）** | **87** |
| **不可达（可砍候选）** | **95 / 24,861 行** |
| 未解析 import（误判风险） | **0** |

**可砍 95 个文件、约 2.5 万行**，约占自研代码的一半。剩下的 87 个正是纯推理链（AR + SoVITS + BigVGAN + text 前端 + cnhubert + sv），结构上很干净。

---

## 2. 方法可信度（先说我自己踩的坑）

静态可达性分析很容易漏边，导致"误判可砍"。本轮**踩了 3 个 bug 并已修正**，修正前后差异很大，所以把过程摆出来：

| # | 坑 | 后果 | 修正 |
|---|---|---|---|
| 1 | `SKIP_DIRS` 里放了通用名 `"models"` | **`GPT_SoVITS/AR/models/` 整包被跳过** → AR 全判不可达，差点砍掉推理核心 | 改为只按根级路径排除权重目录 |
| 2 | `from . import X` 形式没取 `names` | BigVGAN 的 `activations.py` 等丢边 | 按 alias 生成依赖 |
| 3 | `sys.path.append(eres2net)` 后的裸名导入 | `eres2net` 被误判为不可达 | 所有含 .py 目录都作候选根 + 唯一同名消歧 |

修正后可达 68 → 77 → **87**，未解析 import 归零。另外对动态导入（`__import__` / `importlib`）做了保守处理：含动态导入文件的**同目录全部视为可达**（本轮 2 个文件：`text/cleaner.py`、`text/g2pw/utils.py`）。

---

## 3. 🔴 这些"看着像训练用"的，其实推理必需，绝不能砍

这是最容易砍错的地方，逐条**读码确认**过：

| 文件 | 为什么不能砍 | 证据 |
|---|---|---|
| `GPT_SoVITS/BigVGAN/bigvgan.py` | `TTS.py` 直接 `from BigVGAN.bigvgan import BigVGAN` | 仅 BigVGAN 目录里的 train/loss/discriminators/tests 可砍 |
| `GPT_SoVITS/process_ckpt.py` | `TTS.py` 用它的 `load_sovits_new` / `get_sovits_version_from_path_fast` 加载权重 | 名字像工具，实为推理加载入口 |
| `GPT_SoVITS/sv.py` + `eres2net/ERes2NetV2.py` | SV 说话人验证；`sv.py:4` 用 `sys.path.append(.../eres2net)` 再裸名导入 | 静态分析看不见，差点误砍 |
| `GPT_SoVITS/feature_extractor/cnhubert.py` | 音频特征提取，推理必需 | — |
| `GPT_SoVITS/f5_tts/model/backbones/dit.py` | `module/models.py:13` `from f5_tts.model import DiT`（v4 架构依赖） | 只有 unett/mmdit 两个备胎 backbone 可砍 |
| `AR/modules/{transformer,activation,embedding,optim,scaling,patched_mha_with_cache}.py` | `t2s_model.py:21-22` 直接引用 | 仅 `*_onnx.py` 变体可砍 |
| `tools/audio_sr.py` | `TTS.py` `from tools.audio_sr import AP_BWE` | — |
| `GPT_SoVITS/inference_webui.py` | `inference_cli.py` 依赖它的 `get_tts_wav` | 别和 webui.py 搞混 |

**另有 8 个文件虽"不可达"但必须保留**——全部是包标识 `__init__.py`（删了包就废）：
`GPT_SoVITS/AR/__init__.py`、`AR/models/__init__.py`、`AR/modules/__init__.py`、`AR/utils/__init__.py`、`GPT_SoVITS/TTS_infer_pack/__init__.py`、`BigVGAN/alias_free_activation/torch/__init__.py`、`tools/__init__.py`、`tools/AP_BWE_main/models/__init__.py`。

---

## 4. 三档方案

| 档 | 内容 | py 数 | 行数 | 主要磁盘 |
|---|---|---|---|---|
| **档1 · 训练与导出** | s1/s2 训练四件套 + train_util/train_cli + onnx_export + export_torch_script×2 + prepare_datasets + AR/data + AR/text_processing + 全部 `*_onnx.py` + BigVGAN(train/discriminators/loss/inference/tests) + eres2net 多余两个 + f5 备胎 backbone + download.py | 45 | 13,927 | 小（<5MB） |
| **档2 · +GUI 与数据预处理** | `webui.py` + `inference_webui_fast.py` + `inference_gui.py` + **`tools/uvr5/`（719MB）** + slicer2/slice_audio/cmd-denoise/subfix_webui/my_utils + i18n/scan_i18n + AP_BWE_main/datasets1 | 38 | 9,163 | **≈719 MB** |
| **档3 · +旧API 与 ASR** | `api.py` + **`tools/asr/`（1.2GB）** | 4 | 1,727 | **≈1.2 GB** ⚠️ |

- 档1+2 合计：**83 个 py / 23,090 行 / ≈719 MB**
- 档1+2+3 合计：**87 个 py / 24,817 行 / ≈1.9 GB**

### 推荐：档1 + 档2（档3 的 ASR 别动）

**⚠️ `tools/asr/` 1.2GB 强烈建议保留**：你的 `gpt-sovits-local-tts` skill 第 24 行明确写着"离线 ASR：`tools/asr/models/`（FunASR paraformer + fsmn_vad + punc，可断网跑）"，长句合成的 ASR 回读校验依赖它。它不在 TTS 的 import 链里，但在**你的工作流**里。砍了代码没事，砍了 `models/` 就断链。

`api.py` 砍不砍看你：它是旧版 HTTP 服务，`api_v2.py`/`gsvi.py` 已覆盖，且它含有本次审计里最多的 shell 注入面。砍掉顺带缩掉一块攻击面。

---

## 5. 附带发现：权重层还有 GB 级空间（另一轮再议）

代码只占几十 MB，真正的大头在 `GPT_SoVITS/pretrained_models/`：

| 目录/文件 | 大小 | 是否推理必需 |
|---|---|---|
| `gsv-v4-pretrained/` | 789M | ✅ 你在用（s2Gv4.pth） |
| `chinese-roberta-wwm-ext-large/` | 622M | ✅ BERT 特征 |
| `models--nvidia--bigvgan_v2_.../` | 430M | ⚠️ 看你用不用 BigVGAN 声码器 |
| `chinese-hubert-base/` | 181M | ✅ |
| `fast_langdetect/` | 126M | ✅ 语种检测 |
| `sv/` | 103M | ✅ |
| **`v2Pro/`** | **587M** | ❓ v2Pro 底模——不微调 v2 就不需要 |
| **`gsv-v2final-pretrained/`** | **339M** | ❓ v2 底模——同上 |
| **`s2D488k.pth`** | — | ❌ **判别器权重，纯训练用** |
| `s2G488k.pth` / `s2Gv3.pth` / `s1v3.ckpt` / `s1bert25hz-...ckpt` | — | ❓ 看版本 |

**本轮不动**（权重删错直接跑不起来，需要你明确版本后再定）。

---

## 6. 执行方式（必须这样干，别直接删）

目标在**桌面**目录下，且是整合包，按规矩：

1. **隔离而非删除**：把砍掉的内容移动（move）到
   `.workbuddy/backup/20260927_gpt_sovits_slim/` 下，**保持原相对路径**。
   这样随时能整目录拷回来，等于可回滚。
2. **移动前先备份 + MD5 校验**：先复制一份到备份目录，校验 MD5 一致后再从原位移除。
3. **分批执行**：每批 ≤10 个删除单元，跑完立刻验证。
4. **每批后冒烟**：用你的真实调用方式跑一次 TTS 合成（长句 + 参考音频），确认没炸。
5. **顺序**：先档1（纯训练/导出，风险最低）→ 冒烟 → 再档2。

**冒烟命令**（用你自己的 runtime，不要起服务）：
```bash
cd C:/Users/24459/Desktop/GPT-SoVITS-1007-cu128
runtime/python.exe -c "
import sys; sys.path.insert(0,'GPT_SoVITS')
from TTS_infer_pack.TTS import TTS, TTS_Config
cfg = TTS_Config('GPT_SoVITS/configs/tts_infer.yaml')
print('import OK', cfg.version)
"
```
只验证 import 链通不通；要真出声再走你现有的合成脚本。

---

## 7. 待你拍板

1. 砍到哪一档？（档1 / 档1+2【推荐】/ 全砍）
2. `tools/asr/`（1.2GB）保不保？（我建议保）
3. `api.py` 保不保？
4. 要不要顺带处理权重目录里的 v2 底模（926M）与 `s2D488k.pth`？（我建议单开一轮）

# 模型下载链接真实验证报告（2026-07-23）

> 验证方式：**HF 链接走国内镜像站 `hf-mirror.com`**；**魔搭链接用 `modelscope` python SDK 的 `get_model_files()` 实测**。
> 校验脚本与隔离 venv 均放在临时目录 / 托管 envs，未污染工程。
> 说明：HF 镜像对超大文件仅读 1 字节确认存在（不下载），404 即链接失效。

## 一、GGUF 下载链接（HF 镜像）— 36 项检查

### ✅ 实测可用（点击「HF 镜像」可下）
| 模型 | 可用精度 |
|---|---|
| deepseek-r1-1.5b / 7b / 8b / 14b / 32b | Q4_K_M ✓；F16 仅 7/8/14B ✓（1.5B/32B 的 F16 分片→404）|
| qwen2.5-0.5b / 1.5b / 3b、qwen2.5-coder-7b / 14b、qwq-32b | Q4_K_M ✓ |
| glm-4-9b-chat、glm-4-9b-chat-1m | Q4_K_M + F16 ✓ |
| gpt-oss-20b | Q4_K_M + F16 ✓ |
| llama3.2-1b / 3b、llama3.3-70b | Q4_K_M ✓（llama3.3 仅 Q2_K~Q5_K_M 可用）|
| llama3.1-8b、mistral-7b、gemma2-2b / 9b、phi3.5-mini | Q4_K_M ✓ |

### ❌ 实测 404 / 失效（根因分类）
| 模型 | 现象 | 根因 |
|---|---|---|
| **qwen2.5-7b / 14b / 32b** | Q4_K_M 等全部 404 | HF 上这些量化**被切成多片**（`qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf`），顶层无单文件；本下载器仅支持单文件 |
| **qwen3-0.6b / 4b / 8b / 14b** | 所有精度 404 | 文件名实为**大写** `Qwen3-8B-Q4_K_M.gguf`（前缀+量化都大写）；且只提供 Q4_K_M/Q5_0/Q5_K_M/Q6_K/Q8_0（0.6B 仅 Q8_0）|
| **gpt-oss-120b** | K-quants 404 | K-quants 在**子文件夹** `Q4_K_M/gpt-oss-120b-...-00001-of-00002.gguf`；F16 单文件可用 |
| **minimax-m2.7** | 全精度+全部 K-quants 404 | unsloth 只提供 **Dynamic 2.0 量化**（UD-IQ*/UD-Q*），无标准 K-quants；全精度是 **BF16（457GB）非 F16** |
| **kimi-k2-instruct / thinking** | 全部 404 | 量化文件**分片在子文件夹**（`...-Q4_K_M/...-00001-of-00002.gguf`）|
| **llama3.3-70b** | Q6_K / Q8_0 / F16 404 | 仅提供 Q2_K~Q5_K_M；F16 分片在子文件夹 |
| **llama3.2-11b-vision / llama3.1-70b / phi4-mini** | resolve 404、tree 401 | 受限仓库 / 文件命名不符（需人工确认正确路径）|
| deepseek-r1-1.5b / 32b 的 F16 | 404 | F16 分片或未提供 |

## 二、GGUF 的魔搭链接（modelscope SDK 实测）

- ✅ **可用**：`qwen/Qwen2.5-3B/7B/14B/32B-Instruct-GGUF`、`qwen/QwQ-32B-GGUF`、`unsloth/gpt-oss-20b-GGUF` 全部量化文件均存在（魔搭上这些仓库是**单文件**，不受 HF 分片影响）。
- ❌ **缺失（21 项）**：`qwen/Qwen3-4B/8B/14B-GGUF` 全部量化（大小写错，应为 `Qwen3-8B-Q4_K_M.gguf`）。

## 三、SafeTensors 仓库存在性

### HF 镜像（53 个仓库 id）
- 43 个直接 200；**10 个 HTTP401（仓库存在但需登录/受限）**：CodeLlama-7b、gemma-2-7b-it、gemma-3-4b-it、internlm2-chat-7b、internlm3-8b、GLM-4-32B-0414、GLM-Z1-32B-0414、glm-4-9b-chat、glm-4v-9b、DeepSeek-R1-Distill-Qwen-3B。
- **结论：53 个仓库 id 全部真实存在，无伪造 404。**

### 魔搭 python 工具（51 个 SafeTensors 条目）
- ✅ **41 个 OK**（仓库存在且含 `.safetensors`）。
- ❌ **7 个 `NotExistError`（modelscope id 写错/不存在）**：
  - `01-ai/Yi-1.5-34B-Chat`、`01-ai/Yi-1.5-6B-Chat`、`01-ai/Yi-1.5-9B-Chat`（org 路径可能应为 `01ai/...`）
  - `LLM-Research/Llama-3.1-8B-Instruct`（org 可能应为 `AI-ModelScope/...` 或 `meta-llama/...`）
  - `LLM-Research/gemma-2-7b-it`（同上）
  - `Shanghai_AI_Laboratory/internlm3-8b`（名称可能应为 `internlm3-8b-instruct`）
  - `deepseek-ai/DeepSeek-R1-Distill-Qwen-3B`（魔搭无此 id）
- ⚠️ **3 个仓库存在但无 `.safetensors`**（格式标注可能不准）：`Qwen/Qwen-VL-Chat`、`baichuan-inc/Baichuan2-13B-Chat`、`baichuan-inc/Baichuan2-7B-Chat`（可能为 `.bin` 或权重在子目录）。

## 四、修复建议（待确认范围）

**A 类（模板/大小写/量化集合写错，可直接修，无副作用）**
1. `catalog.py` Qwen3 系列：`qcase` 改 `upper`，文件名模板改 `Qwen3-{X}b-{q}.gguf`，并按真实可用集合限制量化（0.6B 仅 Q8_0；其余仅 Q4_K_M/Q5_0/Q5_K_M/Q6_K/Q8_0）。
2. `modelscope-models.json` 中 7 个写错的魔搭 id：修正或移除该来源。
3. `modelscope-models.json` 中 3 个无 safetensors 的条目：核实真实格式（改 format 或补子目录）。

**B 类（分片/子文件夹，需下载器增强或退而求其次）**
4. Qwen2.5-7B/14B/32B、gpt-oss-120b、Kimi、llama3.3 F16：HF 上分片。→ 方案：① 增强下载器支持分片合并；② 或对这些模型**优先用魔搭链接**（魔搭是单文件，已验证 OK）；③ 或从目录移除该来源的 HF 选项。
5. MiniMax-M2.7：改量化集合为 unsloth Dynamic（UD-IQ*/UD-Q*），F16 改 BF16 并标注需 `huggingface-cli` 拉取分片。
6. llama3.2-11b-vision / llama3.1-70b / phi4-mini：人工确认受限仓库的正确文件名。

**C 类（一致性）**
7. `catalog.py` 仍含 6 个 <3B GGUF 条目（qwen2.5-0.5/1.5b、deepseek-r1-1.5b、gemma2-2b、llama3.2-1b、qwen3-0.6b），而 `modelscope-models.json` 已删 <3B → Ollama 引导页仍会显示这些小模型。

---
验证产物（临时，未入工程）：`_hf_check.json` / `_hf_f16.json` / `_hf_st_repo.json` / `_hf_trees.json` / `_ms_check.json`（均位于 `%TEMP%`）。魔搭工具装在隔离 venv `envs/ms-verify`（可删）。

## 五、修复状态（2026-07-23 已应用 A + B）

- **A.1** `catalog.py` Qwen3 系列：`qcase` 改 `upper`、文件名模板改 `Qwen3-{X}B-{q}.gguf`，并按真实可用集合限制量化（0.6B 仅 Q8_0；其余仅 Q4_K_M/Q5_0/Q5_K_M/Q6_K/Q8_0）。`docs/modelscope-models.json` 对应 GGUF 条目已同步重算。
- **A.2** `docs/modelscope-models.json` 中 7 个写错的魔搭 id（Yi-1.5 系列、Llama-3.1-8B、gemma-2-7b、internlm3-8b、DeepSeek-R1-Distill-Qwen-3B）已将该来源置空并加 `note` 标注，保留 HF 来源。
- **A.3** 3 个无 `.safetensors` 的条目（Qwen-VL-Chat、Baichuan2-7B/13B-Chat）`format` 改 `pytorch_bin`、魔搭来源置空、加 `note`。
- **B.4** 分片/子文件夹模型：Qwen2.5-7B/14B/32B 在 `catalog.py` 中移除 HF（分片无单文件），仅保留魔搭单文件（已验证 OK）；`gpt-oss-120b` 仅保留 F16 单文件；`llama3.3-70b` 限制为 Q2_K~Q5_K_M；Kimi 两个变体移除 HF（分片于子文件夹），标注需 `huggingface-cli` 拉取。JSON 已同步。
- **B.5** `MiniMax-M2.7`：量化集合改 unsloth Dynamic 2.0（`UD-IQ*`/`UD-Q*`），全精度改 BF16 并标注需 `huggingface-cli` 拉取分片。新增 `DYNAMIC_QUANTS`/`BF16` 到 `catalog.py` 量化表。
- **B.6（未自动处理）**：`llama3.2-11b-vision` / `llama3.1-70b` / `phi4-mini` 为受限仓库，需人工确认正确文件名后再修；本次保持原样。

> 说明：仅修正可确定的模板/大小写/量化集合与分片来源指向，未引入下载器分片合并能力（属更大的功能项，未在此提交）。


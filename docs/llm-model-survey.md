# 开源 LLM 大模型检索记录（HF 镜像 + 魔搭社区）

> 用途：为 Ollama 引导向导提供可下载的 GGUF 模型清单。本文件是「记录」，代码的真实数据源在
> `backend/app/bricks/ollama/catalog.py`。URL 均指向 **GGUF 量化版本**（Ollama 本地运行所需格式）。
> 默认量化均为 **Q4_K_M**（质量/体积平衡，推荐起步）。
>
> 生成时间：2026-07-23。来源：HuggingFace 官方/主流量化作者仓库 + 魔搭社区，文件名已逐项核对。
> 最近更新：扩大至 **36 个模型**，并新增 **GPT-OSS（OpenAI 开放权重）**、**Kimi-K2（MoonshotAI）**、
> **Llama 3.2 / 3.3 / 3.1-70B**，F16 全精度现覆盖 10 个仓库。

## 一、下载源与精度说明

| 来源 | 地址 | 备注 |
|---|---|---|
| HF 镜像（国内） | `https://hf-mirror.com` | 替代 `huggingface.co`，规避境外网络问题；文件命名与官方一致 |
| 魔搭社区 | `https://modelscope.cn/models` | 目前仅 Qwen 官方仓库 + GPT-OSS-20B 有稳定 GGUF 镜像；其余多为社区镜像且文件名不统一 |

**精度档位**：
- 标准 K-quants：`Q2_K`（最小体积）、`Q3_K_M`、`Q4_0`、`Q4_K_M`（推荐）、`Q5_K_M`、`Q6_K`、`Q8_0`（近无损）。
- **F16 全精度（半精度权重）**：体积约为 Q4_K_M 的 3.3 倍。仅在确实提供 f16 文件的仓库出现，
  通过每模型显式 `f16_file` 指定，避免大小写猜错导致 404（F16 仅 HF 提供，魔搭留空）。
- 当前支持 F16 的 10 个仓库：`DeepSeek-R1` 蒸馏全系列（1.5/7/8/14/32B）、`GLM-4-9B-Chat-1M`、
  `MiniMax-M2.7`、`GPT-OSS-20B`、`GPT-OSS-120B`、`Llama-3.3-70B`。

**文件名大小写约定（已确认）**：
- Qwen 官方仓库：`小写`，如 `qwen2.5-7b-instruct-q4_k_m.gguf`
- bartowski / unsloth / moonshot：`大写量化后缀`，如 `Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf`、
  `DeepSeek-R1-Distill-Qwen-7B-Q4_K_M.gguf`、`gpt-oss-120b-Q4_K_M.gguf`、
  `moonshotai_Kimi-K2-Instruct-0905-Q4_K_M.gguf`
- F16 文件名由仓库决定：`gpt-oss-120b-F16.gguf`（unsloth，大写）/ `glm-4-9b-chat-1m-f16.gguf`（bartowski，小写）

**分片提醒**：≥32B 模型常被切分为多文件（`xxx-q4_k_m-00001-of-00002.gguf`）。当前下载器按单文件下载，
遇到分片需手动合并（`llama-gguf-split --merge`）或改用 `huggingface-cli` / `modelscope snapshot_download`。

## 二、模型清单（按参数量从小到大）

| 模型名称 | 参数量 | 默认量化 | HF 仓库 / 文件(Q4_K_M) | 魔搭仓库 / 文件 | 备注 |
|---|---|---|---|---|---|
| Qwen2.5 0.5B Instruct | 0.5B | Q4_K_M | `Qwen/Qwen2.5-0.5B-Instruct-GGUF` / `qwen2.5-0.5b-instruct-q4_k_m.gguf` | `qwen/Qwen2.5-0.5B-Instruct-GGUF` / 同名 | 官方+魔搭稳定 |
| Qwen3 0.6B Instruct | 0.6B | Q4_K_M | `Qwen/Qwen3-0.6B-GGUF` / `qwen3-0.6b-q4_k_m.gguf` | `qwen/Qwen3-0.6B-GGUF` / 同名 | 2025 新系列，官方+魔搭 |
| Qwen2.5 1.5B Instruct | 1.5B | Q4_K_M | `Qwen/Qwen2.5-1.5B-Instruct-GGUF` / `qwen2.5-1.5b-instruct-q4_k_m.gguf` | `qwen/Qwen2.5-1.5B-Instruct-GGUF` / 同名 | 官方+魔搭稳定 |
| Llama 3.2 1B Instruct | 1B | Q4_K_M | `unsloth/Llama-3.2-1B-Instruct-GGUF` / `Llama-3.2-1B-Instruct-Q4_K_M.gguf` | — | 2024 小模型，无 F16 |
| DeepSeek-R1 Distill Qwen 1.5B | 1.5B | Q4_K_M | `unsloth/DeepSeek-R1-Distill-Qwen-1.5B-GGUF` / `DeepSeek-R1-Distill-Qwen-1.5B-Q4_K_M.gguf` | — | 魔搭暂无；**支持 F16** |
| Qwen2.5 3B Instruct | 3B | Q4_K_M | `Qwen/Qwen2.5-3B-Instruct-GGUF` / `qwen2.5-3b-instruct-q4_k_m.gguf` | `qwen/Qwen2.5-3B-Instruct-GGUF` / 同名 | 官方+魔搭稳定 |
| Llama 3.2 3B Instruct | 3B | Q4_K_M | `unsloth/Llama-3.2-3B-Instruct-GGUF` / `Llama-3.2-3B-Instruct-Q4_K_M.gguf` | — | 2024 小模型，无 F16 |
| Gemma 2 2B Instruct | 2B | Q4_K_M | `bartowski/gemma-2-2b-it-GGUF` / `gemma-2-2b-it-Q4_K_M.gguf` | — | 魔搭暂无稳定镜像 |
| Qwen3 4B Instruct | 4B | Q4_K_M | `Qwen/Qwen3-4B-GGUF` / `qwen3-4b-q4_k_m.gguf` | `qwen/Qwen3-4B-GGUF` / 同名 | 2025 新系列，官方+魔搭 |
| Phi-3.5 mini Instruct | 3.8B | Q4_K_M | `bartowski/Phi-3.5-mini-instruct-GGUF` / `Phi-3.5-mini-instruct-Q4_K_M.gguf` | — | 魔搭暂无稳定镜像 |
| Phi-4 mini Instruct | 3.8B | Q4_K_M | `bartowski/Phi-4-mini-instruct-GGUF` / `Phi-4-mini-instruct-Q4_K_M.gguf` | — | 魔搭暂无稳定镜像 |
| Qwen2.5 7B Instruct | 7B | Q4_K_M | `Qwen/Qwen2.5-7B-Instruct-GGUF` / `qwen2.5-7b-instruct-q4_k_m.gguf` | `qwen/Qwen2.5-7B-Instruct-GGUF` / 同名 | 官方+魔搭稳定，已核实 |
| Qwen2.5-Coder 7B Instruct | 7B | Q4_K_M | `Qwen/Qwen2.5-Coder-7B-Instruct-GGUF` / `qwen2.5-coder-7b-instruct-q4_k_m.gguf` | `qwen/Qwen2.5-Coder-7B-Instruct-GGUF` / 同名 | 代码模型，官方+魔搭 |
| DeepSeek-R1 Distill Qwen 7B | 7B | Q4_K_M | `unsloth/DeepSeek-R1-Distill-Qwen-7B-GGUF` / `DeepSeek-R1-Distill-Qwen-7B-Q4_K_M.gguf` | — | 魔搭暂无；**支持 F16** |
| Mistral 7B Instruct v0.3 | 7B | Q4_K_M | `bartowski/Mistral-7B-Instruct-v0.3-GGUF` / `Mistral-7B-Instruct-v0.3-Q4_K_M.gguf` | — | 魔搭暂无稳定镜像 |
| Llama 3.1 8B Instruct | 8B | Q4_K_M | `bartowski/Meta-Llama-3.1-8B-Instruct-GGUF` / `Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf` | — | 注意 `Meta-` 前缀，已核实 |
| Qwen3 8B Instruct | 8B | Q4_K_M | `Qwen/Qwen3-8B-GGUF` / `qwen3-8b-q4_k_m.gguf` | `qwen/Qwen3-8B-GGUF` / 同名 | 2025 新系列，官方+魔搭 |
| DeepSeek-R1 Distill Llama 8B | 8B | Q4_K_M | `unsloth/DeepSeek-R1-Distill-Llama-8B-GGUF` / `DeepSeek-R1-Distill-Llama-8B-Q4_K_M.gguf` | — | 魔搭暂无；**支持 F16** |
| Gemma 2 9B Instruct | 9B | Q4_K_M | `bartowski/gemma-2-9b-it-GGUF` / `gemma-2-9b-it-Q4_K_M.gguf` | — | 魔搭暂无稳定镜像 |
| GLM-4 9B Chat | 9B | Q4_K_M | `bartowski/glm-4-9b-chat-GGUF` / `glm-4-9b-chat-Q4_K_M.gguf` | — | 智谱 GLM 系列 |
| GLM-4 9B Chat 1M | 9B | Q4_K_M | `bartowski/glm-4-9b-chat-1m-GGUF` / `glm-4-9b-chat-1m-Q4_K_M.gguf` | — | 长上下文(1M)；**支持 F16(f16 小写)** |
| Llama 3.2 11B Vision Instruct | 11B | Q4_K_M | `unsloth/Llama-3.2-11B-Vision-Instruct-GGUF` / `Llama-3.2-11B-Vision-Instruct-Q4_K_M.gguf` | — | 多模态(视觉)，无 F16 |
| GPT-OSS 20B（OpenAI 开放权重） | 21B（3.6B 激活） | Q4_K_M | `unsloth/gpt-oss-20b-GGUF` / `gpt-oss-20b-Q4_K_M.gguf` | `unsloth/gpt-oss-20b-GGUF` / 同名 | Apache-2.0；**支持 F16**；魔搭仅 20B 稳定 |
| Qwen2.5 14B Instruct | 14B | Q4_K_M | `Qwen/Qwen2.5-14B-Instruct-GGUF` / `qwen2.5-14b-instruct-q4_k_m.gguf` | `qwen/Qwen2.5-14B-Instruct-GGUF` / 同名 | 官方+魔搭稳定 |
| Qwen2.5-Coder 14B Instruct | 14B | Q4_K_M | `Qwen/Qwen2.5-Coder-14B-Instruct-GGUF` / `qwen2.5-coder-14b-instruct-q4_k_m.gguf` | `qwen/Qwen2.5-Coder-14B-Instruct-GGUF` / 同名 | 代码模型，官方+魔搭 |
| DeepSeek-R1 Distill Qwen 14B | 14B | Q4_K_M | `unsloth/DeepSeek-R1-Distill-Qwen-14B-GGUF` / `DeepSeek-R1-Distill-Qwen-14B-Q4_K_M.gguf` | — | 魔搭暂无；**支持 F16** |
| Qwen3 14B Instruct | 14B | Q4_K_M | `Qwen/Qwen3-14B-GGUF` / `qwen3-14b-q4_k_m.gguf` | `qwen/Qwen3-14B-GGUF` / 同名 | 2025 新系列，官方+魔搭 |
| Qwen2.5 32B Instruct | 32B | Q4_K_M | `Qwen/Qwen2.5-32B-Instruct-GGUF` / `qwen2.5-32b-instruct-q4_k_m.gguf` | `qwen/Qwen2.5-32B-Instruct-GGUF` / 同名 | 官方+魔搭；可能分片 |
| QwQ-32B（推理） | 32B | Q4_K_M | `Qwen/QwQ-32B-GGUF` / `qwq-32b-q4_k_m.gguf` | `qwen/QwQ-32B-GGUF` / 同名 | 推理增强；可能分片 |
| DeepSeek-R1 Distill Qwen 32B | 32B | Q4_K_M | `unsloth/DeepSeek-R1-Distill-Qwen-32B-GGUF` / `DeepSeek-R1-Distill-Qwen-32B-Q4_K_M.gguf` | — | 魔搭暂无；**支持 F16**；可能分片 |
| Llama 3.3 70B Instruct | 70B | Q4_K_M | `unsloth/Llama-3.3-70B-Instruct-GGUF` / `Llama-3.3-70B-Instruct-Q4_K_M.gguf` | — | 2024 末；**支持 F16** |
| Llama 3.1 70B Instruct | 70B | Q4_K_M | `unsloth/Llama-3.1-70B-Instruct-GGUF` / `Llama-3.1-70B-Instruct-Q4_K_M.gguf` | — | 70B 级，无 F16 |
| GPT-OSS 120B（OpenAI 开放权重） | 117B（5.1B 激活） | Q4_K_M | `unsloth/gpt-oss-120b-GGUF` / `gpt-oss-120b-Q4_K_M.gguf` | — | Apache-2.0；**支持 F16**；超大，需多卡 |
| MiniMax-M2.7 | 229B | Q4_K_M | `unsloth/MiniMax-M2.7-GGUF` / `MiniMax-M2.7-Q4_K_M.gguf` | — | 超大模型(229B)；**支持 F16**；需极大显存 |
| Kimi-K2-Instruct（MoonshotAI） | 1T（32 专家） | Q4_K_M | `bartowski/moonshotai_Kimi-K2-Instruct-0905-GGUF` / `moonshotai_Kimi-K2-Instruct-0905-Q4_K_M.gguf` | — | 超大 MoE(1T)；无 F16；需极大显存 |
| Kimi-K2-Thinking（MoonshotAI） | 1T（32 专家） | Q4_K_M | `bartowski/moonshotai_Kimi-K2-Thinking-GGUF` / `moonshotai_Kimi-K2-Thinking-Q4_K_M.gguf` | — | 超大 MoE(1T) 推理版；无 F16；需极大显存 |

## 三、其它可补充的知名开源 LLM（未纳入默认清单）

- **Llama 4（Scout / Maverick）**：`unsloth/Llama-4-Scout-17B-16E-Instruct-GGUF`（109B MoE）、
  `unsloth/Llama-4-Maverick-17B-128E-Instruct-GGUF`（400B MoE）。均为超大 MoE，URL 较新未逐项核实，暂未收录。
- **GLM 系列**：智谱 `zai-org/GLM-4-9B-0414`、GLM-4.5 等（魔搭 `ZhipuAI` 组织有镜像），可补充。
- **DeepSeek 原版**：`unsloth/DeepSeek-V3-GGUF`（671B MoE，巨大，需分片+多卡）。
- **Qwen3 更大尺寸 / Qwen3-Coder / QwQ 更大**：可按需补充到 catalog。
- **MiniMax-M3**：`unsloth/MiniMax-M3-GGUF`（426B，更大），当前仅收录 M2.7。
- **GPT-OSS-safeguard-20B**：`unsloth/gpt-oss-safeguard-20b-GGUF`（对齐安全版），按需补充。

## 四、扩展方式

1. 后端：`backend/app/bricks/ollama/catalog.py` 的 `_MODELS` 追加字典条目（`key/name/params/approx_q4/hf_repo/hf_tpl/qcase/ms_id/ms_tpl/quants`）即可，向导自动读取。
2. 精度切换：`quants` 为支持该模型的精度 key 列表（子集）；F16 需额外给 `f16_file` 显式文件名。
3. 量化切换：将文件名中的 `q4_k_m` / `Q4_K_M` 替换为 `q8_0` / `Q5_K_M` 等即可下其它精度（已由 `QUANT_RATIO` 估算体积）。
4. 魔搭补全：找到对应模型的魔搭仓库与文件名后，把 `ms_id` / `ms_tpl` 填上，前端自动启用「魔搭社区」按钮。

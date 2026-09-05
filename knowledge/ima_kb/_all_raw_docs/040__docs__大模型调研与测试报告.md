# 大模型调研与测试报告

> 📅 **时间线**
> - 2026-07-23：开源 LLM 大模型检索（HF 镜像 + 魔搭）
> - 2026-08-10：DeepSeek V4 Pro 全流程 + 腾讯 MaaS 批量测试
> - 注：完整模型目录见 模型目录数据.json（保留原始数据）。

## 大模型调研记录（HF 镜像 + 魔搭）

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

---


## DeepSeek V4 Pro 全流程性能测试

测试时间：2026-08-10 08:08 | 模型：deepseek-v4-pro | 端点：tokenhub.tencentmaas.com 测试环境：P.A.L.M 项目主 .venv (Python 3.13) | openai SDK

## 测试概览
10/10

测试通过率

1.696s

预热平均延迟

3.97s

流式首字延迟(TTFT)

9.54s

非流式中位数延迟

57.5

非流式吞吐(tokens/s)

46.8

流式吞吐(tokens/s)

## 预热阶段（模拟真实使用前预加载）
连续发送 3 次 max_tokens=10 的极简请求，模拟实际使用前的连接预热：

| 轮次             | 延迟   | 状态         |
| ---------------- | ------ | ------------ |
| 预热 1（冷启动） | 2.555s | 首次建连较慢 |
| 预热 2           | 1.268s | 正常         |
| 预热 3           | 1.264s | 正常         |

冷启动首请求 2.555s，后续稳定在 1.26s 左右。建议实际使用前做 1 次预热请求。

## 非流式调用测试

| 用例                 | 总延迟  | 输入tokens | 输出tokens | 吞吐(tok/s) | 输出字数 | 完成 |
| -------------------- | ------- | ---------- | ---------- | ----------- | -------- | ---- |
| 短文本-问候          | 7.004s  | 9          | 369        | 52.7        | 443      | stop |
| 短文本-知识问答      | 4.307s  | 11         | 197        | 45.7        | 45       | stop |
| 中等问题-代码解释    | 9.656s  | 17         | 598        | 61.9        | 1226     | stop |
| 长文本-架构设计      | 62.078s | 25         | 3584       | 57.7        | 3827     | stop |
| 中英混合-RAG vs 微调 | 16.441s | 29         | 1171       | 71.2        | 2081     | stop |
| 多轮对话-上下文保持  | 9.415s  | 82         | 524        | 55.7        | 656      | stop |

18.15s

平均总延迟

9.54s

中位数延迟

57.5

平均吞吐(tokens/s)

76.4

平均吞吐(字/s)

延迟与输出长度强相关：短文本(45字)4.3s，长文本(3827字)62s。吞吐稳定在 45-71 tokens/s，说明模型推理速度恒定，延迟差异主要由输出量决定。

### 非流式延迟分布
4.3s知识问答

7.0s问候

9.4s多轮对话

9.7s代码解释

16.4s中英混合

62.1s架构设计

## 流式调用测试（首字延迟 TTFT）

| 用例              | 首字延迟(TTFT) | 总延迟  | 流式输出时间 | 输出tokens | 吞吐(tok/s) | 字/s  |
| ----------------- | -------------- | ------- | ------------ | ---------- | ----------- | ----- |
| 短文本-问候       | 2.761s         | 6.751s  | 3.990s       | 362        | 53.6        | 69.6  |
| 短文本-知识问答   | 1.620s         | 2.117s  | 0.497s       | 36         | 17.0        | 18.9  |
| 中等问题-代码解释 | 2.619s         | 11.224s | 8.605s       | 682        | 60.8        | 115.6 |
| 长文本-架构设计   | 8.861s         | 40.521s | 31.660s      | 2261       | 55.8        | 83.3  |

3.97s

平均TTFT

2.69s

中位数TTFT

15.15s

平均总延迟

46.8

平均吞吐(tokens/s)

TTFT 波动较大：最短 1.62s（知识问答），最长 8.86s（架构设计）。长文本 prompt 的 TTFT 明显更高，推测与 prompt 处理时间有关。短文本 TTFT 约 1.6-2.8s，可满足语音交互的"提示音频"填补需求。

### 流式首字延迟(TTFT)分布
1.62s知识问答

2.62s代码解释

2.76s问候

8.86s架构设计

## 质量评估

### 短文本-知识问答（"什么是递归？用一句话解释。"）
准确 简洁 遵循指令

递归是一种函数直接或间接调用自身的编程技巧，常用于将复杂问题分解为结构相同的子问题来求解。

评价：一句话解释，准确无冗余。197 tokens 中大部分可能是 reasoning tokens（输出仅 45 字），推测模型内部做了思维链推理。

### 中等问题-代码解释（"Python装饰器原理+示例"）
代码正确 结构化 原理清晰

装饰器（Decorator）是 Python 中一种强大的语法，用于在不修改原函数代码的情况下，给函数增加额外的功能。它的核心原理基于 Python 的 **函数是一等对象**（可以赋值给变量、作为参数传递、作为返回值）以及 **闭包**（内层函数引用外层函数的变量）。 ### 原理简述 1. 装饰器本质上是一个 **可调用对象**（通常是函数），它接收一个函数作为参数，并返回一个新的函数。 2. 使用 `@decorator_name` 语法时，Python 解释器会把被装饰的函数自动传递给装饰器，并将返回值重新绑定到原函数名上。 3. 装饰器内部通常会定义一个包装函数（wrapper），在调用原函数的前后可以插入额外的逻辑，然后返回这个包装函数。 4. 为了保留原函数的元数据（如 `__name__`、`__doc__`），通常使用 `functools.wraps` 装饰包装函数。 ### 简单示例：一个计时装饰器 ```python import time from functools import wraps def timer(func): """装饰器：打印函数执行时间""" @wraps(func) def wrapper(*args, **kwargs): start = time.time() result = func(*args, **kwargs) end = time.time() print(f"{func.__name__} 执行耗时: {end - start:.4f}s") return result return wrapper @timer def slow_function(): time.sleep(1) print("任务完成") slow_function() # 输出: # 任务完成 # slow_function 执行耗时: 1.0012s ``` ...

评价：原理分点说明 + 可运行代码示例 + functools.wraps 最佳实践。结构清晰，适合教学。

### 多轮对话-上下文保持
上下文正确 代码正确 解释详细

列表 `[3, 1, 4, 1, 5, 9, 2, 6]` 排序后结果为： ```python original = [3, 1, 4, 1, 5, 9, 2, 6] sorted_list = sorted(original) print(sorted_list) # 输出: [1, 1, 2, 3, 4, 5, 6, 9] ``` **解释：** 1. **默认升序排序**：`sorted()` 默认按从小到大排列 2. **稳定排序**：两个 `1` 保持原来的相对顺序 3. **原地排序**：`list.sort()` 方法可直接修改原列表

评价：正确记住前文列表，排序结果正确，额外解释了稳定排序和原地排序概念。

### 中英混合-技术讨论
双语切换自然 结构化 技术准确

输出 2081 字，使用中文回答英文提问，RAG vs Fine-tuning 的原理/优缺点/选择依据对比清晰。结构化使用了一二级标题 + 分点 + 代码块。

## 关键发现
发现 1

吞吐稳定：非流式平均 57.5 tokens/s，流式平均 46.8 tokens/s。不同用例的吞吐波动小（45-71），说明模型推理速度恒定，延迟差异主要由输出长度决定。

发现 2

TTFT 波动大：流式首字延迟从 1.62s 到 8.86s 不等。短文本 TTFT 约 1.6-2.8s，长文本 prompt 的 TTFT 显著升高（8.86s）。推测与 prompt 处理 + reasoning 时间有关。

发现 3

reasoning tokens 存在：知识问答用例输出仅 45 字但消耗 197 tokens，说明模型内部做了思维链推理。这会增加延迟但提升质量。

发现 4

质量优秀：6 个用例全部正常完成（finish_reason=stop），代码可运行，上下文保持正确，中英混合自然，结构化输出一致。

发现 5

冷启动效应：首次请求 2.555s，后续预热请求降至 1.26s。实际使用前建议做 1 次预热请求。

## 与 P.A.L.M 语音交互链路适配分析

| 链路环节             | 预算延迟  | 实测延迟      | 状态     | 说明                                 |
| -------------------- | --------- | ------------- | -------- | ------------------------------------ |
| STT 尾字延迟         | ~200ms    | -             | 待测     | Sherpa-onnx 尚未实现                 |
| 语义识别（打断判断） | ~10ms     | -             | 待测     | FastText 尚未实现                    |
| LLM 首字延迟         | 300-500ms | 1,620-8,861ms | 超出预算 | 短文本 TTFT 1.6s 已超 0.5s 预算 3 倍 |
| TTS 首字延迟(GSV)    | ~400ms    | 490-710ms     | 符合     | 已实测验证                           |
| 音频传输             | ~100ms    | -             | 待测     | 依赖前端实现                         |

关键问题：LLM 延迟远超预算 原预算 LLM 首字延迟 300-500ms，实测 DeepSeek V4 Pro 流式 TTFT 最低 1.62s、最高 8.86s。 即使取最好情况 1.62s，加上 STT 200ms + TTS 490ms + 传输 100ms = 2.41s，远超 1.5s 目标。 提示音频机制的必要性得到验证：TTFT 1.6-8.9s 的空窗期必须有提示音频填补。 原设计的提示音长度选择逻辑（1s/3s/5s）需要调整——建议改为 3s/5s/8s 三档，因为 TTFT 普遍超过 1s。

优化建议 1. 考虑测试其他模型/端点对比 TTFT（如 DeepSeek 官方 API、Qwen 等） 2. 提示音频改为 3s/5s/8s 三档，TTFT 普遍 1.6s+ 需要 3s 档起步 3. 流式调用是必须的——非流式总延迟 4.3-62s 用户体验极差 4. 可考虑预填充策略：用户说话时就开始 LLM 请求（不等 STT 完整结果）

## 完整测试参数汇总

| 指标       | 非流式     | 流式                      | 说明                       |
| ---------- | ---------- | ------------------------- | -------------------------- |
| 测试用例数 | 6          | 4                         | 全部成功                   |
| 平均总延迟 | 18.15s     | 15.15s                    | 流式略快（无需等完整响应） |
| 中位数延迟 | 9.54s      | 8.99s                     | -                          |
| 最小延迟   | 4.31s      | 2.12s                     | 均为知识问答用例           |
| 最大延迟   | 62.08s     | 40.52s                    | 均为架构设计用例           |
| 平均TTFT   | -          | 3.97s                     | 首字延迟                   |
| 中位数TTFT | -          | 2.69s                     | -                          |
| 平均吞吐   | 57.5 tok/s | 46.8 tok/s                | 非流式略高（无流式开销）   |
| 预热平均   | 1.696s     | 冷启动 2.56s → 稳定 1.26s |                            |

报告生成：2026-08-10 | P.A.L.M 项目 | 测试脚本：test_deepseek_v4.py

---


## 腾讯 MaaS 文本对话模型批量测试

测试时间：2026-08-10 08:21 | 端点：tokenhub.tencentmaas.com 测试 Prompt：「你好，1+1等于几？请简短回答。」| max_tokens=200 | 流式调用

## 测试概览
89

平台总模型数

22

文本对话模型（待测）

13

测试成功

9

无余额/不可用

## 首字延迟排行（TTFT，越低越好）
流式调用从发送请求到收到第一个 token 的延迟。对语音交互链路最关键的指标。

0.73s

1.39s

1.50s

1.67s

1.72s

1.87s

2.27s

2.64s

4.51s

6.18s

7.19s

minimax-m3 以 0.73s TTFT 遥遥领先，是唯一进入 sub-1s 的模型。但注意它输出了 <think> 标签，是推理模型。非推理模型中 deepseek-v4-flash（1.50s）和 minimax-m2.5/m2.7（1.67-1.72s）表现最佳。

## 详细测试数据

| 模型              | 类型     | TTFT(s) | 总延迟(s) | 输出tokens | 吞吐(tok/s) | 回答         | 状态 |
| ----------------- | -------- | ------- | --------- | ---------- | ----------- | ------------ | ---- |
| minimax-m3        | 推理     | 0.728   | 0.980     | 40         | 40.8        | <think>...2  | 成功 |
| deepseek-v4-flash | 非推理   | 1.495   | 1.512     | 40         | 26.5        | 2            | 成功 |
| kimi-k2.7-code    | 非推理   | 1.392   | 1.437     | 38         | 26.4        | 2            | 成功 |
| minimax-m2.5      | 非推理   | 1.671   | 1.687     | 101        | 59.9        | 2            | 成功 |
| minimax-m2.7      | 非推理   | 1.720   | 1.740     | 70         | 40.2        | 2            | 成功 |
| mimo-v2.5-pro     | 非推理   | 1.872   | 2.026     | 32         | 15.8        | 1+1等于 2    | 成功 |
| glm-5v-turbo      | 疑似推理 | 2.265   | 2.283     | 191        | 83.6        | 2            | 成功 |
| glm-5-turbo       | 疑似推理 | 2.636   | 2.644     | 127        | 48.0        | 2            | 成功 |
| kimi-k2.5         | 疑似推理 | 4.513   | 4.546     | 123        | 27.1        | 2            | 成功 |
| qwen3.5-flash     | 推理     | 6.183   | 6.187     | 651        | 105.2       | 2            | 成功 |
| qwen3.5-plus      | 推理     | 7.194   | 7.320     | 375        | 51.2        | 1+1 等于 2   | 成功 |
| glm-5             | 疑似推理 | N/A     | 5.328     | 200        | 37.5        | （内容为空） | 成功 |
| kimi-k2.6         | 疑似推理 | N/A     | 1.336     | 200        | 149.7       | （内容为空） | 成功 |

类型判定依据：输出 <think> 标签=推理模型；简单问题消耗 100+ tokens=疑似推理（可能含隐藏思维链）；40 tokens 以下直接回答=非推理。glm-5 和 kimi-k2.6 内容为空但消耗 200 tokens（max_tokens 上限），推测输出全是 reasoning tokens。

## 吞吐排行（tokens/s，越高越好）
149.7

105.2

83.6

59.9

51.2

48.0

40.8

40.2

37.5

27.1

26.5

26.4

15.8

## 失败模型（无免费额度）

| 模型                     | 错误                   |
| ------------------------ | ---------------------- |
| hy3                      | 402 - 免费额度已用完   |
| hy3-preview              | 402 - 免费额度已用完   |
| deepseek-v4-flash-202605 | 402 - 免费额度已用完   |
| kimi-k3                  | 402 - 免费额度已用完   |
| kimi-k2.7-code-highspeed | 402 - 免费额度已用完   |
| glm-5.2                  | 402 - 免费额度已用完   |
| deepseek-v4-pro-202606   | 402 - 免费额度已用完   |
| glm-5.1                  | 402 - 免费额度已用完   |
| deepseek-v3.2            | 400 - 模型或服务不可用 |

## 与 DeepSeek V4 Pro 对比

| 模型              | 类型     | TTFT(s)   | 总延迟(s) | 吞吐(tok/s) | 语音链路适配 |
| ----------------- | -------- | --------- | --------- | ----------- | ------------ |
| deepseek-v4-pro   | 推理     | 1.62-8.86 | 2.12-40.5 | 46.8        | 不达标       |
| minimax-m3        | 推理     | 0.73      | 0.98      | 40.8        | TTFT 最佳    |
| deepseek-v4-flash | 非推理   | 1.50      | 1.51      | 26.5        | 非推理首选   |
| minimax-m2.5      | 非推理   | 1.67      | 1.69      | 59.9        | 综合最佳     |
| minimax-m2.7      | 非推理   | 1.72      | 1.74      | 40.2        | 综合优秀     |
| kimi-k2.6         | 疑似推理 | N/A       | 1.34      | 149.7       | 吞吐最高     |

## 语音交互链路延迟预算重算
基于本次实测数据，用 TTFT 最低的非推理模型重新计算端到端延迟：

| 方案                        | STT(ms) | LLM TTFT(ms) | TTS(ms) | 传输(ms) | 总计(ms) | 目标 1.5s |
| --------------------------- | ------- | ------------ | ------- | -------- | -------- | --------- |
| 原方案 deepseek-v4-pro      | 200     | 1,620        | 490     | 100      | 2,410    | 超 61%    |
| minimax-m3（推理）          | 200     | 728          | 490     | 100      | 1,518    | 刚好达标  |
| deepseek-v4-flash（非推理） | 200     | 1,495        | 490     | 100      | 2,285    | 超 52%    |
| minimax-m2.5（非推理）      | 200     | 1,671        | 490     | 100      | 2,461    | 超 64%    |

结论：即使 TTFT 最低的模型也无法在无提示音情况下达到 1.5s 目标 最好的 minimax-m3（728ms TTFT）刚好压线 1.5s（1,518ms），但它输出 <think> 标签是推理模型，实际对话场景 TTFT 会更高。 提示音频机制是刚需——不是"锦上添花"而是"没有就不可用"。

推荐方案 日常对话：minimax-m2.5（TTFT 1.67s，吞吐 59.9 tok/s，非推理）+ 3s 提示音 低延迟优先：minimax-m3（TTFT 0.73s，推理模型）+ 短提示音 质量优先：deepseek-v4-flash（TTFT 1.50s，DeepSeek 血统）+ 3s 提示音 吞吐优先：kimi-k2.6（149.7 tok/s，疑似推理）+ 动态提示音 提示音档位建议调整为 2s/4s/6s 三档（基于实测 TTFT 分布）。

## 关键发现

| # | 发现                                                                                  | 影响               |
| - | ------------------------------------------------------------------------------------- | ------------------ |
| 1 | minimax-m3 是唯一 sub-1s TTFT 的模型（0.73s），但它是推理模型（输出 <think> 标签）    | 推理模型延迟波动大 |
| 2 | 非推理模型中 deepseek-v4-flash / minimax-m2.5 / minimax-m2.7 的 TTFT 在 1.5-1.7s 区间 | 可用但需提示音     |
| 3 | qwen3.5-flash/plus 的 TTFT 高达 6-7s，简单问题消耗 375-651 tokens，重度推理模型       | 不适合实时语音     |
| 4 | 9/22 模型无免费额度（402），包括 hy3、kimi-k3、glm-5.2 等新模型                       | 可选范围缩小       |
| 5 | kimi-k2.6 吞吐 149.7 tok/s 遥遥领先，但输出内容为空（200 tokens 全是 reasoning）      | 需进一步测试       |
| 6 | 即使最好的模型，无提示音也达不到 1.5s 端到端目标                                      | 提示音从可选变刚需 |

报告生成：2026-08-10 | P.A.L.M 项目 | 测试脚本：batch_test_models.py

---

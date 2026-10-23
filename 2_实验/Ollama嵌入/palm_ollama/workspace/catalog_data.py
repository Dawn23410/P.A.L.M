"""Ollama 模型目录原始数据（与 build_catalog/resolve_model 逻辑分离）。

纯数据字典，字段含义见 catalog.py 顶部文档；不含任何逻辑，仅被 catalog.py 导入。
下载管理器为通用实现，任何可达 URL 均可下载。
"""
from __future__ import annotations

_GB = 1024 * 1024 * 1024

# 标准精度子集（无全精度），多数仓库使用。
STD_QUANTS = ["Q2_K", "Q3_K_M", "Q4_0", "Q4_K_M", "Q5_K_M", "Q6_K", "Q8_0"]
# 含全精度 F16 的仓库（unsloth / bartowski-*1m 等），F16 文件名由 f16_file 显式给出。
FULL_QUANTS = ["F16"] + STD_QUANTS

# GLM-Edge-V 多模态系列的量化（不含 F16 外的 K-quants 变体）。
GLM_EDGE_V_QUANTS = ["Q4_0", "Q4_K_M", "Q5_0", "Q5_K_M", "Q8_0"]

# CodeGeeX4-ALL-9B 特殊量化（含低比特 IQ 量化，非标准 K-quants 子集）。
CODEGEEX4_QUANTS = ["Q4_K_M", "Q5_K_M", "Q6_K_L", "Q8_0", "IQ2_M", "IQ3_M"]

# MiniMax-M2.7 等使用 unsloth Dynamic 2.0 量化（UD-*），非标准 K-quants；
# 全精度实为 BF16（非 F16），且仓库按子文件夹/分片存放，需 huggingface-cli 拉取。
DYNAMIC_QUANTS = [
    "UD-IQ1_M", "UD-IQ2_XXS", "UD-IQ2_XS", "UD-IQ2_M", "UD-IQ2_L",
    "UD-IQ3_XXS", "UD-IQ3_XS", "UD-IQ3_M",
    "UD-Q2_K", "UD-Q3_K_M", "UD-Q4_K_M", "UD-Q5_K_M", "UD-Q6_K", "UD-Q8_0",
]

_MODELS = [
    # ---------- DeepSeek（unsloth，含 F16 全精度）----------
    {
        "key": "deepseek-r1-1.5b", "name": "DeepSeek-R1 Distill Qwen 1.5B", "params": "1.5B",
        "approx_q4": int(1.1 * _GB),
        "hf_repo": "unsloth/DeepSeek-R1-Distill-Qwen-1.5B-GGUF",
        "hf_tpl": "DeepSeek-R1-Distill-Qwen-1.5B-{q}.gguf", "qcase": "upper",
        "ms_id": "", "ms_tpl": "",
        "quants": FULL_QUANTS, "f16_file": "DeepSeek-R1-Distill-Qwen-1.5B-F16.gguf",
    },
    {
        "key": "deepseek-r1-7b", "name": "DeepSeek-R1 Distill Qwen 7B", "params": "7B",
        "approx_q4": int(4.7 * _GB),
        "hf_repo": "unsloth/DeepSeek-R1-Distill-Qwen-7B-GGUF",
        "hf_tpl": "DeepSeek-R1-Distill-Qwen-7B-{q}.gguf", "qcase": "upper",
        "ms_id": "", "ms_tpl": "",
        "quants": FULL_QUANTS, "f16_file": "DeepSeek-R1-Distill-Qwen-7B-F16.gguf",
    },
    {
        "key": "deepseek-r1-8b", "name": "DeepSeek-R1 Distill Llama 8B", "params": "8B",
        "approx_q4": int(4.9 * _GB),
        "hf_repo": "unsloth/DeepSeek-R1-Distill-Llama-8B-GGUF",
        "hf_tpl": "DeepSeek-R1-Distill-Llama-8B-{q}.gguf", "qcase": "upper",
        "ms_id": "", "ms_tpl": "",
        "quants": FULL_QUANTS, "f16_file": "DeepSeek-R1-Distill-Llama-8B-F16.gguf",
    },
    {
        "key": "deepseek-r1-14b", "name": "DeepSeek-R1 Distill Qwen 14B", "params": "14B",
        "approx_q4": int(9.0 * _GB),
        "hf_repo": "unsloth/DeepSeek-R1-Distill-Qwen-14B-GGUF",
        "hf_tpl": "DeepSeek-R1-Distill-Qwen-14B-{q}.gguf", "qcase": "upper",
        "ms_id": "", "ms_tpl": "",
        "quants": FULL_QUANTS, "f16_file": "DeepSeek-R1-Distill-Qwen-14B-F16.gguf",
    },
    {
        "key": "deepseek-r1-32b", "name": "DeepSeek-R1 Distill Qwen 32B", "params": "32B",
        "approx_q4": int(20.0 * _GB),
        "hf_repo": "unsloth/DeepSeek-R1-Distill-Qwen-32B-GGUF",
        "hf_tpl": "DeepSeek-R1-Distill-Qwen-32B-{q}.gguf", "qcase": "upper",
        "ms_id": "", "ms_tpl": "",
        "quants": FULL_QUANTS, "f16_file": "DeepSeek-R1-Distill-Qwen-32B-F16.gguf",
    },

    # ---------- Qwen（官方仓库，魔搭可用，标准精度）----------
    {
        "key": "qwen2.5-0.5b", "name": "Qwen2.5 0.5B Instruct", "params": "0.5B",
        "approx_q4": int(0.4 * _GB),
        "hf_repo": "Qwen/Qwen2.5-0.5B-Instruct-GGUF",
        "hf_tpl": "qwen2.5-0.5b-instruct-{q}.gguf", "qcase": "lower",
        "ms_id": "qwen/Qwen2.5-0.5B-Instruct-GGUF", "ms_tpl": "qwen2.5-0.5b-instruct-{q}.gguf",
        "quants": STD_QUANTS,
    },
    {
        "key": "qwen2.5-1.5b", "name": "Qwen2.5 1.5B Instruct", "params": "1.5B",
        "approx_q4": int(1.1 * _GB),
        "hf_repo": "Qwen/Qwen2.5-1.5B-Instruct-GGUF",
        "hf_tpl": "qwen2.5-1.5b-instruct-{q}.gguf", "qcase": "lower",
        "ms_id": "qwen/Qwen2.5-1.5B-Instruct-GGUF", "ms_tpl": "qwen2.5-1.5b-instruct-{q}.gguf",
        "quants": STD_QUANTS,
    },
    {
        "key": "qwen2.5-3b", "name": "Qwen2.5 3B Instruct", "params": "3B",
        "approx_q4": int(2.0 * _GB),
        "hf_repo": "Qwen/Qwen2.5-3B-Instruct-GGUF",
        "hf_tpl": "qwen2.5-3b-instruct-{q}.gguf", "qcase": "lower",
        "ms_id": "qwen/Qwen2.5-3B-Instruct-GGUF", "ms_tpl": "qwen2.5-3b-instruct-{q}.gguf",
        "quants": STD_QUANTS,
    },
    {
        "key": "qwen2.5-7b", "name": "Qwen2.5 7B Instruct", "params": "7B",
        "approx_q4": int(4.7 * _GB),
        # HF 上这些量化被切成多片（无单文件），故仅保留魔搭单文件来源（已验证 OK）。
        "hf_repo": "", "hf_tpl": "",
        "ms_id": "qwen/Qwen2.5-7B-Instruct-GGUF", "ms_tpl": "qwen2.5-7b-instruct-{q}.gguf", "qcase": "lower",
        "quants": STD_QUANTS,
    },
    {
        "key": "qwen2.5-14b", "name": "Qwen2.5 14B Instruct", "params": "14B",
        "approx_q4": int(9.0 * _GB),
        # HF 上这些量化被切成多片（无单文件），故仅保留魔搭单文件来源（已验证 OK）。
        "hf_repo": "", "hf_tpl": "",
        "ms_id": "qwen/Qwen2.5-14B-Instruct-GGUF", "ms_tpl": "qwen2.5-14b-instruct-{q}.gguf", "qcase": "lower",
        "quants": STD_QUANTS,
    },
    {
        "key": "qwen2.5-32b", "name": "Qwen2.5 32B Instruct", "params": "32B",
        "approx_q4": int(19.0 * _GB),
        # HF 上这些量化被切成多片（无单文件），故仅保留魔搭单文件来源（已验证 OK）。
        "hf_repo": "", "hf_tpl": "",
        "ms_id": "qwen/Qwen2.5-32B-Instruct-GGUF", "ms_tpl": "qwen2.5-32b-instruct-{q}.gguf", "qcase": "lower",
        "quants": STD_QUANTS,
    },
    {
        "key": "qwen2.5-coder-7b", "name": "Qwen2.5-Coder 7B Instruct", "params": "7B",
        "approx_q4": int(4.7 * _GB),
        "hf_repo": "Qwen/Qwen2.5-Coder-7B-Instruct-GGUF",
        "hf_tpl": "qwen2.5-coder-7b-instruct-{q}.gguf", "qcase": "lower",
        "ms_id": "qwen/Qwen2.5-Coder-7B-Instruct-GGUF", "ms_tpl": "qwen2.5-coder-7b-instruct-{q}.gguf",
        "quants": STD_QUANTS,
    },
    {
        "key": "qwen2.5-coder-14b", "name": "Qwen2.5-Coder 14B Instruct", "params": "14B",
        "approx_q4": int(9.0 * _GB),
        "hf_repo": "Qwen/Qwen2.5-Coder-14B-Instruct-GGUF",
        "hf_tpl": "qwen2.5-coder-14b-instruct-{q}.gguf", "qcase": "lower",
        "ms_id": "qwen/Qwen2.5-Coder-14B-Instruct-GGUF", "ms_tpl": "qwen2.5-coder-14b-instruct-{q}.gguf",
        "quants": STD_QUANTS,
    },
    {
        "key": "qwen3-0.6b", "name": "Qwen3 0.6B Instruct", "params": "0.6B",
        "approx_q4": int(0.5 * _GB),
        "hf_repo": "Qwen/Qwen3-0.6B-GGUF",
        "hf_tpl": "Qwen3-0.6B-{q}.gguf", "qcase": "upper",
        "ms_id": "qwen/Qwen3-0.6B-GGUF",         "ms_tpl": "Qwen3-0.6B-{q}.gguf",
        "quants": ["Q8_0"],
        # Qwen3 原生上下文上限为 32K（选更大值部署会被 Ollama 拒绝）。
        "max_ctx": 32768,
    },
    {
        "key": "qwen3-4b", "name": "Qwen3 4B Instruct", "params": "4B",
        "approx_q4": int(2.5 * _GB),
        "hf_repo": "Qwen/Qwen3-4B-GGUF",
        "hf_tpl": "Qwen3-4B-{q}.gguf", "qcase": "upper",
        "ms_id": "qwen/Qwen3-4B-GGUF",         "ms_tpl": "Qwen3-4B-{q}.gguf",
        "quants": ["Q4_K_M", "Q5_0", "Q5_K_M", "Q6_K", "Q8_0"],
        # Qwen3 原生上下文上限为 32K（选更大值部署会被 Ollama 拒绝）。
        "max_ctx": 32768,
    },
    {
        "key": "qwen3-8b", "name": "Qwen3 8B Instruct", "params": "8B",
        "approx_q4": int(5.0 * _GB),
        "hf_repo": "Qwen/Qwen3-8B-GGUF",
        "hf_tpl": "Qwen3-8B-{q}.gguf", "qcase": "upper",
        "ms_id": "qwen/Qwen3-8B-GGUF",         "ms_tpl": "Qwen3-8B-{q}.gguf",
        "quants": ["Q4_K_M", "Q5_0", "Q5_K_M", "Q6_K", "Q8_0"],
        # Qwen3 原生上下文上限为 32K（选更大值部署会被 Ollama 拒绝）。
        "max_ctx": 32768,
    },
    {
        "key": "qwen3-14b", "name": "Qwen3 14B Instruct", "params": "14B",
        "approx_q4": int(9.0 * _GB),
        "hf_repo": "Qwen/Qwen3-14B-GGUF",
        "hf_tpl": "Qwen3-14B-{q}.gguf", "qcase": "upper",
        "ms_id": "qwen/Qwen3-14B-GGUF",         "ms_tpl": "Qwen3-14B-{q}.gguf",
        "quants": ["Q4_K_M", "Q5_0", "Q5_K_M", "Q6_K", "Q8_0"],
        # Qwen3 原生上下文上限为 32K（选更大值部署会被 Ollama 拒绝）。
        "max_ctx": 32768,
    },
    {
        "key": "qwq-32b", "name": "QwQ-32B（推理）", "params": "32B",
        "approx_q4": int(20.0 * _GB),
        "hf_repo": "Qwen/QwQ-32B-GGUF",
        "hf_tpl": "qwq-32b-{q}.gguf", "qcase": "lower",
        "ms_id": "qwen/QwQ-32B-GGUF", "ms_tpl": "qwq-32b-{q}.gguf",
        "quants": STD_QUANTS,
    },

    # ---------- GLM（bartowski）----------
    {
        "key": "glm-4-9b-chat", "name": "GLM-4 9B Chat", "params": "9B",
        "approx_q4": int(6.25 * _GB),
        "hf_repo": "bartowski/glm-4-9b-chat-GGUF",
        "hf_tpl": "glm-4-9b-chat-{q}.gguf", "qcase": "upper",
        "ms_id": "", "ms_tpl": "",
        "quants": STD_QUANTS,
    },
    {
        "key": "glm-4-9b-chat-1m", "name": "GLM-4 9B Chat 1M（长上下文）", "params": "9B",
        "approx_q4": int(6.3 * _GB),
        # GLM-4-9B-Chat-1M 原生支持 1M 上下文。
        "max_ctx": 1048576,
        "hf_repo": "bartowski/glm-4-9b-chat-1m-GGUF",
        "hf_tpl": "glm-4-9b-chat-1m-{q}.gguf", "qcase": "upper",
        "ms_id": "", "ms_tpl": "",
        "quants": FULL_QUANTS, "f16_file": "glm-4-9b-chat-1m-f16.gguf",
        # tag 用于同参数量（9B）下与「普通版」区分，避免误认为同一模型两种尺寸。
        "tag": "1M 长上下文",
    },

    # ---------- ZhipuAI GLM-Edge 系列（智谱，边缘设备小模型，魔搭官方 GGUF）----------
    {
        "key": "glm-edge-1.5b-chat", "name": "GLM-Edge 1.5B Chat（边缘）", "params": "1.5B",
        "approx_q4": int(1.0 * _GB),
        "hf_repo": "", "hf_tpl": "",
        "ms_id": "ZhipuAI/glm-edge-1.5b-chat-gguf",
        "ms_tpl": "ggml-model-Q{q}.gguf", "qcase": "upper",
        "quants": ["Q4_K_S", "Q5_K_S", "Q8_0"],
    },
    {
        "key": "glm-edge-4b-chat", "name": "GLM-Edge 4B Chat（边缘）", "params": "4B",
        "approx_q4": int(3.5 * _GB),
        "hf_repo": "", "hf_tpl": "",
        "ms_id": "ZhipuAI/glm-edge-4b-chat-gguf",
        "ms_tpl": "ggml-model-Q{q}.gguf", "qcase": "upper",
        "quants": STD_QUANTS,
    },
    {
        "key": "glm-edge-v-2b", "name": "GLM-Edge-V 2B（多模态，智谱边缘视觉）", "params": "2B",
        "approx_q4": int(1.0 * _GB),
        "hf_repo": "", "hf_tpl": "",
        "ms_id": "ZhipuAI/glm-edge-v-2b-gguf",
        "ms_tpl": "ggml-model-Q{q}.gguf", "qcase": "upper",
        "quants": GLM_EDGE_V_QUANTS,
    },
    {
        "key": "glm-edge-v-5b", "name": "GLM-Edge-V 5B（多模态，智谱边缘视觉）", "params": "5B",
        "approx_q4": int(3.0 * _GB),
        "hf_repo": "", "hf_tpl": "",
        "ms_id": "ZhipuAI/glm-edge-v-5b-gguf",
        "ms_tpl": "ggml-model-Q{q}.gguf", "qcase": "upper",
        "quants": GLM_EDGE_V_QUANTS,
    },

    # ---------- CodeGeeX4（智谱，代码生成，官方 GGUF）----------
    {
        "key": "codegeex4-all-9b", "name": "CodeGeeX4-ALL 9B（代码）", "params": "9B",
        "approx_q4": int(6.25 * _GB),
        "hf_repo": "THUDM/codegeex4-all-9b-GGUF",
        "hf_tpl": "codegeex4-all-9b-{q}.gguf", "qcase": "upper",
        "ms_id": "ZhipuAI/codegeex4-all-9b-GGUF",
        "ms_tpl": "codegeex4-all-9b-{q}.gguf", "qcase": "upper",
        "quants": CODEGEEX4_QUANTS,
    },

    # ---------- Tencent-Hunyuan Hy-MT2（腾讯混元，多语言翻译，官方 GGUF）----------
    {
        "key": "hy-mt2-1.8b", "name": "Hy-MT2 1.8B（翻译，腾讯混元）", "params": "1.8B",
        "approx_q4": int(1.05 * _GB),
        "hf_repo": "", "hf_tpl": "",
        "ms_id": "Tencent-Hunyuan/Hy-MT2-1.8B-GGUF",
        "ms_tpl": "Hy-MT2-1.8B-{q}.gguf", "qcase": "upper",
        "quants": STD_QUANTS,
    },
    {
        "key": "hy-mt2-7b", "name": "Hy-MT2 7B（翻译，腾讯混元）", "params": "7B",
        "approx_q4": int(5.5 * _GB),
        "hf_repo": "", "hf_tpl": "",
        "ms_id": "Tencent-Hunyuan/Hy-MT2-7B-GGUF",
        "ms_tpl": "Hy-MT2-7B-{q}.gguf", "qcase": "upper",
        "quants": STD_QUANTS,
    },

    # ---------- MiniMax（unsloth，含 F16 全精度，超大模型）----------
    {
        "key": "minimax-m2.7", "name": "MiniMax-M2.7", "params": "229B",
        "approx_q4": int(140.0 * _GB),
        # MiniMax-M2.7 原生支持 1M 上下文。
        "max_ctx": 1048576,
        "hf_repo": "unsloth/MiniMax-M2.7-GGUF",
        "hf_tpl": "MiniMax-M2.7-{q}.gguf", "qcase": "upper",
        "ms_id": "", "ms_tpl": "",
        # unsloth 仅提供 Dynamic 2.0 量化（UD-*），全精度为 BF16（非 F16）且需 cli 拉取分片。
        "quants": DYNAMIC_QUANTS + ["BF16"],
        "large": True,
    },

    # ---------- GPT（OpenAI 开放权重，unsloth，含 F16 全精度）----------
    {
        "key": "gpt-oss-20b", "name": "GPT-OSS 20B（OpenAI 开放权重）", "params": "21B（3.6B 激活）",
        "approx_q4": int(11.6 * _GB),
        "hf_repo": "unsloth/gpt-oss-20b-GGUF",
        "hf_tpl": "gpt-oss-20b-{q}.gguf", "qcase": "upper",
        "ms_id": "unsloth/gpt-oss-20b-GGUF", "ms_tpl": "gpt-oss-20b-{q}.gguf",
        "quants": FULL_QUANTS, "f16_file": "gpt-oss-20b-F16.gguf",
    },
    {
        "key": "gpt-oss-120b", "name": "GPT-OSS 120B（OpenAI 开放权重）", "params": "117B（5.1B 激活）",
        "approx_q4": int(62.8 * _GB),
        "hf_repo": "unsloth/gpt-oss-120b-GGUF",
        "hf_tpl": "gpt-oss-120b-{q}.gguf", "qcase": "upper",
        "ms_id": "", "ms_tpl": "",
        # K-quants 分片在子文件夹，仅 F16 为单文件（已验证）；K-quants 需 huggingface-cli 拉取。
        "quants": ["F16"], "f16_file": "gpt-oss-120b-F16.gguf",
        "large": True,
    },

    # ---------- Kimi（MoonshotAI，bartowski，超大 MoE，无 F16）----------
    {
        "key": "kimi-k2-instruct", "name": "Kimi-K2-Instruct（MoonshotAI，1T MoE）", "params": "1T（32 专家）",
        "approx_q4": int(624.0 * _GB),
        # HF 量化分片在子文件夹（无单文件），魔搭无镜像；需 huggingface-cli 拉取后合并。
        "hf_repo": "", "hf_tpl": "", "qcase": "upper",
        "ms_id": "", "ms_tpl": "",
        "quants": STD_QUANTS,
        "large": True,
        # tag 用于同参数量（1T）下与「推理版」区分。
        "tag": "通用",
    },
    {
        "key": "kimi-k2-thinking", "name": "Kimi-K2-Thinking（MoonshotAI，推理，1T MoE）", "params": "1T（32 专家）",
        "approx_q4": int(624.0 * _GB),
        # HF 量化分片在子文件夹（无单文件），魔搭无镜像；需 huggingface-cli 拉取后合并。
        "hf_repo": "", "hf_tpl": "", "qcase": "upper",
        "ms_id": "", "ms_tpl": "",
        "quants": STD_QUANTS,
        "large": True,
        # tag 用于同参数量（1T）下与「通用版」区分。
        "tag": "推理",
    },

    # ---------- Llama 扩展（unsloth）----------
    {
        "key": "llama3.2-1b", "name": "Llama 3.2 1B Instruct", "params": "1B",
        "approx_q4": int(0.9 * _GB),
        "hf_repo": "unsloth/Llama-3.2-1B-Instruct-GGUF",
        "hf_tpl": "Llama-3.2-1B-Instruct-{q}.gguf", "qcase": "upper",
        "ms_id": "", "ms_tpl": "",
        "quants": STD_QUANTS,
    },
    {
        "key": "llama3.2-3b", "name": "Llama 3.2 3B Instruct", "params": "3B",
        "approx_q4": int(2.0 * _GB),
        "hf_repo": "unsloth/Llama-3.2-3B-Instruct-GGUF",
        "hf_tpl": "Llama-3.2-3B-Instruct-{q}.gguf", "qcase": "upper",
        "ms_id": "", "ms_tpl": "",
        "quants": STD_QUANTS,
    },
    {
        "key": "llama3.2-11b-vision", "name": "Llama 3.2 11B Vision Instruct", "params": "11B",
        "approx_q4": int(7.6 * _GB),
        "hf_repo": "unsloth/Llama-3.2-11B-Vision-Instruct-GGUF",
        "hf_tpl": "Llama-3.2-11B-Vision-Instruct-{q}.gguf", "qcase": "upper",
        "ms_id": "", "ms_tpl": "",
        "quants": STD_QUANTS,
    },
    {
        "key": "llama3.3-70b", "name": "Llama 3.3 70B Instruct", "params": "70B",
        "approx_q4": int(42.5 * _GB),
        "hf_repo": "unsloth/Llama-3.3-70B-Instruct-GGUF",
        "hf_tpl": "Llama-3.3-70B-Instruct-{q}.gguf", "qcase": "upper",
        "ms_id": "", "ms_tpl": "",
        # 仓库仅提供 Q2_K~Q5_K_M 单文件；Q6_K/Q8_0/F16 分片或不存在。
        "quants": ["Q2_K", "Q3_K_M", "Q4_0", "Q4_K_M", "Q5_K_M"],
    },
    {
        "key": "llama3.1-70b", "name": "Llama 3.1 70B Instruct", "params": "70B",
        "approx_q4": int(40.0 * _GB),
        "hf_repo": "unsloth/Llama-3.1-70B-Instruct-GGUF",
        "hf_tpl": "Llama-3.1-70B-Instruct-{q}.gguf", "qcase": "upper",
        "ms_id": "", "ms_tpl": "",
        "quants": STD_QUANTS,
    },

    # ---------- 其他主流（bartowski，标准精度）----------
    {
        "key": "llama3.1-8b", "name": "Llama 3.1 8B Instruct", "params": "8B",
        "approx_q4": int(4.9 * _GB),
        "hf_repo": "bartowski/Meta-Llama-3.1-8B-Instruct-GGUF",
        "hf_tpl": "Meta-Llama-3.1-8B-Instruct-{q}.gguf", "qcase": "upper",
        "ms_id": "", "ms_tpl": "",
        "quants": STD_QUANTS,
    },
    {
        "key": "mistral-7b", "name": "Mistral 7B Instruct v0.3", "params": "7B",
        "approx_q4": int(4.4 * _GB),
        "max_ctx": 32768,
        "hf_repo": "bartowski/Mistral-7B-Instruct-v0.3-GGUF",
        "hf_tpl": "Mistral-7B-Instruct-v0.3-{q}.gguf", "qcase": "upper",
        "ms_id": "", "ms_tpl": "",
        "quants": STD_QUANTS,
    },
    {
        "key": "gemma2-2b", "name": "Gemma 2 2B Instruct", "params": "2B",
        "approx_q4": int(1.6 * _GB),
        # Gemma 2 原生上下文上限为 8K。
        "max_ctx": 8192,
        "hf_repo": "bartowski/gemma-2-2b-it-GGUF",
        "hf_tpl": "gemma-2-2b-it-{q}.gguf", "qcase": "upper",
        "ms_id": "", "ms_tpl": "",
        "quants": STD_QUANTS,
    },
    {
        "key": "gemma2-9b", "name": "Gemma 2 9B Instruct", "params": "9B",
        "approx_q4": int(5.4 * _GB),
        "max_ctx": 8192,
        "hf_repo": "bartowski/gemma-2-9b-it-GGUF",
        "hf_tpl": "gemma-2-9b-it-{q}.gguf", "qcase": "upper",
        "ms_id": "", "ms_tpl": "",
        "quants": STD_QUANTS,
    },
    {
        "key": "phi3.5-mini", "name": "Phi-3.5 mini Instruct", "params": "3.8B",
        "approx_q4": int(2.3 * _GB),
        "hf_repo": "bartowski/Phi-3.5-mini-instruct-GGUF",
        "hf_tpl": "Phi-3.5-mini-instruct-{q}.gguf", "qcase": "upper",
        "ms_id": "", "ms_tpl": "",
        "quants": STD_QUANTS,
    },
    {
        "key": "phi4-mini", "name": "Phi-4 mini Instruct", "params": "3.8B",
        "approx_q4": int(2.3 * _GB),
        "hf_repo": "bartowski/Phi-4-mini-instruct-GGUF",
        "hf_tpl": "Phi-4-mini-instruct-{q}.gguf", "qcase": "upper",
        "ms_id": "", "ms_tpl": "",
        "quants": STD_QUANTS,
    },
]

ALL_MODELS = _MODELS

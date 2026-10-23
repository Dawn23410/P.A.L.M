"""Ollama 模型目录：国内 HF 镜像 + 魔搭社区双来源，含可选量化精度。

目录为「引导」向导的模型清单数据源，前端据此渲染可选模型卡片（名称 / 参数量 /
近似体积），并提供量化精度下拉。精度集合在原有 Q2_K ~ Q8_0 基础上新增了
**F16 全精度**（半精度权重，体积约为 Q4_K_M 的 3.3 倍）；每个 (模型, 精度, 来源)
组合给出对应 GGUF 下载 URL，真实文件体积以后端下载管理器 HEAD 探测为准，
approx_size 仅作下载前展示（按精度比例估算）。

精度可用性说明：
- 仓库并非都提供全精度 F16。为避免 404，F16 仅在「明确提供 f16 文件」的仓库
  出现（unsloth 的 DeepSeek-R1 蒸馏系列、bartowski 的 GLM-4-9B-1M、unsloth 的
  MiniMax 等），通过每模型显式 f16_file 指定，不靠大小写猜。
- 其余仓库仅提供标准 K-quants（Q2_K ~ Q8_0）。

来源可靠性：
- HF 镜像（hf-mirror.com）条目均来自官方组织（Qwen）或主流量化作者
  （unsloth / bartowski），文件名已逐项核对。
- 魔搭社区（modelscope.cn）目前仅 Qwen 官方仓库有稳定 GGUF 镜像；非 Qwen 模型
  在魔搭多为社区镜像且文件名不统一，故该精度的 modelscope.url 留空，前端自动禁用
  「魔搭社区」按钮，用户改用 HF 镜像即可。
- 体积较大（≥32B）的模型在仓库中可能被切分为多文件（如 -00001-of-00002.gguf），
  当前下载器按单文件下载，遇到分片需手动合并或改用 huggingface-cli；后续可扩展。
- MiniMax-M2.7 为 229B 超大模型，仅作可选展示，本地部署需极大显存/内存。

注意：URL 为常用 GGUF 仓库的精选映射，可随社区更新调整；下载管理器为通用实现，
任何可达 URL 均可下载。
"""
# GGUF 模型的量化精度集合。SafeTensors 转换（llama.cpp）已移除。
from __future__ import annotations

# 国内 HF 镜像（替代 huggingface.co，规避境外网络问题）。
MIRROR_HF = "https://hf-mirror.com"
# 魔搭社区模型文件解析地址。
MIRROR_MS = "https://modelscope.cn/models"

# 提供给用户的量化精度集合（key 用于 url 文件名，label 用于展示）。
# F16 为全精度（半精度）权重；其余为 K-quants。
QUANTS = [
    ("F16", "F16（全精度）"),
    ("Q2_K", "Q2_K（最小体积）"),
    ("Q3_K_M", "Q3_K_M"),
    ("Q4_0", "Q4_0"),
    ("Q4_K_M", "Q4_K_M（推荐）"),
    ("Q5_K_M", "Q5_K_M"),
    ("Q6_K", "Q6_K"),
    ("Q8_0", "Q8_0（近无损）"),
]
QUANT_LABELS = dict(QUANTS)
DEFAULT_QUANT = "Q4_K_M"

# 上下文窗口（num_ctx）默认上限（128K）；可在每模型用 max_ctx 字段覆盖。
# 前端「上下文窗口」选择框从 1K 到该上限按 2 的幂生成选项。
DEFAULT_MAX_CTX = 131072

# 各精度相对 Q4_K_M 的体积比例（仅用于下载前估算，真实体积以 HEAD 探测为准）。
QUANT_RATIO = {
    "F16": 3.30,
    "Q2_K": 0.54,
    "Q3_K_M": 0.68,
    "Q4_0": 0.94,
    "Q4_K_M": 1.0,
    "Q5_K_M": 1.13,
    "Q6_K": 1.36,
    "Q8_0": 1.75,
}
# Qwen3 在官方仓库额外提供 Q5_0（标准 K-quants 之外）。
QUANT_LABELS["Q5_0"] = "Q5_0"
QUANT_RATIO["Q5_0"] = 1.08

# CodeGeeX4 特殊量化（低比特 IQ / 大模式 Q6_K_L）。
QUANT_RATIO["Q6_K_L"] = 1.45
QUANT_RATIO["IQ2_M"] = 0.55
QUANT_LABELS["IQ2_M"] = "IQ2_M（极小体积）"
QUANT_RATIO["IQ3_M"] = 0.70
QUANT_LABELS["IQ3_M"] = "IQ3_M"

_DYN_LABELS = {
    "UD-IQ1_M": "UD-IQ1_M（极小体积）",
    "UD-IQ2_XXS": "UD-IQ2_XXS",
    "UD-IQ2_XS": "UD-IQ2_XS",
    "UD-IQ2_M": "UD-IQ2_M",
    "UD-IQ2_L": "UD-IQ2_L",
    "UD-IQ3_XXS": "UD-IQ3_XXS",
    "UD-IQ3_XS": "UD-IQ3_XS",
    "UD-IQ3_M": "UD-IQ3_M",
    "UD-Q2_K": "UD-Q2_K",
    "UD-Q3_K_M": "UD-Q3_K_M",
    "UD-Q4_K_M": "UD-Q4_K_M（推荐）",
    "UD-Q5_K_M": "UD-Q5_K_M",
    "UD-Q6_K": "UD-Q6_K",
    "UD-Q8_0": "UD-Q8_0（近无损）",
}
_DYN_RATIO = {
    "UD-IQ1_M": 0.30, "UD-IQ2_XXS": 0.40, "UD-IQ2_XS": 0.45, "UD-IQ2_M": 0.50,
    "UD-IQ2_L": 0.55, "UD-IQ3_XXS": 0.58, "UD-IQ3_XS": 0.62, "UD-IQ3_M": 0.70,
    "UD-Q2_K": 0.55, "UD-Q3_K_M": 0.70, "UD-Q4_K_M": 1.00, "UD-Q5_K_M": 1.13,
    "UD-Q6_K": 1.36, "UD-Q8_0": 1.75,
}
QUANT_LABELS.update(_DYN_LABELS)
QUANT_RATIO.update(_DYN_RATIO)
QUANT_LABELS["BF16"] = "BF16（全精度，需 huggingface-cli 拉取分片）"
QUANT_RATIO["BF16"] = 3.30


def _hf_url(repo: str, file: str) -> str:
    if not repo or not file:
        return ""
    return f"{MIRROR_HF}/{repo}/resolve/main/{file}"


def _ms_url(ms_id: str, file: str) -> str:
    if not ms_id or not file:
        return ""
    return f"{MIRROR_MS}/{ms_id}/resolve/master/{file}"


def _hf_repo_url(repo: str) -> str:
    """仓库主页链接（不含具体文件），用于 SafeTensors 原始权重来源的展示与可用性判断。"""
    if not repo:
        return ""
    return f"{MIRROR_HF}/{repo}"


def _ms_repo_url(ms_id: str) -> str:
    """魔搭仓库主页链接（不含具体文件），同上。"""
    if not ms_id:
        return ""
    return f"{MIRROR_MS}/{ms_id}"


def _fmt_file(tpl: str, qkey: str, qcase: str) -> str:
    """把文件名模板里的 {q} 替换为对应大小写精度的文件名片段。"""
    qq = qkey.lower() if qcase == "lower" else qkey
    return tpl.format(q=qq)


# 目录原始条目（字典形式，字段见下）：
# key            模型唯一 key
# name           展示名
# params         参数量（如 "7B"）
# approx_q4      Q4_K_M 近似体积（字节）
# hf_repo        HF 仓库 id（空串=无 HF 来源）
# hf_tpl         HF 文件名模板（含 {q}，空串=无）
# qcase          "lower" / "upper"，决定 {q} 大小写
# ms_id          魔搭模型 id（空串=无魔搭镜像）
# ms_tpl         魔搭文件名模板（含 {q}，空串=无）
# quants         该模型支持的精度 key 列表（子集）
# f16_file       显式 F16 文件名（仅 FULL_QUANTS 模型需要，否则留空）
# large          是否为超大模型（仅展示提示用）
from .catalog_data import ALL_MODELS, STD_QUANTS, _MODELS


def _parse_params_b(params_str: str) -> float:
    """从参数字符串（如 '7B', '21B（3.6B 激活）', '1T（32 专家）'）提取以 B 为单位的数值。"""
    s = params_str.replace("，", ",").replace("（", "(").replace("）", ")").strip()
    # 先看是否含 T（万亿）
    import re
    m = re.search(r'([\d.]+)\s*T', s)
    if m:
        return float(m.group(1)) * 1000
    m = re.search(r'([\d.]+)\s*B', s)
    if m:
        return float(m.group(1))
    return 999  # 无法解析时视为超大


# ≤32B 参数上限：超过此值的模型不在下载器目录中展示。
_MAX_PARAMS_B = 32.0


def _family_version(name: str) -> tuple[str, str]:
    """由展示名推导「模型名称（family）」与「版本（version）」，供 4 级联动下拉用。"""
    n = name
    if n.startswith("Qwen2.5-Coder"):
        return "Qwen", "2.5-Coder"
    if n.startswith("Qwen2.5"):
        return "Qwen", "2.5"
    if n.startswith("Qwen3"):
        return "Qwen", "3"
    if n.startswith("QwQ"):
        return "Qwen", "QwQ"
    if n.startswith("DeepSeek-R1 Distill Qwen"):
        return "DeepSeek-R1", "蒸馏 · Qwen"
    if n.startswith("DeepSeek-R1 Distill Llama"):
        return "DeepSeek-R1", "蒸馏 · Llama"
    if n.startswith("DeepSeek"):
        return "DeepSeek-R1", "标准"
    if n.startswith("Llama 3.2"):
        return "Llama", "3.2"
    if n.startswith("Llama 3.3"):
        return "Llama", "3.3"
    if n.startswith("Llama 3.1"):
        return "Llama", "3.1"
    if n.startswith("GLM-Edge"):
        return "GLM-Edge", "v1"
    if n.startswith("CodeGeeX4"):
        return "CodeGeeX4", "9B"
    if n.startswith("Hy-MT2"):
        return "Hy-MT2", "v1"
    if n.startswith("GLM"):
        return "GLM", "4"
    if n.startswith("MiniMax"):
        return "MiniMax", "M2.7"
    if n.startswith("GPT-OSS"):
        # 注意：先判 120B，否则 "20B" 会作为 "120B" 的子串命中，导致 120B 误归到 20B 版本。
        ver = "120B" if "120B" in n else ("20B" if "20B" in n else "标准")
        return "GPT-OSS", ver
    if n.startswith("Kimi"):
        return "Kimi", "K2"
    if n.startswith("Mistral"):
        return "Mistral", "7B"
    if n.startswith("Gemma"):
        return "Gemma", "2"
    if n.startswith("Phi-3"):
        return "Phi", "3.5"
    if n.startswith("Phi-4"):
        return "Phi", "4"
    # 兜底：取首个词作为 family。
    return n.split()[0], ""


def _build_quant(m: dict, qkey: str) -> dict:
    """构造单个精度条目（含 HF / 魔搭双来源 URL 与自动优选来源）。"""
    qlabel = QUANT_LABELS.get(qkey, qkey)
    if qkey == "F16":
        # 全精度仅 HF 提供，文件名由 f16_file 显式给出（避免大小写猜错 404）。
        hf_url = _hf_url(m["hf_repo"], m.get("f16_file", "")) if m.get("f16_file") else ""
        ms_url = ""
    else:
        hf_url = (
            _hf_url(m["hf_repo"], _fmt_file(m["hf_tpl"], qkey, m["qcase"]))
            if m.get("hf_repo") else ""
        )
        ms_tpl = m.get("ms_tpl")
        ms_url = (
            _ms_url(m["ms_id"], _fmt_file(ms_tpl, qkey, m["qcase"]))
            if (m.get("ms_id") and ms_tpl) else ""
        )
    sources = {
        "hf": {"url": hf_url, "label": "HF 镜像"},
        "modelscope": {"url": ms_url, "label": "魔搭社区"},
    }
    # 自动优选来源：魔搭社区优先（平台偏好），无魔搭时回退 HF。
    preferred = next((s for s in ("modelscope", "hf") if sources[s]["url"]), "")
    return {
        "key": qkey,
        "label": qlabel,
        "approx_size": int(m["approx_q4"] * QUANT_RATIO.get(qkey, 1.0)),
        "format": "gguf",
        "needs_conversion": False,
        "sources": sources,
        "preferred_source": preferred,
    }


def _entry_for(m: dict) -> dict:
    """由原始条目构造扁平目录条目（含 quantizations / sources / 格式化信息）。"""
    family, version = _family_version(m["name"])
    quants = [_build_quant(m, qkey) for qkey in m.get("quants", STD_QUANTS)]
    default_q = next((q for q in quants if q["key"] == DEFAULT_QUANT), quants[0])
    return {
        "model_key": m["key"],
        "key": m["key"],
        "name": m["name"],
        # family / version 供前端 4 级联动（模型名称 / 版本）。
        "family": family,
        "version": version,
        "params": m["params"],
        "tag": m.get("tag", ""),
        "approx_size": m["approx_q4"],
        "default_quant": DEFAULT_QUANT,
        "quantizations": quants,
        "format": "gguf",
        "max_ctx": m.get("max_ctx", DEFAULT_MAX_CTX),
        "large": m.get("large", False),
        # 兼容旧字段：取默认精度的双来源 URL。
        "sources": default_q["sources"],
    }


def build_catalog() -> list[dict]:
    """返回按「模型名称→版本→参数量」分组的目录树，供前端 4 级联动下拉渲染。

    每个叶子（size）含 model_key 与 quantizations（各精度含 HF/魔搭双来源 URL 与
    preferred_source），前端据此联动展示「模型名称/版本/参数量/量化精度」四个选择框。
    """
    tree: dict[str, dict[str, list[dict]]] = {}
    for m in ALL_MODELS:
        if _parse_params_b(m.get("params", "999B")) > _MAX_PARAMS_B:
            continue  # 超过 32B 的模型不在下载器目录中展示
        entry = _entry_for(m)
        tree.setdefault(entry["family"], {}).setdefault(entry["version"], []).append(entry)
    out = []
    for family in sorted(tree.keys()):
        versions = tree[family]
        vlist = []
        for version in sorted(versions.keys()):
            vlist.append({
                "key": version,
                "name": version or "—",
                "sizes": versions[version],
            })
        out.append({"key": family, "name": family, "versions": vlist})
    return out


def resolve_model(key: str) -> dict | None:
    """按 model_key 取目录条目（含 quantizations 与各精度 sources）；超过 32B 的模型返回 None。"""
    for m in ALL_MODELS:
        if m["key"] == key:
            if _parse_params_b(m.get("params", "999B")) > _MAX_PARAMS_B:
                return None
            return _entry_for(m)
    return None

"""模型文件上传能力登记表（控制器逻辑）。

决定给定模型是否原生支持文件 / 多模态上传：

- 支持（supports_files=True） -> 聊天时跳过解析砖块，直接将文件传给模型（direct）
- 不支持（supports_files=False）-> 聊天时先把文件交给解析砖块处理成结构化文本（process）

登记采用「关键字通配」方式，命中即判定；未知模型默认按「不支持」处理，
以确保文件仍能被解析砖块转成文本后消费，不会因误判而丢文件。

真实集成时只需在此扩充 FILE_CAPABLE_PATTERNS / TEXT_ONLY_PATTERNS。
"""
from __future__ import annotations

import fnmatch

# 已知「支持原生文件 / 多模态上传」的模型关键字（前缀或通配）。
FILE_CAPABLE_PATTERNS = [
    # OpenAI
    "gpt-4o*", "gpt-4-turbo*", "gpt-4-vision*",
    # Anthropic
    "claude-3*", "claude-3.5*", "claude-opus-4*",
    "claude-sonnet-4*", "claude-haiku-4*",
    # Google
    "gemini-1.5*", "gemini-2.0*", "gemini-2.5*",
    # 阿里通义（视觉）
    "qwen-vl*", "qwen2-vl*", "qwen2.5-vl*",
    # 其他多模态
    "glm-4v*", "llava*", "internvl*",
]

# 明确「不支持文件上传」的文本模型（命中即 process，优先级高于上面的通配）。
TEXT_ONLY_PATTERNS = [
    # OpenAI 文本
    "gpt-3.5*", "gpt-4", "gpt-4-0314", "gpt-4-0613", "text-davinci*",
    # Anthropic 旧版
    "claude-2*", "claude-instant*",
    # Google 旧版
    "gemini-1.0*",
    # 阿里通义（文本）
    "qwen-turbo", "qwen-plus", "qwen-max", "qwen2*", "qwen1.5*",
    # 其他文本模型
    "llama-2*", "llama-3*", "deepseek*", "mistral*",
    "glm-4*", "chatglm*",
]


def is_model_file_capable(model: str | None) -> bool:
    """模型是否原生支持文件 / 多模态上传。

    - model 为空（如本地 mock）-> False（走解析砖块）
    - 命中 TEXT_ONLY_PATTERNS   -> False
    - 命中 FILE_CAPABLE_PATTERNS-> True
    - 均不命中（未知）          -> False（默认交给解析，保证文件可用）
    """
    if not model:
        return False
    m = model.strip().lower()
    # 先判「支持文件」：带 -vl 等视觉标识的模型（如 qwen2.5-vl）应优先命中，
    # 避免被宽泛的 qwen2* 文本规则误判为不支持。
    for pat in FILE_CAPABLE_PATTERNS:
        if fnmatch.fnmatch(m, pat):
            return True
    for pat in TEXT_ONLY_PATTERNS:
        if fnmatch.fnmatch(m, pat):
            return False
    return False


def file_handling_mode(model: str | None, has_files: bool) -> str:
    """根据模型能力与是否有附件，返回处理方式：

    - "none"    : 无附件，无需处理
    - "direct"  : 模型支持文件上传，跳过解析直接传文件
    - "process" : 模型不支持文件上传，先经解析砖块处理
    """
    if not has_files:
        return "none"
    return "direct" if is_model_file_capable(model) else "process"

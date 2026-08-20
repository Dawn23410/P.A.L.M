"""Worker 提示构建（移植自 palm dual_runner._build_prompt_native + dual_prompt）。

仅保留 Worker 侧（后台任务执行 Agent）：系统模板沿用归档 NATIVE_SYSTEM_PROMPT_TPL，
记忆上下文注入专业记忆（ProfessionalMemory.build_injection_context）+ 轨迹历史；
Worker 不做角色扮演（跳过 roleplay 清洗，避免误伤任务文本）。
"""
from __future__ import annotations

import re

from .dual_parse import _normalize_native_chunk  # noqa: F401  解析器随包可用

_TOOL_WRAPPER_RE = re.compile(
    '✅\\s*工具【[^】]*】执行成功。\\s*以下是该工具的输出，\\*\\*直接当作回答用户的依据，'
    '不要再调用工具或追问\\*\\*：\\s*')
_STATUS_LINE_RE = re.compile('^[✅❌⚠️]\\s*状态:\\s*.+$', re.MULTILINE)
_ISOLATION_RE = re.compile('^\\s*隔离等级:\\s*.+$', re.MULTILINE)
_GUI_HINT_RE = re.compile('^\\s*输出:\\s*\\(空\\)\\s*[—-]\\s*GUI 类命令.*$', re.MULTILINE)
_RESULT_LABEL_RE = re.compile('工具\\[[^\\]]*]\\s*结果:\\s*')


def _sanitize_tool_text(text: str) -> str:
    """剥离旧版工具结果装饰壳（emoji/状态行/隔离等级/GUI 提示/结果标签），只留原始输出。"""
    if not text:
        return text
    text = _TOOL_WRAPPER_RE.sub('', text)
    text = _STATUS_LINE_RE.sub('', text)
    text = _ISOLATION_RE.sub('', text)
    text = _GUI_HINT_RE.sub('', text)
    text = _RESULT_LABEL_RE.sub('', text)
    return re.sub('\\n{3,}', '\n\n', text).strip()


# Worker 角色段（归档 dual_prompt._compile_roleplay_section 的 worker 分支原样）
_WORKER_ROLEPLAY_SECTION = (
    "【Worker 模式】你是后台任务执行 Agent，专注完成指定任务。"
    "不进行角色扮演，以标准技术语气回答。"
)

# 归档 dual_runner.NATIVE_SYSTEM_PROMPT_TPL（Worker 侧使用，去掉角色/记忆占位之外的冗余）
_NATIVE_SYSTEM_PROMPT_TPL = (
    '你是一个**有完整行动能力的 Agent**，不是普通对话 AI——要**真正动手帮用户操作电脑**。\n\n'
    '# 🛠️ 工具\n'
    '你可以使用模型内置的工具（function calling）来完成任务，不要以纯文本格式输出工具调用指令。\n'
    '{tools_note}\n'
    '**关键原则**：成功执行工具后立即下一步，不要重复相同调用。GUI命令(stdout空+退出码0)=成功。\n\n'
    '# 📋 执行准则\n'
    '1. **独立对待每条消息**——短词按字面回应，不从历史推断意图。\n'
    '2. **工具优先**——涉及操作的任务必须调工具完成，不说"做不到"。\n'
    '3. **试错到底**——首次失败至少换2种方法再试，穷尽前不放弃。\n'
    '4. **限时思考**——识别需求后最多想2句就调用工具或回复。\n'
    '5. **后台任务必须闭环**——可以启动耗时较长的子进程，但**严禁**以"已在后台运行"一句话结束。\n\n'
    '# 🎭 角色设定\n'
    '{roleplay_context}\n\n'
    '# 🧠 记忆\n'
    '{memory_context}\n'
)


def build_worker_prompt(
    goal: str,
    context: str,
    history: list,
    memory_context: str,
    tools_desc: str,
    keep_recent: int = 6,
    skill_context: str = "",
) -> str:
    """组装 Worker 单轮完整提示（系统模板沿用归档 + 目标 + 轨迹历史）。

    keep_recent>0 时对历史做「摘要式压缩」：最近 keep_recent 步保留完整
    Action/Observation，更早步骤按工具名统计压缩成一行摘要（零 LLM、确定性）。
    摘要置于末尾，避免打断固定前缀，保住前缀缓存命中；压缩同时封顶输入增长。
    skill_context：PCB 扩展板已习得技能（进化注入），拼在历史之后。
    """
    tools_note = f"可用工具：\n{tools_desc}\n不确定用什么工具时先调用可用的工具观察结果。"
    sys_part = _NATIVE_SYSTEM_PROMPT_TPL.format(
        tools_note=tools_note,
        roleplay_context=_WORKER_ROLEPLAY_SECTION,
        memory_context=memory_context or "（无专业经验）",
    )
    parts = [sys_part, f"目标：{goal}", f"上下文：{context}"]
    if keep_recent > 0 and len(history) > keep_recent:
        recent = history[-keep_recent:]
        older = history[:-keep_recent]
        for action, obs in recent:
            parts.append(f"Action: {action}\nObservation: {obs}")
        parts.append(_digest_history(older))
    else:
        for action, obs in history:
            parts.append(f"Action: {action}\nObservation: {obs}")
    if skill_context:
        parts.append(skill_context)
    return "\n\n".join(parts)


def _digest_history(older: list) -> str:
    """早期轨迹摘要：按工具名统计调用次数（确定性、零 LLM）。"""
    counts: dict[str, int] = {}
    for action, _obs in older:
        counts[action] = counts.get(action, 0) + 1
    tools = "、".join(f"{k}×{v}" for k, v in counts.items())
    return (f"【早期轨迹摘要（已压缩）】已执行 {len(older)} 步：{tools or '无工具调用'}；"
            "细节已归档，可结合专业经验继续执行。")

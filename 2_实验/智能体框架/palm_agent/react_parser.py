"""ReAct 输出解析：把 LLM 文本解析为 tool / response / unknown 指令。"""
from __future__ import annotations

import json
import re

# 动作/回答标签：兼容模型偶发的 Markdown 加粗写法。模型常见两种：
#   `**Action**: <名>`（加粗在标签上、冒号在外，Action 与冒号间有闭合 `**`）
#   `**Action:** <名>`（冒号在内、加粗不闭合）
# 另兼容中文全角冒号 `：`。动作名用 [^\s*]+ 取词，避免把结尾 `**` 一并吞入。
_RE_ACTION = re.compile(r"\*{0,2}Action\*?\*?\s*[:：]\s*\*?\*?\s*`?\s*([^\s*`]+)", re.MULTILINE)
_RE_RESPONSE = re.compile(r"\*{0,2}(?:Response|最终回答|Answer)\*?\*?\s*[:：]\s*\*?\*?\s*(.+)", re.MULTILINE | re.DOTALL)


def _strip_affinity_json(text: str) -> str:
    """剥离模型自发的"好感度 JSON"代码块（角色扮演场景偶发）。

    模型有时在回复末尾自发追加 ```json\n{"当前的好感度":...}\n``` 格式的元数据块，
    后端计算好感度，不应由模型输出。统一在此静默剥离。
    """
    # 1) Markdown 代码块包裹的 JSON
    text = re.sub(r"```(?:json)?\s*\n?[\{\[].*?[\}\]]\s*\n?```", "", text, flags=re.DOTALL)
    # 2) 裸 JSON（无代码块包裹）：{key:value} 或 [key:value]（最后一段）
    text = re.sub(r"\n?\s*\{[^{}]*?(?:好感度|affection|emotion)[^{}]*?\}\s*$", "", text, flags=re.DOTALL)
    text = re.sub(r"\n?\s*\[[^\[\]]*?(?:好感度|affection|emotion)[^\[\]]*?\]\s*$", "", text, flags=re.DOTALL)
    return text.strip()


def parse_react_output(text: str) -> dict:
    """从 LLM 输出中解析 ReAct 指令。

    Returns:
        {"type": "tool", "name": ..., "input": {...}} 或
        {"type": "response", "content": ...} 或
        {"type": "unknown", "content": ...}
    """
    m_a = _RE_ACTION.search(text)
    m_r = _RE_RESPONSE.search(text)
    # 动作指令优先：两者皆有时以先出现者为准（模型在动作轮通常先写 Action），
    # 避免把推理中提及 "Response" 字样的文本误判为终答。
    if m_a and (m_r is None or m_a.start() < m_r.start()):
        name = m_a.group(1).strip()
        raw_input = _extract_action_input(text) or "{}"
        parsed = _parse_tool_input(raw_input)
        return {"type": "tool", "name": name, "input": parsed}

    if m_r:
        content = m_r.group(1).strip()
        # 模型偶发在回复末尾自发 Markdown 代码块（如 ```json\n{"好感度":...}\n```），静默剥离
        content = _strip_affinity_json(content)
        return {"type": "response", "content": content}

    # 未知格式→直接用原文回复，但剥离尾部的 JSON 代码块
    cleaned = _strip_affinity_json(text).strip()
    return {"type": "unknown", "content": cleaned}


def _locate_json_start(rest: str) -> int | None:
    """定位 ActionInput 之后的首个 JSON 起点（{ / [ / "）。"""
    for i, ch in enumerate(rest):
        if ch in "{[\"":
            return i
    return None


def _scan_bracket_json(rest: str) -> str | None:
    """括号深度扫描抽取完整 {…} / […] JSON（兼容嵌套与转义）。"""
    first = rest[0]
    open_ch, close_ch = first, "}" if first == "{" else "]"
    depth = 0
    in_str = False
    esc = False
    for i, ch in enumerate(rest):
        if esc:
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return rest[:i + 1]
    return None


def _scan_string_json(rest: str) -> str | None:
    """ActionInput 本身是 JSON 字符串（双编码）时，截取该字符串。"""
    esc = False
    for i in range(1, len(rest)):
        ch = rest[i]
        if esc:
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if ch == '"':
            return rest[:i + 1]
    return None


def _extract_action_input(text: str) -> str | None:
    """从 `ActionInput` 之后提取完整 JSON（兼容嵌套/转义/双编码/Markdown 包裹）。

    大模型偶发把标签写成 `**Action:**` / `**ActionInput:**`，或把 JSON 包进
    ```` ```json ```` 代码块；先用括号深度扫描兼容嵌套/转义，再跳过标签与 JSON
    之间的 `**`、反引号、`json`、冒号、空白，定位首个 `{`/`[`/`"` 作为 JSON 起点。
    """
    marker = "ActionInput"
    idx = text.find(marker)
    if idx == -1:
        return None
    rest = text[idx + len(marker):]
    # 跳过标签与 JSON 之间的 ** / ``` / json / 冒号 / 空白，定位 JSON 起点
    start = _locate_json_start(rest)
    if start is None:
        # 既无对象/数组也无字符串：保留原文交由 _parse_tool_input 兜底（剥掉标签后的冒号）
        return rest.strip().lstrip(":").strip()
    rest = rest[start:]
    first = rest[0]
    if first in "{[":
        return _scan_bracket_json(rest)
    if first == '"':
        return _scan_string_json(rest)
    return None


def _parse_tool_input(raw: str) -> dict:
    """解析 ActionInput 为工具参数字典，兼容大模型常见的格式退化。

    兼容情况：
    - 正常 JSON 对象 → 直接返回
    - JSON 字符串（整体被引号包成字符串，双编码）→ 再解析一层
    - {"value": "<json 字符串>"} 包裹 → 提取内层对象
    - 无法解析 → {"value": raw}（保持原行为，交由工具执行时报错）
    """
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return {"value": raw}
    if isinstance(obj, str):
        try:
            obj = json.loads(obj)
        except json.JSONDecodeError:
            return {"value": obj}
    if isinstance(obj, dict) and list(obj.keys()) == ["value"] and isinstance(obj["value"], str):
        try:
            inner = json.loads(obj["value"])
        except json.JSONDecodeError:
            return obj
        return inner if isinstance(inner, dict) else obj
    return obj if isinstance(obj, dict) else {"value": raw}

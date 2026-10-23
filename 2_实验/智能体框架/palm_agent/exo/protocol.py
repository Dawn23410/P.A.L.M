"""外骨骼 Worker 协议：ReAct 文本标记解析（沿用心智魔方 ||DATA|| 同思想）。

Worker 模型在回复中追加：
- ||TOOL||{"name":"<工具名>","args":{...}}||END||  → 调工具
- ||FIN||{"result":"<最终结论>"}||END||            → 任务收尾
不依赖 function calling，任意聊天模型可用；标记损坏则回退纯文本（继续追问）。
"""
import json
import re
from dataclasses import dataclass
from typing import Tuple


@dataclass
class TaskGoal:
    """Boss 委派给 Worker 的任务目标（来自 ||EXO|| 透传）。"""
    goal: str
    context: str = ""


_TOOL_RE = re.compile(r"\|\|TOOL\|\|(.*?)\|\|END\|\|", re.S)
_FIN_RE = re.compile(r"\|\|FIN\|\|(.*?)\|\|END\|\|", re  .S)


def parse_worker_output(raw: str) -> Tuple[str, dict]:
    """解析 Worker 一轮输出：返回 ('tool'|'fin'|'text', payload)。"""
    fin = _FIN_RE.search(raw)
    if fin:
        payload = _safe_json(fin.group(1))
        return "fin", payload if isinstance(payload, dict) else {"result": str(payload)}
    tool = _TOOL_RE.search(raw)
    if tool:
        payload = _safe_json(tool.group(1))
        if isinstance(payload, dict) and payload.get("name"):
            return "tool", payload
    return "text", {"text": raw.strip()}


def _safe_json(text: str) -> object:
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return None


def extract_exo(payload: object) -> TaskGoal:
    """把 Boss 透传的 exo 字段归一为 TaskGoal。"""
    if isinstance(payload, dict):
        return TaskGoal(
            goal=str(payload.get("goal", "")),
            context=str(payload.get("context", "")),
        )
    return TaskGoal(goal=str(payload or ""))

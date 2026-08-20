"""原生工具调用运行器（移植自 palm dual_runner.py 的 Worker 相关部分）。

- 反思自检：回答后让模型自审（verdict ok/revise），revise 时给出修正指令再补一轮。
- 工具结果装饰壳清洗：_sanitize_tool_text 剥离旧版包装，只留原始输出。
- 同步适配：经 worker.llm.complete(prompt, tools) 走原生 function calling。
"""
from __future__ import annotations

import json

from .prompt import _sanitize_tool_text  # noqa: F401  供外部复用

_REFLECT_PROMPT = '你是一个严苛的回答自我审查员。请判断「本次回答」是否真正、完整地满足了「用户请求」。\n\n用户请求：\n{request}\n\n本次回答：\n{draft}\n{failure_note}\n\n仅输出一个 JSON 对象，不要任何额外文字：\n{{"verdict": "ok" 或 "revise", "issue": "若存在问题，用一句话说明", "instruction": "若需修正，给自己的具体修正指令（中文）"}}\n\n判定要点：\n- 回答明显未回应请求、遗漏用户明确要求的重点、或声称完成但仍有未解决的工具失败，则 verdict="revise"。\n- 回答已合理满足请求则为 "ok"。\n'


def _parse_reflect_json(text: str) -> dict:
    """从模型输出中稳健提取首个 JSON 对象（容忍 ```json 包裹/前后噪声）。"""
    text = (text or '').strip()
    start = text.find('{')
    end = text.rfind('}')
    if start == -1 or end <= start:
        return {}
    try:
        return json.loads(text[start:end + 1])
    except Exception:  # noqa: BLE001
        return {}


def reflect_once(worker, request: str, draft: str, had_failure: bool = False) -> str:
    """自检：返回修正指令（verdict=revise 时）；解析失败/异常一律降级为 ""（不自残）。

    使用 Worker 同款干事模型做自审；mock 模型（无反思语义）返回空，等效关闭。
    """
    failure_note = ''
    if had_failure:
        failure_note = '\n注意：本次有工具执行失败或被拦截，但回答可能未提及，请核实是否应向用户如实说明。\n'
    prompt = _REFLECT_PROMPT.format(request=request, draft=draft, failure_note=failure_note)
    try:
        raw = worker.llm.complete(prompt)["text"]
    except Exception:  # noqa: BLE001
        return ""
    data = _parse_reflect_json(raw)
    if (data.get('verdict') or '').lower() == 'revise':
        return (data.get('instruction') or data.get('issue') or '请检查并补全回答').strip()
    return ""

def _normalize_native_chunk(chunk) -> tuple[str, str, object]:
    """把 native 流式 chunk 统一为 (正文, 推理链, 原始 tool_calls)。"""
    if isinstance(chunk, dict):
        return (chunk.get('content') or '', chunk.get('reasoning') or '', chunk.get('tool_calls'))
    if isinstance(chunk, str):
        return (chunk, '', None)
    return (getattr(chunk, 'content', None) or getattr(chunk, 'delta', '') or '', getattr(chunk, 'reasoning', None) or '', getattr(chunk, 'tool_calls', None))

def _should_reflect(agent, state: dict) -> bool:
    """仅在「反思开关开启且本轮用过工具」时自检（纯闲聊不浪费 LLM 调用）。

    开关通过 agent._enable_reflection 控制（缺省视为开启）。
    """
    if state.get('skip_reflect'):
        return False
    if not getattr(agent, '_enable_reflection', True):
        return False
    return bool(state.get('used_tools'))

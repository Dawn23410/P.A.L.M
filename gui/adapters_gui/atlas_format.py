def _format_level(level: dict, detail: bool) -> dict:
    """把单个 level 压成 LLM 友好的控件清单（动态占位只标类型不标值）。"""
    nodes = level.get('nodes', []) or []
    controls = []
    for n in nodes:
        role = n.get('role')
        item = {'identity': n.get('identity'), 'type': n.get('control_type'), 'name': n.get('name') or '', 'role': role}
        if role and role != 'static':
            item['dynamic'] = n.get('dynamic')
        if detail:
            item['rect_relative'] = n.get('rect_relative')
        controls.append(item)
    return {'level_id': level.get('level_id'), 'control_count': len(controls), 'controls': controls}

def _entry_is_empty(entry: dict) -> bool:
    """条目无任何 level/节点 → 视为 Atlas 尚未建立。"""
    levels = entry.get('levels', {}) or {}
    return not any((lv.get('nodes') for lv in levels.values()))

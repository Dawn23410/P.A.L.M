def _filter_by_rect(boxes: list, rect) -> list:
    """只保留中心点落在目标窗口矩形内的 OCR 结果，排除其他窗口（如 WorkBuddy）文字干扰。"""
    if not rect:
        return boxes
    l, t, r, b = rect
    out = []
    for item in boxes:
        btxt, box = (item[0], item[1])
        bl, bt, br, bb = box
        cx, cy = ((bl + br) // 2, (bt + bb) // 2)
        if l <= cx <= r and t <= cy <= b:
            out.append(item)
    return out

def _win_error(msg: str) -> str:
    """统一错误前缀，便于 AI 识别。"""
    return f'[window_tools] {msg}'

def _parse_color(text: str) -> tuple[int, int, int] | None:
    """解析颜色字符串为 (r,g,b)；支持 #RRGGBB / RRGGBB / #RGB。无法解析返回 None。"""
    if not text:
        return None
    s = text.strip().lstrip('#')
    if len(s) == 3:
        s = ''.join((c * 2 for c in s))
    if len(s) != 6:
        return None
    try:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except ValueError:
        return None

def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return '#%02X%02X%02X' % rgb

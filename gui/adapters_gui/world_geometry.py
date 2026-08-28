def _area(rect: tuple) -> int:
    """矩形面积；rect 为 (左,上,右,下)。"""
    l, t, r, b = rect
    return max(0, r - l) * max(0, b - t)

def _contains(outer: tuple, inner: tuple, tol: int=4) -> bool:
    """inner 是否基本落在 outer 内（含容差，吸收 OCR 抖动）。"""
    ol, ot, or_, ob = outer
    il, it, ir, ib = inner
    return il >= ol - tol and it >= ot - tol and (ir <= or_ + tol) and (ib <= ob + tol)

def _norm_text(s: str) -> str:
    """去空白小写化，用于名称与 OCR 文本的鲁棒匹配。"""
    return ''.join((s or '').lower().split())

def _center(rect: tuple) -> tuple:
    """包围盒中心坐标。"""
    return ((rect[0] + rect[2]) / 2.0, (rect[1] + rect[3]) / 2.0)

def _iter_nodes(node: dict):
    """深度优先遍历 UIA 树节点（含自身）。"""
    yield node
    for child in node.get('children', []) or []:
        yield from _iter_nodes(child)

def _walk_confirmed(node, depth, out):
    """收集所有被 OCR 文本语义归属的 UIA 节点（带深度）。"""
    if node.get('name') and node.get('image_confirmed'):
        out.append((depth, node['control_type'].replace('Control', ''), node['name']))
    for c in node.get('children', []):
        _walk_confirmed(c, depth + 1, out)


import ctypes
import os
from PIL import ImageFont

def _point_owned_by(hwnd_target: int, cx: float, cy: float) -> bool:
    """像素所有权测试：坐标 (cx,cy) 处的真实顶层窗口是否为目标窗口或其子窗口。

    用以区分"目标窗口自身的文本"与"叠在目标之上、且不透明的别窗文本"——
    后者几何上也落在目标矩形内，但那一点真正可见的窗口是别窗，绝不应认领为目标内容。
    """
    if not hwnd_target:
        return False
    _user32 = ctypes.windll.user32

    class _POINT(ctypes.Structure):
        _fields_ = [('x', ctypes.c_long), ('y', ctypes.c_long)]
    top = _user32.WindowFromPoint(_POINT(int(cx), int(cy)))
    if not top:
        return False
    if top == hwnd_target:
        return True
    return bool(_user32.IsChild(hwnd_target, top))

def _load_font(size: int):
    """优先加载系统中文字体，失败回退默认。"""
    candidates = ['C:/Windows/Fonts/msyh.ttc', 'C:/Windows/Fonts/simhei.ttf', 'C:/Windows/Fonts/msyhbd.ttc']
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()

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

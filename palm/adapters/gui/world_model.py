"""GUI 世界模型：UIA 树 + 图像检索 混合架构。

目标：把一个真实窗口"看"成一份结构化数据，而不是一张模糊的截图。
两条互相校核的感知通道：
  - 结构通道（UIA 树）：Windows UI Automation 给出的原生控件树，自带控件类型、
    名称、automation_id、精确坐标、可见性、启用态、父子层级——机器可读、像素无关。
  - 像素通道（图像检索）：对窗口截图做 OCR，拿到"人眼真正看到"的文本与包围盒，
    用来反向校验 UIA 树（哪些节点真的画出来了）、并补全 UIA 漏掉的自定义绘制元素。

融合产物是一份 world_model JSON，包含：
  - uia_tree：带 image_confirmed / visible_text 标注的控件树
  - visible_layer：可见层级（二维包含树）+ ocr 匹配 / 图像独有 / 结构独有 三张清单
  - meta：目标窗口、截图路径、统计

设计边界：纯读取、不改任何窗口状态（不点击、不写注册表），可安全反复跑。
"""
from __future__ import annotations
import json
import logging
import os
import tempfile
import time
import ctypes
from dataclasses import dataclass, field
import pyautogui
from PIL import Image, ImageDraw, ImageFont
from .desktop_control import ocr_boxes, find_window
from .world_geometry import _area, _contains, _norm_text, _center, _iter_nodes, _walk_confirme, _point_owned_by, _load_font
_LOGGER = logging.getLogger(__name__)
MAX_DEPTH = 12
MAX_NODES = 1500

def _iou(a: tuple, b: tuple) -> float:
    """两矩形交并比。"""
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = (max(ax1, bx1), max(ay1, by1))
    ix2, iy2 = (min(ax2, bx2), min(ay2, by2))
    iw, ih = (max(0, ix2 - ix1), max(0, iy2 - iy1))
    inter = iw * ih
    if inter == 0:
        return 0.0
    union = _area(a) + _area(b) - inter
    return inter / union if union else 0.0

@dataclass
class _WalkState:
    count: int = 0
    flat: list = field(default_factory=list)

def _walk_uia(control, depth: int, state: _WalkState, wid: int, parent_id: int=0):
    """递归把 UIA 控件转成 dict；同时把带坐标的节点登记进 flat 供后续匹配。"""
    if state.count >= MAX_NODES or depth > MAX_DEPTH:
        return None
    rect = control.BoundingRectangle
    node_rect = (rect.left, rect.top, rect.right, rect.bottom)
    state.count += 1
    node_id = state.count
    try:
        name = control.Name or ''
    except Exception:
        name = ''
    try:
        visible = not control.IsOffscreen
    except Exception:
        visible = True
    try:
        enabled = control.IsEnabled
    except Exception:
        enabled = True
    try:
        sel_pat = control.GetSelectionItemPattern()
        selected = bool(sel_pat.IsSelected) if sel_pat else False
    except Exception:
        selected = False
    node = {'id': node_id, 'parent_id': parent_id, 'name': name, 'control_type': control.ControlTypeName, 'automation_id': getattr(control, 'AutomationId', '') or '', 'class_name': control.ClassName, 'rect': node_rect, 'visible': visible, 'enabled': enabled, 'image_confirmed': False, 'visible_text': '', 'selected': selected, 'children': []}
    if _area(node_rect) > 0:
        state.flat.append(node)
    if depth < MAX_DEPTH:
        try:
            for child in control.GetChildren():
                sub = _walk_uia(child, depth + 1, state, wid, node_id)
                if sub:
                    node['children'].append(sub)
        except Exception as exc:
            _LOGGER.debug('遍历子节点失败: %s', exc)
    return node

def build_uia_tree(hwnd: int) -> dict:
    """从窗口句柄构建 UIA 控件树（含扁平索引）。"""
    import uiautomation as auto
    root_control = auto.ControlFromHandle(hwnd)
    state = _WalkState()
    tree = _walk_uia(root_control, 0, state, hwnd)
    if tree is None:
        tree = {'id': 0, 'name': '', 'control_type': 'Window', 'automation_id': '', 'class_name': '', 'rect': (0, 0, 0, 0), 'visible': True, 'enabled': True, 'image_confirmed': False, 'visible_text': '', 'selected': False, 'children': []}
    return {'tree': tree, 'flat': state.flat, 'node_count': state.count}

def image_retrieval(screenshot_path: str) -> list:
    """对窗口截图 OCR，返回 [{text, rect}, ...]；rect 为 (左,上,右,下)。"""
    boxes = ocr_boxes(screenshot_path)
    out = []
    for text, rect in boxes:
        if _area(rect) <= 0:
            continue
        out.append({'text': text, 'rect': rect})
    return out

def _name_match(ocr_text: str, node_name: str) -> bool:
    """OCR 文本与节点名称双向包含匹配（容错截断与大小写）。"""
    a, b = (_norm_text(ocr_text), _norm_text(node_name))
    if not a or not b:
        return False
    return a in b or b in a

def find_control(model: dict, name: str | None=None, automation_id: str | None=None, control_type: str | None=None):
    """在实时世界模型的 UIA 树里按名称/automation_id/控件类型定位最佳节点。

    这是 Atlas 静态地图与实际运行态之间的桥：规划阶段查 Atlas 知道「有什么」，
    执行阶段仍必须重新 build_world_model 拿到实时树，再经本函数解析目标控件坐标——
    绝不直接用 Atlas 的坐标当运行时位置。
    优先 image_confirmed（OCR 佐证可见）+ enabled + 面积最小（最精确命中）。
    返回 (匹配节点, 屏幕中心(x,y))；无命中返回 (None, None)。
    """
    tree = (model or {}).get('uia_tree')
    if not tree:
        return (None, None)
    ct_want = control_type
    candidates = []
    for n in _iter_nodes(tree):
        if not n.get('visible') or _area(n.get('rect', (0, 0, 0, 0))) <= 0:
            continue
        node_ct = n.get('control_type', '') or ''
        if ct_want and node_ct not in (ct_want, ct_want + 'Control'):
            continue
        if automation_id and (n.get('automation_id') or '') != automation_id:
            continue
        if name:
            node_name = (n.get('name') or '').strip()
            if not node_name or name.lower() not in node_name.lower():
                continue
        candidates.append(n)
    if not candidates:
        return (None, None)
    candidates.sort(key=lambda n: (not n.get('image_confirmed'), not n.get('enabled'), _area(n['rect'])))
    best = candidates[0]
    cx, cy = _center(best['rect'])
    return (best, (int(cx), int(cy)))

def _match_ocr_to_uia(ocr_items: list, flat: list, tree_root: dict, target_hwnd: int) -> tuple:
    """把每个 OCR 文本盒归属到 UIA 树，双策略：

    1) 语义归属（优先）：归属链上至少一个节点名称命中 OCR 文本才算认领。
    2) 几何兜底（强化状态文本）：无名称命中、但文本中心点经像素所有权测试确属目标窗口时，
       归属到最小可见包含节点。这类文本通常是设置里的状态描述（"已连接，安全"等），
       控件本身无名。兜底以 WindowFromPoint 判定真实可见归属，叠在目标之上的别窗文本永不误认领。
    调用方需保证 ocr_items 的 rect 为屏幕坐标，同时带 rect_img 以备渲染。
    """
    by_id = {n['id']: n for n in flat}

    def ancestors(node):
        chain = []
        cur = node
        while cur and cur['id']:
            chain.append(cur)
            pid = cur.get('parent_id', 0)
            cur = by_id.get(pid)
        return chain
    matched, image_only = ([], [])
    for item in ocr_items:
        sem_candidates = []
        geo_candidates = []
        cx, cy = _center(item['rect'])
        in_target = _point_owned_by(target_hwnd, cx, cy)
        for node in flat:
            if _area(node['rect']) <= 0 or not node['visible']:
                continue
            if not _contains(node['rect'], item['rect']):
                continue
            chain_names = ' '.join((n.get('name', '') for n in ancestors(node)))
            if _name_match(item['text'], chain_names):
                sem_candidates.append(node)
            elif in_target:
                geo_candidates.append(node)
        if sem_candidates:
            best = min(sem_candidates, key=lambda n: _area(n['rect']))
            via = [n['control_type'] for n in ancestors(best)[:3]]
        elif geo_candidates:
            best = min(geo_candidates, key=lambda n: _area(n['rect']))
            via = ['geometric'] + [n['control_type'] for n in ancestors(best)[:3]]
        else:
            image_only.append({'text': item['text'], 'rect': item['rect'], 'rect_img': item.get('rect_img', item['rect'])})
            continue
        best['image_confirmed'] = True
        best['visible_text'] = item['text']
        matched.append({'text': item['text'], 'rect': item['rect'], 'rect_img': item.get('rect_img', item['rect']), 'uia_id': best['id'], 'uia_control_type': best['control_type'], 'matched_via': via})
    return (matched, image_only)

def _collect_structure_only(flat: list) -> list:
    """可见、未被 OCR 确认、自身无名且无文本子节点的 UIA 节点（图标/图形/空容器）。"""
    out = []
    confirmed_ids = {n['id'] for n in flat if n['image_confirmed']}

    def has_confirmed_child(node) -> bool:
        for c in node.get('children', []):
            if c['id'] in confirmed_ids or has_confirmed_child(c):
                return True
        return False
    for node in flat:
        if not node['visible'] or _area(node['rect']) <= 0:
            continue
        if node['image_confirmed']:
            continue
        if node['name']:
            continue
        if has_confirmed_child(node):
            continue
        out.append({'id': node['id'], 'control_type': node['control_type'], 'class_name': node['class_name'], 'rect': node['rect']})
    return out[:200]

def _build_visible_layer(ocr_items: list, root_rect: tuple) -> list:
    """二维包含树：以整屏为最外层，按面积升序把每个 OCR 文本盒挂到最小包含者之下。

    这给出"屏幕上什么文字落在哪个区域里"的可见层级，可作为 UIA 树之外的像素级佐证。
    """
    regions = [{'id': 'root', 'rect': root_rect, 'label': '整屏根'}]
    for i, item in enumerate(ocr_items):
        regions.append({'id': f't{i}', 'rect': item['rect'], 'label': item['text']})
    regions.sort(key=lambda r: _area(r['rect']))
    nodes = {r['id']: {**r, 'children': []} for r in regions}
    roots = []
    for r in regions:
        parent = None
        for p in regions:
            if p is r:
                continue
            if _contains(p['rect'], r['rect']) and _area(p['rect']) > _area(r['rect']) + 1:
                if parent is None or _area(p['rect']) < _area(parent['rect']):
                    parent = p
        if parent:
            nodes[parent['id']]['children'].append(nodes[r['id']])
        else:
            roots.append(nodes[r['id']])
    return roots

def fuse(uia_result: dict, ocr_items: list, target_hwnd: int, root_rect: tuple) -> dict:
    """融合两条通道，产出可见层级与三张清单，并回写标注到 UIA 树。

    target_hwnd = 聚焦窗口句柄（像素所有权测试判定文本真实归属，排除叠放的别窗）；
    root_rect = 整屏矩形（可见层级根）。
    """
    flat = uia_result['flat']
    tree_root = uia_result['tree']
    matched, image_only = _match_ocr_to_uia(ocr_items, flat, tree_root, target_hwnd)
    structure_only = _collect_structure_only(flat)
    visible_layer = _build_visible_layer(ocr_items, root_rect)
    return {'visible_layer': visible_layer, 'ocr_matched': matched, 'image_only': image_only, 'structure_only': structure_only}

def render_world_model(model: dict, screenshot_path: str, out_png: str, window_rect: tuple) -> str:
    """在截图上叠加包围盒与标签，输出标注图。

    绿框=OCR 命中的 UIA 节点；橙框=图像独有（UIA 漏掉）；浅蓝框=结构独有（可见无文本）。
    截图坐标系：summary 里的 rect_img 直接用；structure_only/其它屏幕坐标 rect 需减去窗口原点。
    """
    img = Image.open(screenshot_path).convert('RGB')
    draw = ImageDraw.Draw(img)
    font = _load_font(16)
    palette = {'matched': (0, 170, 0), 'image': (230, 120, 0), 'struct': (70, 130, 220)}
    wx, wy, wr, wb = window_rect
    summary = model['visible_layer_summary']

    def to_img(rect):
        return rect

    def draw_box(rect, color, label):
        l, t, r, b = rect
        draw.rectangle([l, t, r, b], outline=color, width=2)
        if label:
            draw.text((l, max(0, t - 18)), label, fill=color, font=font)
    draw.rectangle([wx, wy, wr, wb], outline=(110, 110, 230), width=2)
    for item in summary['ocr_matched']:
        draw_box(item.get('rect_img') or to_img(item['rect']), palette['matched'], '')
    for item in summary['image_only']:
        draw_box(item.get('rect_img') or to_img(item['rect']), palette['image'], '')
    for item in summary['structure_only'][:60]:
        draw_box(to_img(item['rect']), palette['struct'], '')
    legend = ['绿=OCR命中UIA', '橙=图像独有', '蓝=结构独有(可见无文本)']
    y = 10
    for text in legend:
        draw.text((10, y), text, fill=(255, 255, 255), font=font)
        draw.text((11, y + 1), text, fill=(0, 0, 0), font=font)
        y += 22
    img.save(out_png)
    return out_png

def render_world_model_svg(model: dict, out_svg: str) -> str:
    """把 world_model 渲染成结构化 SVG：混合架构 + 三张清单 + 已确认控件树 + 图像独有。"""
    meta = model['meta']
    confirmed = []
    _walk_confirmed(model['uia_tree'], 0, confirmed)
    image_only = [x['text'] for x in model['visible_layer_summary']['image_only'][:10]]
    counts = [(len(model['visible_layer_summary']['ocr_matched']), '#1a7a3a', 'OCR 命中 UIA'), (len(model['visible_layer_summary']['image_only']), '#c8771a', '图像独有'), (len(model['visible_layer_summary']['structure_only']), '#3a6fc8', '结构独有')]
    W = 680
    parts = [f'<svg viewBox="0 0 {W} 980" xmlns="http://www.w3.org/2000/svg" font-family="Microsoft YaHei,Segoe UI,sans-serif">', '<rect width="100%" height="100%" fill="#fafafa"/>', '<text x="20" y="28" font-size="16" font-weight="700" fill="#1a1a1a">GUI 世界模型 · 混合架构与结构化输出</text>', f"""<text x="20" y="48" font-size="11" fill="#555">目标={meta['target']} · 标题={meta['title']} · 窗口={meta['window_rect']}</text>"""]

    def box(x, y, w, h, fill, stroke):
        parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{fill}" stroke="{stroke}" stroke-width="1.2"/>')
    box(20, 70, 150, 60, '#e3f0ff', '#5a8ec8')
    parts.append('<text x="95" y="95" font-size="12" font-weight="600" text-anchor="middle" fill="#1a3a5c">UIA 结构通道</text>')
    parts.append(f"""<text x="95" y="113" font-size="11" text-anchor="middle" fill="#1a3a5c">{meta['uia_node_count']} 个控件节点</text>""")
    box(265, 70, 150, 60, '#fff1e3', '#c8865a')
    parts.append('<text x="340" y="95" font-size="12" font-weight="600" text-anchor="middle" fill="#5c3a1a">图像检索通道</text>')
    parts.append(f"""<text x="340" y="113" font-size="11" text-anchor="middle" fill="#5c3a1a">{meta['ocr_box_count']} 个 OCR 文本</text>""")
    box(510, 70, 150, 60, '#e8f5e3', '#5aa86b')
    parts.append('<text x="585" y="95" font-size="12" font-weight="600" text-anchor="middle" fill="#1a5c2a">融合输出</text>')
    parts.append('<text x="585" y="113" font-size="11" text-anchor="middle" fill="#1a5c2a">3 张清单 + 可见层级</text>')
    for x1, x2 in [(170, 265), (415, 510)]:
        parts.append(f'<path d="M{x1}100 L{x2 - 8}100 M{x2 - 8}96 L{x2}100 L{x2 - 8}104" stroke="#888" stroke-width="1.2" fill="none"/>')
    for i, (c, col, lab) in enumerate(counts):
        x = 20 + i * 225
        box(x, 155, 210, 42, '#fff', '#ccc')
        parts.append(f'<text x="{x + 12}" y="173" font-size="12" font-weight="600" fill="{col}">{lab}</text>')
        parts.append(f'<text x="{x + 12}" y="190" font-size="11" fill="#333">数量：{c}</text>')
    parts.append('<line x1="20" y1="220" x2="660" y2="220" stroke="#ddd"/>')
    parts.append('<text x="20" y="240" font-size="13" font-weight="700" fill="#1a1a1a">已确认的 UIA 控件树（语义归属）</text>')
    parts.append(f'<text x="20" y="256" font-size="10" fill="#777">共 {len(confirmed)} 个节点的名称与 OCR 文本匹配</text>')
    ty = 278
    for d, t, name in confirmed:
        if ty > 860:
            break
        x = 20 + d * 14
        if d:
            parts.append(f'<line x1="{x - 10}" y1="{ty + 5}" x2="{x}" y2="{ty + 5}" stroke="#bbb" stroke-width="1"/>')
        parts.append(f'<rect x="{x}" y="{ty}" width="9" height="9" rx="2" fill="#1a7a3a"/>')
        parts.append(f'<text x="{x + 14}" y="{ty + 9}" font-size="11" fill="#333"><tspan fill="#888">{t}</tspan> {name}</text>')
        ty += 15
    parts.append('<text x="20" y="880" font-size="12" font-weight="700" fill="#c8771a">图像独有（OCR 见到但 UIA 未认领）</text>')
    tx, ty2 = (20, 900)
    for txt in image_only:
        s = txt[:14] + '…' if len(txt) > 15 else txt
        parts.append(f'<rect x="{tx}" y="{ty2 - 10}" width="{len(s) * 7 + 12}" height="15" rx="3" fill="#fff1e3" stroke="#c8865a" stroke-width="0.8"/>')
        parts.append(f'<text x="{tx + 6}" y="{ty2 + 2}" font-size="10" fill="#5c3a1a">{s}</text>')
        tx += len(s) * 7 + 22
        if tx > 640:
            tx = 20
            ty2 += 20
    parts.append('</svg>')
    with open(out_svg, 'w', encoding='utf-8') as fh:
        fh.write(''.join(parts))
    return out_svg

def build_world_model(target: str | int | None=None, save_dir: str='', mode: str='') -> dict:
    """构建某个窗口的 GUI 世界模型。

    target: 窗口标题子串（str）或 hwnd（int）；None 取前台窗口。
    mode: "window"（默认，仅 OCR 目标窗口区域，快）或 "full"（全屏采集）；
          空值读环境变量 PALM_OCR_MODE，再缺省 "window"。
    返回 world_model dict，并落盘 JSON 与标注 PNG（路径写在 meta 里）。
    """
    import uiautomation as auto
    if isinstance(target, int):
        hwnd = target
    elif isinstance(target, str) and target:
        found = find_window(target)
        if not found:
            raise RuntimeError(f'找不到标题含 {target!r} 的窗口')
        hwnd = found[0]
    else:
        hwnd = auto.GetForegroundControl().NativeWindowHandle
    root_control = auto.ControlFromHandle(hwnd)
    try:
        title = root_control.Name or ''
    except Exception:
        title = ''
    try:
        rect = root_control.BoundingRectangle
        window_rect = (rect.left, rect.top, rect.right, rect.bottom)
    except Exception:
        window_rect = (0, 0, 0, 0)
    save_dir = save_dir or os.path.join(tempfile.gettempdir(), 'palm_worldmodel')
    os.makedirs(save_dir, exist_ok=True)
    stamp = time.strftime('%Y%m%d_%H%M%S')
    shot_path = os.path.join(save_dir, f'wm_{stamp}.png')
    mode = mode or os.environ.get('PALM_OCR_MODE', 'window')
    offset = (0, 0)
    if mode == 'window' and window_rect[2] > window_rect[0] and (window_rect[3] > window_rect[1]):
        left, top, right, bottom = window_rect
        try:
            pyautogui.screenshot(shot_path, region=(left, top, right - left, bottom - top))
            offset = (left, top)
            SW, SH = pyautogui.size()
        except Exception:
            pyautogui.screenshot(shot_path)
            with Image.open(shot_path) as _im:
                SW, SH = _im.size
    else:
        pyautogui.screenshot(shot_path)
        with Image.open(shot_path) as _im:
            SW, SH = _im.size
    screen_rect = (0, 0, SW, SH)
    uia_result = build_uia_tree(hwnd)
    ocr_items_img = image_retrieval(shot_path)
    ocr_items = []
    for it in ocr_items_img:
        l, t, r, b = it['rect']
        if offset != (0, 0):
            l += offset[0]
            t += offset[1]
            r += offset[0]
            b += offset[1]
        ocr_items.append({'text': it['text'], 'rect': (l, t, r, b), 'rect_img': it['rect']})
    fusion = fuse(uia_result, ocr_items, hwnd, screen_rect)
    model = {'meta': {'target': str(target) if target else 'foreground', 'hwnd': hwnd, 'title': title, 'window_rect': window_rect, 'screenshot_size': (SW, SH), 'timestamp': stamp, 'uia_node_count': uia_result['node_count'], 'ocr_box_count': len(ocr_items), 'screenshot': shot_path}, 'uia_tree': uia_result['tree'], 'visible_layer': fusion['visible_layer'], 'visible_layer_summary': {'ocr_matched': fusion['ocr_matched'], 'image_only': fusion['image_only'], 'structure_only': fusion['structure_only']}}
    json_path = os.path.join(save_dir, f'wm_{stamp}.json')
    with open(json_path, 'w', encoding='utf-8') as fh:
        json.dump(model, fh, ensure_ascii=False, indent=2)
    render_path = os.path.join(save_dir, f'wm_{stamp}_render.png')
    render_world_model(model, shot_path, render_path, window_rect)
    svg_path = os.path.join(save_dir, f'wm_{stamp}_structure.svg')
    render_world_model_svg(model, svg_path)
    model['meta']['json'] = json_path
    model['meta']['render'] = render_path
    model['meta']['structure_svg'] = svg_path
    try:
        from .world_model_cache import derive_and_merge
        derive_and_merge(model)
    except Exception as _atlas_err:
        _LOGGER.warning('Atlas 动态认知落盘失败（不影响世界模型产出）: %s', _atlas_err)
    return model

def render_from_document(json_path: str, out_png: str | None=None) -> str:
    """纯靠结构化文档（JSON）重建可视化图 —— 全程不读取任何像素/截图。

    画布尺寸取自 window_rect；屏幕坐标经 window_rect 左上平移到截图坐标，
    ocr_matched / image_only 直接用已落盘的 rect_img。证明世界模型文档自包含：
    即便丢失原始截图，仅靠结构化数据也能复原布局语义图。
    浅灰底代表「无像素、纯结构」；绿=OCR 命中 UIA，橙=图像独有，蓝=结构独有。
    """
    with open(json_path, encoding='utf-8') as fh:
        model = json.load(fh)
    meta = model['meta']
    wx, wy, wr, wb = meta['window_rect']
    sw, sh = meta.get('screenshot_size', (max(1, wr - wx), max(1, wb - wy)))
    W, H = (sw, sh)
    img = Image.new('RGB', (W, H), (243, 243, 243))
    draw = ImageDraw.Draw(img, 'RGBA')
    font = _load_font(15)
    small = _load_font(11)
    palette = {'matched': (0, 150, 0), 'image': (214, 110, 0), 'struct': (60, 120, 210)}
    summary = model['visible_layer_summary']
    draw.rectangle([wx, wy, wr, wb], outline=(110, 110, 230), width=2)
    for item in summary['structure_only']:
        l, t, r, b = item['rect']
        draw.rectangle([l, t, r, b], outline=palette['struct'], width=2)
        label = item['control_type'].replace('Control', '') or '控件'
        draw.text((l, max(0, t - 14)), label, fill=palette['struct'], font=small)
    for item in summary['ocr_matched']:
        l, t, r, b = item['rect_img']
        draw.rectangle([l, t, r, b], outline=palette['matched'], width=2)
        draw.text((l, max(0, t - 14)), item['text'], fill=palette['matched'], font=small)
    for item in summary['image_only']:
        l, t, r, b = item['rect_img']
        draw.rectangle([l, t, r, b], outline=palette['image'], width=2)
        draw.text((l, max(0, t - 14)), item['text'], fill=palette['image'], font=small)
    lx, ly = (10, 10)
    draw.rectangle([lx, ly, lx + 16, ly + 16], outline=palette['matched'], width=2)
    draw.text((lx + 22, ly + 2), 'OCR 命中 UIA', fill=(40, 40, 40), font=small)
    draw.rectangle([lx, ly + 22, lx + 16, ly + 38], outline=palette['image'], width=2)
    draw.text((lx + 22, ly + 24), '图像独有（UIA 未认领）', fill=(40, 40, 40), font=small)
    draw.rectangle([lx, ly + 44, lx + 16, ly + 60], outline=palette['struct'], width=2)
    draw.text((lx + 22, ly + 46), '结构独有（可见无文本）', fill=(40, 40, 40), font=small)
    caption = f"纯文档渲染 · 目标={meta['target']} · 窗口={meta['window_rect']}"
    draw.text((lx, ly + 66), caption, fill=(90, 90, 90), font=small)
    out_png = out_png or json_path.rsplit('.', 1)[0] + '_from_doc.png'
    img.save(out_png)
    return out_png
if __name__ == '__main__':
    import sys
    argv = sys.argv[1:]
    if '--from-doc' in argv:
        idx = argv.index('--from-doc')
        json_path = argv[idx + 1]
        out_png = argv[idx + 2] if len(argv) > idx + 2 else None
        out = render_from_document(json_path, out_png)
        print(json.dumps({'mode': 'from-doc', 'source': json_path, 'out': out}, ensure_ascii=False, indent=2))
        sys.exit(0)
    arg = argv[0] if argv else None
    try:
        m = build_world_model(arg)
    except Exception as exc:
        print('世界模型构建失败:', exc)
        sys.exit(1)
    print(json.dumps({'target': m['meta']['target'], 'title': m['meta']['title'], 'window_rect': m['meta']['window_rect'], 'uia_node_count': m['meta']['uia_node_count'], 'ocr_box_count': m['meta']['ocr_box_count'], 'ocr_matched': len(m['visible_layer_summary']['ocr_matched']), 'image_only': len(m['visible_layer_summary']['image_only']), 'structure_only': len(m['visible_layer_summary']['structure_only']), 'json': m['meta']['json'], 'render': m['meta']['render'], 'structure_svg': m['meta']['structure_svg']}, ensure_ascii=False, indent=2))
